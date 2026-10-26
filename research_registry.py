"""Durable research identity, conversation history, placement and recovery.

The registry never grants sandbox permissions. Existing folders are indexed in place.
"""
import contextlib
import hashlib
import fcntl
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path


def uid(prefix): return prefix+'-'+uuid.uuid4().hex

def stamp(): return time.time()

def encode(value): return json.dumps(value,ensure_ascii=False)

class Registry:
    def __init__(self, app, source, read_only=False):
        self.app=Path(app).resolve();self.original_source=Path(os.path.abspath(source));self.source=Path(source).resolve();self.db=self.app/'research.sqlite3'
        self.read_only=read_only
        self.project_info={}
        manifest=self.app/'project.json'
        if manifest.exists():self.project_info=json.loads(manifest.read_text())
        if read_only:
            with self.connect() as db:
                existing=db.execute("SELECT value FROM manager_state WHERE key='source_root'").fetchone()
                if not existing or existing['value']!=str(self.source):raise ValueError('This registry belongs to a different research root')
            return
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS research_nodes(
              id TEXT PRIMARY KEY, title TEXT NOT NULL, role TEXT NOT NULL, path TEXT UNIQUE,
              parent_id TEXT, observed_parent_id TEXT, description TEXT NOT NULL DEFAULT '',
              present INTEGER NOT NULL DEFAULT 1, revision INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS research_links(source_id TEXT NOT NULL,target_id TEXT NOT NULL,relation TEXT NOT NULL,evidence TEXT NOT NULL,PRIMARY KEY(source_id,target_id,relation));
            CREATE TABLE IF NOT EXISTS node_aliases(alias TEXT PRIMARY KEY,node_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS node_paths(path TEXT PRIMARY KEY,node_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_conversations(
              id TEXT PRIMARY KEY,node_id TEXT NOT NULL,binding TEXT NOT NULL,objective TEXT NOT NULL,
              status TEXT NOT NULL,workspace TEXT,native_id TEXT,transcript_path TEXT,
              transcript_offset INTEGER NOT NULL DEFAULT 0,review TEXT NOT NULL DEFAULT 'pending',
              briefing TEXT NOT NULL DEFAULT '',created REAL NOT NULL,updated REAL NOT NULL,
              predecessor TEXT,revision INTEGER NOT NULL DEFAULT 1);
            CREATE UNIQUE INDEX IF NOT EXISTS conversation_native_id ON research_conversations(native_id) WHERE native_id IS NOT NULL;
            CREATE TABLE IF NOT EXISTS conversation_selection(node_id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS research_events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT,event_key TEXT UNIQUE,kind TEXT NOT NULL,
              conversation_id TEXT,node_id TEXT,payload TEXT NOT NULL,source TEXT NOT NULL,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS research_checkpoints(
              id INTEGER PRIMARY KEY AUTOINCREMENT,conversation_id TEXT NOT NULL,summary TEXT NOT NULL,
              details TEXT NOT NULL,through_seq INTEGER NOT NULL,created REAL NOT NULL,source TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS manager_jobs(
              id TEXT PRIMARY KEY,dedupe TEXT UNIQUE,conversation_id TEXT,kind TEXT NOT NULL,
              payload TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
              next_at REAL NOT NULL DEFAULT 0,lease_until REAL NOT NULL DEFAULT 0,result TEXT,error TEXT,
              created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS manager_state(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS placement_plans(
              id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL,parent_id TEXT NOT NULL,path TEXT NOT NULL,
              specification TEXT NOT NULL,state TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,
              node_id TEXT,created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS research_executions(
              id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL,node_id TEXT NOT NULL,
              command TEXT NOT NULL,cwd TEXT NOT NULL,status TEXT NOT NULL,pid INTEGER,exit_code INTEGER,
              evidence TEXT NOT NULL DEFAULT '{}',created REAL NOT NULL,updated REAL NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS active_execution_node ON research_executions(node_id)
              WHERE status='running';
            ''')
            existing=db.execute("SELECT value FROM manager_state WHERE key='source_root'").fetchone()
            if existing and existing['value']!=str(self.source):raise ValueError('This registry belongs to a different research root; use a separate application workspace')
            db.execute("INSERT OR IGNORE INTO manager_state VALUES('source_root',?)",(str(self.source),))

    def connect(self):
        db=sqlite3.connect(self.db.as_uri()+'?mode=ro',uri=True,timeout=15) if self.read_only else sqlite3.connect(self.db,timeout=15)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA busy_timeout=15000');return db

    @contextlib.contextmanager
    def transaction(self):
        db=self.connect()
        try:
            db.execute('BEGIN IMMEDIATE');yield db;db.commit()
        except Exception: db.rollback();raise
        finally: db.close()

    def _event(self,db,kind,cid=None,nid=None,payload=None,source='application',key=None):
        db.execute('INSERT OR IGNORE INTO research_events(event_key,kind,conversation_id,node_id,payload,source,created) VALUES(?,?,?,?,?,?,?)',
                   (key,kind,cid,nid,encode(payload or {}),source,stamp()))
        return db.execute('SELECT seq FROM research_events WHERE event_key=?',(key,)).fetchone()[0] if key else db.execute('SELECT last_insert_rowid()').fetchone()[0]

    def _job(self,db,cid,kind,payload,key):
        if kind in ('summary','review') and db.execute("SELECT 1 FROM manager_jobs WHERE conversation_id=? AND kind=? AND state IN ('pending','retry')",(cid,kind)).fetchone():return
        db.execute('INSERT OR IGNORE INTO manager_jobs(id,dedupe,conversation_id,kind,payload,created) VALUES(?,?,?,?,?,?)',
                   (uid('job'),key,cid,kind,encode(payload),stamp()))

    def lexical_path(self,target):
        target=str(target)
        if self.project_info:
            info=self.project_info
            for previous in info.get('previous_roots',[]):
                candidate=target if target==previous or target.startswith(previous+'/') else os.path.realpath(target)
                if candidate==previous or candidate.startswith(previous+'/'):target=str(self.source)+candidate[len(previous):];break
            legacy=info.get('imported_legacy')
            if legacy and (target==legacy or target.startswith(legacy+'/')):target=str(self.app)+target[len(legacy):]
        path=Path(os.path.abspath(target))
        return str(self.source/path.relative_to(self.original_source)) if path.is_relative_to(self.original_source) else str(path)

    def resolve(self,target,db=None):
        if db is None:
            with self.connect() as conn:return self.resolve(target,conn)
        row=db.execute('SELECT n.* FROM research_nodes n LEFT JOIN node_aliases a ON a.node_id=n.id WHERE n.id=? OR a.alias=? LIMIT 1',(target,target)).fetchone()
        if not row:
            path=self.lexical_path(target) if target and (target.startswith('/') or '/' in target) else ''
            row=db.execute('SELECT n.* FROM research_nodes n JOIN node_paths p ON n.id=p.node_id WHERE p.path=?',(path,)).fetchone()
        if not row:raise ValueError('Unknown node: '+str(target))
        return dict(row)

    def sync_nodes(self,model):
        """Adopt legacy IDs as aliases. Metadata IDs survive explicit path changes."""
        records=model.get('nodes',[]);mapping={};paths={}
        with self.transaction() as db:
            db.execute('UPDATE research_nodes SET present=0 WHERE path IS NOT NULL')
            for record in records:
                folders=record.get('storage',{}).get('folders',[])
                if not folders:continue
                path=self.lexical_path(folders[0])
                if not Path(path).is_relative_to(self.source):continue
                existing=db.execute('SELECT * FROM research_nodes WHERE path=?',(path,)).fetchone()
                legacy=db.execute('SELECT node_id FROM node_aliases WHERE alias=?',(record['id'],)).fetchone()
                metadata_id=None
                meta=Path(path)/'metadata.json'
                # Only consider explicit schema metadata, and never follow an outside symlink.
                if meta.is_file() and meta.resolve().is_relative_to(self.source) and meta.stat().st_size<100000:
                    try:
                        data=json.loads(meta.read_text());candidate=data.get('node_id','') if isinstance(data,dict) else ''
                        if isinstance(data,dict) and data.get('schema_version')==1 and re.fullmatch(r'node-[0-9a-f]{32}',candidate):metadata_id=candidate
                    except (ValueError,OSError):pass
                nid=existing['id'] if existing else (legacy['node_id'] if legacy else metadata_id or uid('node'))
                if metadata_id and not existing and not legacy:
                    prior=db.execute('SELECT path FROM research_nodes WHERE id=?',(metadata_id,)).fetchone()
                    if prior and prior['path']!=path and Path(prior['path'] or '').exists():
                        # A copied package is not silently merged with a live original.
                        nid=uid('node');self._event(db,'identity_conflict',nid=nid,payload={'path':path,'copied_id':metadata_id})
                role='project' if record['id']==model.get('root_id') else 'analysis' if record.get('inspectable') else 'collection'
                if not db.execute('SELECT 1 FROM research_nodes WHERE id=?',(nid,)).fetchone():
                    db.execute('INSERT INTO research_nodes(id,title,role,path,description) VALUES(?,?,?,?,?)',(nid,record['title'],role,path,record.get('description','')))
                else:
                    previous=db.execute('SELECT path FROM research_nodes WHERE id=?',(nid,)).fetchone()['path']
                    if previous!=path:self._event(db,'storage_path_changed',nid=nid,payload={'old':previous,'new':path})
                    db.execute('UPDATE research_nodes SET title=?,path=?,present=1 WHERE id=?',(record['title'],path,nid))
                db.execute('INSERT OR REPLACE INTO node_aliases VALUES(?,?)',(record['id'],nid))
                db.execute('INSERT OR REPLACE INTO node_paths VALUES(?,?)',(path,nid))
                mapping[record['id']]=nid;paths[nid]=path
            for record in records:
                nid=mapping.get(record['id']);parent=mapping.get(record.get('parent_id'))
                if nid:
                    db.execute('UPDATE research_nodes SET observed_parent_id=?,parent_id=COALESCE(parent_id,?) WHERE id=?',(parent,parent,nid))
            if model.get('root_id') in mapping:
                db.execute('INSERT OR REPLACE INTO node_aliases VALUES(?,?)',('project:root',mapping[model['root_id']]))
        return mapping

    def excluded_conversations(self,db):
        excluded={r[0] for r in db.execute("SELECT conversation_id FROM research_events WHERE kind='native_session_excluded'")}
        deleted=db.execute("""SELECT e.conversation_id FROM research_events e
            WHERE e.kind='conversation_deleted' AND e.seq=(SELECT MAX(x.seq) FROM research_events x
            WHERE x.conversation_id=e.conversation_id AND x.kind IN ('conversation_deleted','conversation_restored'))""")
        return excluded|{r[0] for r in deleted}

    def delete_conversation(self,cid,restore=False):
        with self.transaction() as db:
            conv=self.conversation(cid,db)
            self._event(db,'conversation_restored' if restore else 'conversation_deleted',cid,conv['node_id'],{},'user')
            if not restore:db.execute('DELETE FROM conversation_selection WHERE conversation_id=?',(cid,))
        return {'ok':True,'conversation_id':cid,'deleted':not restore}

    def conversations(self,node=None):
        with self.connect() as db:
            if node:
                nid=self.resolve(node,db)['id'];rows=db.execute('SELECT * FROM research_conversations WHERE node_id=? ORDER BY updated DESC',(nid,))
            else:rows=db.execute('SELECT * FROM research_conversations ORDER BY updated DESC LIMIT 200')
            result=[dict(r) for r in rows]
            hooked={r[0] for r in db.execute("SELECT DISTINCT conversation_id FROM research_events WHERE source='native_hook'")}
            for item in result:item['tracking_mode']='native hooks' if item['id'] in hooked else 'native transcript (hooks not confirmed)' if item['native_id'] else 'awaiting native session'
            excluded=self.excluded_conversations(db)
            return [item for item in result if item['id'] not in excluded]

    def node_conversations(self,target):
        node=self.resolve(target)
        with self.connect() as db:
            creators={r[0] for r in db.execute("SELECT conversation_id FROM placement_plans WHERE node_id=? AND state='created'",(node['id'],))}
            executors={r[0] for r in db.execute('SELECT DISTINCT conversation_id FROM research_executions WHERE node_id=?',(node['id'],))}
            ids=creators|executors
            ids.update(r[0] for r in db.execute('SELECT id FROM research_conversations WHERE node_id=?',(node['id'],)))
            excluded=self.excluded_conversations(db)
            hooked={r[0] for r in db.execute("SELECT DISTINCT conversation_id FROM research_events WHERE source='native_hook'")}
            conversations=[]
            for cid in ids-excluded:
                item=self.conversation(cid,db)
                item['node_title']=self.resolve(item['node_id'],db)['title']
                item['node_relationship']='Bound to this node' if item['node_id']==node['id'] else 'Created this analysis' if cid in creators else 'Executed this analysis'
                item['tracking_mode']='native hooks' if cid in hooked else 'native transcript (hooks not confirmed)' if item['native_id'] else 'awaiting native session'
                conversations.append(item)
        conversations.sort(key=lambda c:(c['node_id']!=node['id'],-c['updated']))
        return {'node':node,'conversations':conversations}

    def conversation(self,cid,db=None):
        if db is None:
            with self.connect() as conn:return self.conversation(cid,conn)
        row=db.execute('SELECT * FROM research_conversations WHERE id=?',(cid,)).fetchone()
        if not row:raise ValueError('Unknown conversation')
        return dict(row)

    def register(self,binding,objective='',new=False,cid=None,predecessor=None):
        with self.transaction() as db:
            node=self.resolve(binding,db)
            if cid:
                item=self.conversation(cid,db)
                if cid in self.excluded_conversations(db):raise ValueError('Conversation has been deleted')
                if item['node_id']!=node['id']:raise ValueError('Conversation belongs to another node')
                db.execute('INSERT OR REPLACE INTO conversation_selection VALUES(?,?)',(node['id'],cid))
                return item
            chosen=db.execute('SELECT conversation_id FROM conversation_selection WHERE node_id=?',(node['id'],)).fetchone()
            if chosen and not new:
                selected=self.conversation(chosen['conversation_id'],db)
                if selected['id'] not in self.excluded_conversations(db) and selected['status'] not in ('completed','superseded'):return selected
            excluded=self.excluded_conversations(db)
            old=next((r for r in db.execute("SELECT * FROM research_conversations WHERE node_id=? AND status NOT IN ('completed','superseded') ORDER BY created DESC",(node['id'],)) if r['id'] not in excluded),None)
            if old and not new:return dict(old)
            if predecessor:self.conversation(predecessor,db)
            cid=uid('conversation');now=stamp();objective=str(objective).strip()[:12000] or 'Awaiting the first user prompt'
            db.execute('INSERT INTO research_conversations(id,node_id,binding,objective,status,created,updated,predecessor) VALUES(?,?,?,?,?,?,?,?)',
                       (cid,node['id'],binding,objective,'starting',now,now,predecessor))
            db.execute('INSERT OR REPLACE INTO conversation_selection VALUES(?,?)',(node['id'],cid))
            self._event(db,'conversation_started',cid,node['id'],{'objective':objective,'predecessor':predecessor})
            self._job(db,cid,'initial',{},'initial:'+cid)
            return self.conversation(cid,db)

    def attach(self,cid,workspace,native_id=None,transcript_path=None):
        with self.transaction() as db:
            item=self.conversation(cid,db)
            if native_id and not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}',native_id):raise ValueError('Invalid native session ID')
            if item['native_id'] and native_id and native_id!=item['native_id']:
                raise ValueError('A different native session requires a new conversation, not rebinding')
            db.execute("UPDATE research_conversations SET workspace=?,native_id=COALESCE(?,native_id),transcript_path=COALESCE(?,transcript_path),status=CASE WHEN status IN ('starting','interrupted','idle') THEN 'active' ELSE status END,updated=? WHERE id=?",(str(workspace),native_id,transcript_path,stamp(),cid))

    def preferred_conversation(self,binding):
        with self.connect() as db:
            node=self.resolve(binding,db)
            excluded=self.excluded_conversations(db)
            row=db.execute('SELECT c.* FROM research_conversations c JOIN conversation_selection s ON s.conversation_id=c.id WHERE s.node_id=?',(node['id'],)).fetchone()
            if not row or row['id'] in excluded:row=next((r for r in db.execute('SELECT * FROM research_conversations WHERE node_id=? ORDER BY created DESC',(node['id'],)) if r['id'] not in excluded),None)
            return dict(row) if row else None

    @contextlib.contextmanager
    def node_lock(self,nid):
        folder=self.app/'.research'/'locks';folder.mkdir(parents=True,exist_ok=True)
        with (folder/(nid+'.lock')).open('a') as handle:
            try:fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('This analysis is busy; wait for its current write or execution')
            try:yield
            finally:fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

    def hook_event(self,cid,event):
        kind=event.get('hook_event_name','');item=self.conversation(cid)
        native=event.get('session_id');workspace=event.get('cwd') or item['workspace']
        if native:self.attach(cid,workspace,native,event.get('transcript_path'))
        with self.transaction() as db:
            item=self.conversation(cid,db)
            if kind=='UserPromptSubmit':
                prompt=str(event.get('prompt',''))[:12000]
                if item['objective']=='Awaiting the first user prompt':
                    db.execute("UPDATE research_conversations SET objective=?,review='pending',revision=revision+1,updated=? WHERE id=?",(prompt,stamp(),cid))
                seq=self._event(db,'user_prompt',cid,item['node_id'],{'text':prompt},'native_hook',key=cid+':prompt:'+str(event.get('turn_id') or hashlib.sha256(encode(event).encode()).hexdigest()))
                self._job(db,cid,'review',{},'prompt:'+cid+':'+str(seq))
            elif kind in ('Stop','Interrupt','SessionEnd'):
                summary=str(event.get('last_assistant_message') or event.get('reason') or kind)[:24000]
                seq=self._event(db,kind.lower(),cid,item['node_id'],{'summary':summary},'native_hook')
                db.execute('INSERT INTO research_checkpoints(conversation_id,summary,details,through_seq,created,source) VALUES(?,?,?,?,?,?)',
                           (cid,summary,encode({'native_event':kind,'transcript_offset':item['transcript_offset']}),seq,stamp(),'native_hook'))
                status={'Stop':'idle','Interrupt':'interrupted','SessionEnd':'interrupted'}[kind]
                if item['status'] not in ('completed','superseded'):db.execute('UPDATE research_conversations SET status=?,updated=? WHERE id=?',(status,stamp(),cid))
                self._job(db,cid,'summary',{},'summary:'+cid+':'+str(seq))
            elif kind in ('PreToolUse','PostToolUse','SessionStart'):
                self._event(db,kind,cid,item['node_id'],{k:v for k,v in event.items() if k in ('tool_name','tool_input','tool_response','turn_id','source')},'native_hook')

    def checkpoint(self,cid,summary,details=None,status=None):
        if status and status not in ('active','idle','interrupted','completed','superseded','needs_attention'):raise ValueError('Invalid status')
        if not str(summary).strip():raise ValueError('Checkpoint needs a summary')
        with self.transaction() as db:
            item=self.conversation(cid,db);seq=self._event(db,'checkpoint_saved',cid,item['node_id'],{'summary':summary,'details':details or {}},'agent_report')
            db.execute('INSERT INTO research_checkpoints(conversation_id,summary,details,through_seq,created,source) VALUES(?,?,?,?,?,?)',(cid,str(summary)[:24000],encode(details or {}),seq,stamp(),'agent_report'))
            db.execute('UPDATE research_conversations SET status=?,updated=? WHERE id=?',(status or item['status'],stamp(),cid))
            self._job(db,cid,'summary',{},'checkpoint:'+str(seq))
        return self.recovery(cid)

    def search(self,query='',limit=30):
        stop={'has','have','we','already','anything','done','with','for','the','a','an','is','on','of','to','this','and','been','other','conversation','conversations','analysis','analyses','what','which','where','how','do','did','can','you','it','in','any','using'}
        terms=[t for t in re.findall(r'[a-z0-9.]+',str(query).casefold()) if t not in stop]
        with self.connect() as db:
            nodes=[dict(r) for r in db.execute('SELECT * FROM research_nodes')]
            excluded=self.excluded_conversations(db)
            conversations=[dict(r) for r in db.execute('SELECT * FROM research_conversations ORDER BY updated DESC') if r['id'] not in excluded]
        def score(row):
            primary=(row.get('title','')+' '+row.get('objective','')).casefold();all_text=encode(row).casefold()
            return sum(4 if t in primary else 1 if t in all_text else 0 for t in terms)
        def ranked(rows):return sorted((r for r in rows if not terms or score(r)>0),key=score,reverse=True)[:limit]
        return {'nodes':ranked(nodes),'conversations':ranked(conversations),
                'coverage':'Registered app conversations and explicitly imported sessions only. No matching record is not proof work never happened.'}

    def recovery(self,cid):
        with self.connect() as db:
            item=self.conversation(cid,db);node=self.resolve(item['node_id'],db)
            cp=db.execute('SELECT * FROM research_checkpoints WHERE conversation_id=? ORDER BY id DESC LIMIT 1',(cid,)).fetchone()
            events=[dict(r) for r in db.execute('SELECT * FROM research_events WHERE conversation_id=? AND seq>? ORDER BY seq LIMIT 150',(cid,cp['through_seq'] if cp else 0))]
            executions=[dict(r) for r in db.execute('SELECT * FROM research_executions WHERE conversation_id=? ORDER BY created DESC LIMIT 20',(cid,))]
            plans=[dict(r) for r in db.execute('SELECT * FROM placement_plans WHERE conversation_id=? ORDER BY created DESC',(cid,))]
            links=[dict(r) for r in db.execute('SELECT * FROM research_links WHERE source_id=? OR target_id=?',(node['id'],node['id']))]
            predecessor_context=None
            if item['predecessor']:
                previous=self.conversation(item['predecessor'],db)
                previous_cp=db.execute('SELECT * FROM research_checkpoints WHERE conversation_id=? ORDER BY id DESC LIMIT 1',(previous['id'],)).fetchone()
                previous_events=[dict(r) for r in db.execute('SELECT * FROM research_events WHERE conversation_id=? AND seq>? ORDER BY seq LIMIT 50',(previous['id'],previous_cp['through_seq'] if previous_cp else 0))]
                for event in previous_events:event['payload']=json.loads(event['payload'])
                predecessor_context={'conversation':previous,'checkpoint':dict(previous_cp) if previous_cp else None,'events_after_checkpoint':previous_events,'history_command':'research_cli.py history '+previous['id']}
        for event in events:event['payload']=json.loads(event['payload'])
        return dict(conversation=item,node=node,checkpoint=dict(cp) if cp else None,events_since_checkpoint=events,executions=executions,plans=plans,
                    relationships=links,predecessor_context=predecessor_context,source_available=self.source.is_dir(),node_available=bool(node['path'] and Path(node['path']).is_dir()),
                    next_step='Read the checkpoint and later events. Verify process identity, inputs and outputs before resuming. Never rerun from an interrupted status alone.',
                    native_resume_available=bool(item['native_id']),coverage='Only this application and explicitly imported sessions are indexed.')

    def plan(self,cid,spec):
        if spec.get('kind') not in ('variant','child','synthesis','method','collection'):raise ValueError('Choose variant, child, synthesis, method or collection')
        purpose=str(spec.get('purpose','')).strip();name=str(spec.get('name',''))
        if not purpose or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}',name) or name in ('.','..'):raise ValueError('Provide a purpose and a simple folder name')
        with self.transaction() as db:
            conv=self.conversation(cid,db);anchor=self.resolve(spec.get('anchor') or conv['node_id'],db)
            inputs=[self.resolve(t,db) for t in spec.get('inputs',[])]
            kind=spec['kind']
            if kind=='variant':
                if not anchor['parent_id']:raise ValueError('A project root cannot be a scientific variant')
                parent=self.resolve(anchor['parent_id'],db);rationale='Parallel parameter or method variant of '+anchor['title']
            elif kind=='synthesis':
                if len(inputs)<2:raise ValueError('A synthesis needs at least two input nodes')
                def lineage(node):
                    ids=[]
                    while node:
                        ids.append(node['id']);node=self.resolve(node['parent_id'],db) if node['parent_id'] else None
                    return ids
                chains=[lineage(n) for n in inputs];common=next((n for n in chains[0] if all(n in c for c in chains[1:])),None)
                if not common:raise ValueError('Inputs have no shared collection')
                parent=self.resolve(common,db)
                if parent['role']=='analysis' and parent['parent_id']:parent=self.resolve(parent['parent_id'],db)
                rationale='Combines inputs under their nearest shared organizational collection'
            else:
                parent=anchor;rationale={'child':'Narrower investigation within this analysis','method':'Reusable method under the selected shared collection','collection':'Organizational grouping under the selected parent'}[kind]
                if kind=='method' and anchor['role']=='analysis':raise ValueError('Reusable methods need a project or collection parent')
            storage_parent=parent
            while not storage_parent['path'] and storage_parent['parent_id']:storage_parent=self.resolve(storage_parent['parent_id'],db)
            if not storage_parent['path']:raise ValueError('No physical project folder is available for this collection')
            target=Path(storage_parent['path'])/name
            if not target.resolve().is_relative_to(self.source):raise ValueError('Destination is outside the project')
            if target.exists() or db.execute("SELECT 1 FROM placement_plans WHERE path=? AND state IN ('pending','approved','creating','created')",(str(target),)).fetchone():raise ValueError('Destination is already used or reserved')
            input_ids=list(dict.fromkeys(n['id'] for n in inputs))
            if kind=='variant' and anchor['id'] not in input_ids:input_ids.append(anchor['id'])
            specification=dict(spec,purpose=purpose,inputs=input_ids,anchor=anchor['id'],rationale=rationale,parent_revision=parent['revision'],storage_parent_id=storage_parent['id'],storage_parent_revision=storage_parent['revision'],
                               related=self.search(purpose,8),code_sources=spec.get('code_sources',[]))
            pid=uid('plan')
            db.execute('INSERT INTO placement_plans(id,conversation_id,parent_id,path,specification,state,created) VALUES(?,?,?,?,?,?,?)',(pid,cid,parent['id'],str(target),encode(specification),'pending',stamp()))
            self._event(db,'placement_proposed',cid,conv['node_id'],{'plan_id':pid,'specification':specification,'path':str(target)})
            self._job(db,cid,'placement',{'plan_id':pid},'placement:'+pid)
        return self.get_plan(pid)

    def get_plan(self,pid):
        with self.connect() as db:row=db.execute('SELECT * FROM placement_plans WHERE id=?',(pid,)).fetchone()
        if not row:raise ValueError('Unknown placement plan')
        result=dict(row);result['specification']=json.loads(result['specification']);return result

    def retire_plan(self,pid,reason):
        reason=str(reason).strip()
        if not reason:raise ValueError('Record why this proposal is being retired')
        with self.transaction() as db:
            row=db.execute('SELECT * FROM placement_plans WHERE id=?',(pid,)).fetchone()
            if not row:raise ValueError('Unknown placement plan')
            if row['state'] in ('creating','created'):raise ValueError('A created or partly created analysis cannot be retired as an unused proposal')
            db.execute("UPDATE placement_plans SET state='retired',revision=revision+1 WHERE id=?",(pid,))
            self._event(db,'placement_retired',row['conversation_id'],None,{'plan_id':pid,'reason':reason})
            self._job(db,row['conversation_id'],'summary',{},'retired:'+pid)
        return self.get_plan(pid)

    def review_plan(self,pid,reason):
        reason=str(reason).strip()
        if not reason:raise ValueError('Record the new evidence or resolution before requesting another review')
        with self.transaction() as db:
            row=db.execute('SELECT * FROM placement_plans WHERE id=?',(pid,)).fetchone()
            if not row or row['state']!='needs_attention':raise ValueError('Only a proposal needing attention can be reconsidered')
            revision=row['revision']+1
            db.execute("UPDATE placement_plans SET state='pending',revision=? WHERE id=?",(revision,pid))
            self._event(db,'placement_review_requested',row['conversation_id'],None,{'plan_id':pid,'reason':reason,'revision':revision})
            self._job(db,row['conversation_id'],'placement',{'plan_id':pid},'placement:'+pid+':'+str(revision))
            self._job(db,row['conversation_id'],'review',{},'placement-resolution:'+pid+':'+str(revision))
        return self.get_plan(pid)

    def create_analysis(self,pid):
        # Reserve in DB first. A crash leaves a recoverable 'creating' plan; never overwrite it.
        with self.transaction() as db:
            row=db.execute('SELECT * FROM placement_plans WHERE id=?',(pid,)).fetchone()
            if not row:raise ValueError('Unknown plan')
            plan=dict(row);spec=json.loads(plan['specification']);conv=self.conversation(plan['conversation_id'],db)
            if plan['state']=='created':return self.resolve(plan['node_id'],db)
            if plan['state']!='approved' or conv['review']!='ready':raise ValueError('Wait for an approved placement and initial manager review')
            parent=self.resolve(plan['parent_id'],db)
            if parent['revision']!=spec['parent_revision']:raise ValueError('Parent changed; submit a new placement review')
            storage_parent=self.resolve(spec.get('storage_parent_id') or parent['id'],db)
            if storage_parent['revision']!=spec.get('storage_parent_revision',storage_parent['revision']):raise ValueError('Physical parent changed; submit a new placement review')
            path=Path(plan['path'])
            if path.exists() or path.parent.resolve()!=Path(storage_parent['path']).resolve() or not path.resolve().is_relative_to(self.source):raise ValueError('Destination changed or already exists')
            sources=[]
            for source in spec.get('code_sources',[]):
                p=Path(source).resolve()
                if not p.is_file() or not p.is_relative_to(self.source) or p.stat().st_size>10_000_000:raise ValueError('Code source must be a bounded file inside the research project')
                if p.name in [v.name for v in sources]:raise ValueError('Code files have duplicate names')
                sources.append(p)
            nid=uid('node');db.execute("UPDATE placement_plans SET state='creating',node_id=? WHERE id=?",(nid,pid))
        try:
            path.mkdir(exist_ok=False)
            for folder in ('code','data','figures'): (path/folder).mkdir()
            fingerprints=[]
            for source in sources:
                dest=path/'code'/source.name;shutil.copyfile(source,dest)
                fingerprints.append({'source':str(source),'copy':str(dest),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
            metadata={'schema_version':1,'node_id':nid,'parent_id':parent['id'],'title':spec.get('title') or spec['name'],
                      'description':spec['purpose'],'role':'collection' if spec['kind']=='collection' else 'analysis','inputs':spec['inputs'],'parameters':spec.get('parameters',{}),'code':fingerprints,
                      'conversation_id':conv['id'],'placement_plan':pid,'created':stamp(),'verification':'not_run'}
            (path/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
            (path/'description.md').write_text('# '+metadata['title']+'\n\n'+spec['purpose']+'\n\nPlacement: '+spec['rationale']+'\n\nStatus: not run; outputs not validated.\n')
        except Exception as error:
            with self.transaction() as db:self._event(db,'analysis_creation_incomplete',conv['id'],nid,{'plan_id':pid,'path':str(path),'error':str(error)})
            raise
        with self.transaction() as db:
            db.execute('INSERT INTO research_nodes(id,title,role,path,parent_id,description) VALUES(?,?,?,?,?,?)',(nid,metadata['title'],'collection' if spec['kind']=='collection' else 'analysis',str(path),parent['id'],spec['purpose']))
            db.execute('INSERT INTO node_paths VALUES(?,?)',(str(path),nid));db.execute("UPDATE placement_plans SET state='created' WHERE id=?",(pid,))
            for target in spec['inputs']:db.execute('INSERT INTO research_links VALUES(?,?,?,?)',(nid,target,'depends_on',encode({'placement_plan':pid})))
            self._event(db,'node_created',conv['id'],nid,metadata)
            self._job(db,conv['id'],'summary',{},'created:'+pid)
        return self.resolve(nid)

    def recover_creation(self,pid):
        plan=self.get_plan(pid)
        if plan['state']=='created':return self.resolve(plan['node_id'])
        if plan['state']!='creating':raise ValueError('Plan is not an interrupted creation')
        path=Path(plan['path'])
        if not path.is_dir():raise ValueError('No complete package exists. Keep the failed record and propose a fresh reviewed destination.')
        if not path.resolve().is_relative_to(self.source):raise ValueError('Package is outside the project')
        meta=path/'metadata.json'
        if meta.is_symlink() or not meta.is_file():raise ValueError('Package metadata is incomplete; do not overwrite the folder')
        data=json.loads(meta.read_text())
        if data.get('node_id')!=plan['node_id'] or data.get('placement_plan')!=pid or data.get('conversation_id')!=plan['conversation_id']:raise ValueError('Package identity does not match the creation record')
        for name in ('code','data','figures'):
            if not (path/name).is_dir() or (path/name).is_symlink():raise ValueError('Package folders are incomplete')
        for ref in data.get('code',[]):
            copied=Path(ref['copy'])
            if copied.is_symlink() or not copied.resolve().is_relative_to(path.resolve()/'code') or hashlib.sha256(copied.read_bytes()).hexdigest()!=ref['sha256']:raise ValueError('Copied code differs from the creation record')
        with self.transaction() as db:
            db.execute('INSERT OR IGNORE INTO research_nodes(id,title,role,path,parent_id,description) VALUES(?,?,?,?,?,?)',(plan['node_id'],data['title'],'analysis',str(path),plan['parent_id'],data['description']))
            db.execute('INSERT OR REPLACE INTO node_paths VALUES(?,?)',(str(path),plan['node_id']))
            for target in data.get('inputs',[]):db.execute('INSERT OR IGNORE INTO research_links VALUES(?,?,?,?)',(plan['node_id'],target,'depends_on',encode({'placement_plan':pid})))
            db.execute("UPDATE placement_plans SET state='created' WHERE id=?",(pid,))
            self._event(db,'analysis_creation_recovered',plan['conversation_id'],plan['node_id'],{'plan_id':pid,'path':str(path)})
            self._job(db,plan['conversation_id'],'summary',{},'recovered:'+pid)
        return self.resolve(plan['node_id'])

    def collection(self,title,parent_id,children):
        with self.transaction() as db:
            parent=self.resolve(parent_id,db);items=[self.resolve(c,db) for c in children]
            if not title.strip() or len(title)>200:raise ValueError('Provide a collection title')
            if any(n['id']==parent['id'] for n in items):raise ValueError('A collection cannot contain its own parent')
            # Each child must currently be under this parent, preventing cross-tree cycles.
            if any(n['parent_id']!=parent['id'] for n in items):raise ValueError('Only siblings under the chosen parent can be grouped')
            nid=uid('node');db.execute('INSERT INTO research_nodes(id,title,role,parent_id,description) VALUES(?,?,?,?,?)',(nid,title,'collection',parent['id'],'Logical collection; physical folders unchanged'))
            for node in items:
                db.execute('UPDATE research_nodes SET parent_id=?,revision=revision+1 WHERE id=?',(nid,node['id']))
                self._event(db,'node_reparented',nid=node['id'],payload={'old_parent':node['parent_id'],'new_parent':nid,'physical_path_unchanged':node['path']})
        return self.resolve(nid)

    def ask_manager(self,cid,question):
        if not str(question).strip() or len(question)>12000:raise ValueError('Ask a question of up to 12000 characters')
        with self.transaction() as db:
            conv=self.conversation(cid,db);seq=self._event(db,'manager_question',cid,conv['node_id'],{'question':question},'agent_report')
            self._job(db,cid,'question',{'question':question},'question:'+str(seq))
            return dict(db.execute('SELECT * FROM manager_jobs WHERE dedupe=?',('question:'+str(seq),)).fetchone())

    def history(self,cid,after=0):
        self.conversation(cid)
        with self.connect() as db:
            events=[dict(r) for r in db.execute('SELECT * FROM research_events WHERE conversation_id=? AND seq>? ORDER BY seq LIMIT 100',(cid,int(after)))]
            checkpoints=[dict(r) for r in db.execute('SELECT * FROM research_checkpoints WHERE conversation_id=? ORDER BY id DESC LIMIT 30',(cid,))]
        for event in events:event['payload']=json.loads(event['payload'])
        return {'events':events,'next_cursor':events[-1]['seq'] if events else int(after),'checkpoints':checkpoints}

    def link(self,source,target,relation,evidence):
        if relation not in ('depends_on','derived_from','compared_with','supersedes'):raise ValueError('Unknown relationship')
        with self.transaction() as db:
            a=self.resolve(source,db);b=self.resolve(target,db)
            if a['id']==b['id']:raise ValueError('Self relationships are invalid')
            if relation in ('depends_on','derived_from','supersedes'):
                seen=set();stack=[b['id']]
                while stack:
                    key=stack.pop()
                    if key==a['id']:raise ValueError('Dependency cycle')
                    if key in seen:continue
                    seen.add(key);stack.extend(r[0] for r in db.execute("SELECT target_id FROM research_links WHERE source_id=? AND relation IN ('depends_on','derived_from','supersedes')",(key,)))
            db.execute('INSERT OR REPLACE INTO research_links VALUES(?,?,?,?)',(a['id'],b['id'],relation,encode(evidence)))
            self._event(db,'relationship_recorded',nid=a['id'],payload={'target':b['id'],'relation':relation,'evidence':evidence},source='agent_report')
        return {'source':a['id'],'target':b['id'],'relation':relation}

    def write_analysis_file(self,cid,nid,relative,content):
        with self.node_lock(self.resolve(nid)['id']):return self._write_analysis_file(cid,nid,relative,content)

    def _write_analysis_file(self,cid,nid,relative,content):
        node=self.resolve(nid);conv=self.conversation(cid)
        with self.connect() as db:
            plan=db.execute("SELECT * FROM placement_plans WHERE node_id=? AND state='created' AND conversation_id=?",(node['id'],cid)).fetchone()
            if db.execute("SELECT 1 FROM research_executions WHERE node_id=? AND status IN ('running','unknown')",(node['id'],)).fetchone():raise ValueError('Code is frozen while an execution is running or unresolved')
        # A created plan already passed placement review. Permit its owner to
        # repair code while an operational review is blocked; execution still
        # requires a fresh ready review and unresolved runs still freeze edits.
        if not plan:raise ValueError('File edits require this conversation’s reviewed generated analysis')
        root=Path(node['path']).resolve();target=(root/relative).resolve()
        if not root.is_relative_to(self.source):raise ValueError('Analysis package is outside the project')
        if not target.is_relative_to(root) or (not target.is_relative_to(root/'code') and target!=root/'description.md'):raise ValueError('Edit code/ or description.md only; outputs are generated by a recorded execution')
        if not isinstance(content,str) or len(content.encode())>1000000:raise ValueError('Text file exceeds the edit limit')
        if target.exists():
            backup=self.app/'.research'/'revisions';backup.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(target,backup/(uid('revision')+'-'+target.name))
        target.parent.mkdir(parents=True,exist_ok=True);tmp=target.with_name('.'+target.name+'.'+uuid.uuid4().hex+'.tmp')
        tmp.write_text(content);tmp.replace(target)
        evidence={'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
        with self.transaction() as db:
            self._event(db,'analysis_file_written',cid,node['id'],dict(evidence,review_at_edit=conv['review']))
            if conv['review']=='needs_attention':
                db.execute('UPDATE research_conversations SET revision=revision+1 WHERE id=?',(cid,))
                self._job(db,cid,'review',{},'repair:'+cid+':'+evidence['sha256'])
        return evidence

    def execute(self,cid,nid,command):
        with self.node_lock(self.resolve(nid)['id']):return self._execute(cid,nid,command)

    def _execute(self,cid,nid,command):
        if not command or not isinstance(command,list) or not all(isinstance(v,str) for v in command):raise ValueError('Execution requires an argument list, not shell text')
        node=self.resolve(nid);conv=self.conversation(cid);path=Path(node['path'] or '')
        with self.transaction() as db:
            plan=db.execute("SELECT * FROM placement_plans WHERE node_id=? AND state='created'",(node['id'],)).fetchone()
            if not plan or plan['conversation_id']!=cid:raise ValueError('Execution must belong to this conversation and its reviewed generated analysis')
            if conv['review']!='ready':raise ValueError('Conversation manager review is '+conv['review']+'; resolve its recorded concerns and request a fresh review before executing')
            if not path.is_dir() or not path.resolve().is_relative_to(self.source):raise ValueError('Analysis folder unavailable')
            if any((path/name).is_symlink() or not (path/name).resolve().is_relative_to(path.resolve()) for name in ('code','data','figures')):raise ValueError('Package folders must remain inside the analysis')
            expected=json.loads(plan['specification']).get('command')
            if expected!=command:raise ValueError('Execution command differs from the reviewed plan; record the exact argument list in a new placement plan')
            if db.execute("SELECT 1 FROM research_executions WHERE node_id=? AND status IN ('running','unknown')",(node['id'],)).fetchone():raise ValueError('An execution is active or unresolved; inspect it before rerunning')
            eid=uid('execution');now=stamp()
            db.execute('INSERT INTO research_executions(id,conversation_id,node_id,command,cwd,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',(eid,cid,node['id'],encode(command),str(path),'running',now,now))
            self._event(db,'execution_started',cid,node['id'],{'execution_id':eid,'command':command,'cwd':str(path)})
        logs=path/'data'/(eid+'.log')
        code_fingerprints={str(p.relative_to(path)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (path/'code').rglob('*') if p.is_file() and not p.is_symlink()}
        with self.transaction() as db:db.execute('UPDATE research_executions SET evidence=? WHERE id=?',(encode({'code_fingerprints':code_fingerprints,'scientific_validation':'not_performed'}),eid))
        try:
            with logs.open('xb') as output:
                process=subprocess.Popen(command,cwd=path,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
                with self.transaction() as db:db.execute('UPDATE research_executions SET pid=?,updated=? WHERE id=?',(process.pid,stamp(),eid))
                code=process.wait()
            evidence={'code_fingerprints':code_fingerprints,'log':str(logs),'log_sha256':hashlib.sha256(logs.read_bytes()).hexdigest(),'scientific_validation':'not_performed'}
            with self.transaction() as db:
                db.execute('UPDATE research_executions SET status=?,exit_code=?,evidence=?,updated=? WHERE id=?',('finished' if code==0 else 'failed',code,encode(evidence),stamp(),eid))
                seq=self._event(db,'execution_finished',cid,node['id'],{'execution_id':eid,'exit_code':code,'evidence':evidence})
                self._job(db,cid,'summary',{},'execution:'+eid)
            return {'execution_id':eid,'exit_code':code,'evidence':evidence}
        except Exception as error:
            with self.transaction() as db:
                db.execute("UPDATE research_executions SET status='unknown',updated=? WHERE id=?",(stamp(),eid))
                self._event(db,'execution_unknown',cid,node['id'],{'execution_id':eid,'error':str(error)})
            raise

    def conversation_node_aliases(self):
        """All graph aliases with bound, creator, or executor conversations."""
        with self.connect() as db:
            rows=db.execute("""WITH active AS (
                SELECT id,node_id FROM research_conversations c WHERE NOT EXISTS (
                    SELECT 1 FROM research_events e WHERE e.conversation_id=c.id AND e.kind='native_session_excluded')
                AND NOT EXISTS (SELECT 1 FROM research_events e WHERE e.conversation_id=c.id AND e.kind='conversation_deleted'
                    AND e.seq=(SELECT MAX(x.seq) FROM research_events x WHERE x.conversation_id=c.id AND x.kind IN ('conversation_deleted','conversation_restored')))),
                associated AS (
                    SELECT node_id FROM active UNION
                    SELECT p.node_id FROM placement_plans p JOIN active a ON a.id=p.conversation_id WHERE p.state='created' UNION
                    SELECT e.node_id FROM research_executions e JOIN active a ON a.id=e.conversation_id)
                SELECT DISTINCT alias FROM node_aliases JOIN associated USING(node_id) ORDER BY alias""")
            return [row[0] for row in rows]

    def overview(self):
        with self.connect() as db:
            counts={table:db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('research_nodes','research_conversations','research_events','research_executions')}
            jobs=[dict(r) for r in db.execute('SELECT * FROM manager_jobs ORDER BY created DESC LIMIT 30')]
            plans=[dict(r) for r in db.execute('SELECT * FROM placement_plans ORDER BY created DESC LIMIT 30')]
            manager=dict(db.execute('SELECT key,value FROM manager_state').fetchall())
        return dict(counts=counts,conversations=self.conversations(),conversation_node_ids=self.conversation_node_aliases(),jobs=jobs,plans=plans,manager=manager,
                    coverage='This app and explicitly imported native sessions only',source_available=self.source.is_dir())
