#!/usr/bin/env python3
"""Research manager helper: explicit placement, checkpoints and resumable work."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path
from research_registry import Registry,stamp
from manager_worker import capture_transcript

APP=Path(__file__).resolve().parent
SOURCE=str((APP/'project.json').parent.parent) if (APP/'project.json').exists() else str(APP/'demo'/'Orchard Study')

def import_sessions(reg):
    """Only adopt sessions whose exact cwd is an app-owned terminal workspace."""
    from terminal_bridge import PROJECT_TERMINAL_ID
    mapping={}
    dbfile=reg.app/'workspace.sqlite3'
    if dbfile.exists():
        with sqlite3.connect(dbfile) as db:
            try:
                for binding,work in db.execute('SELECT node_id,workspace FROM terminal_bindings'):
                    path=Path(work).resolve()
                    if path.is_relative_to(reg.app/'.codex-terminals'):mapping[str(path)]=binding
            except sqlite3.OperationalError:pass
    import os
    home=Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))
    imported=[]
    for path in sorted((home/'sessions').rglob('*.jsonl')):
        try:
            with path.open() as stream:meta=json.loads(stream.readline(200000))
            payload=meta.get('payload',{});cwd=str(Path(reg.lexical_path(payload.get('cwd',''))).resolve())
            if meta.get('type')!='session_meta' or cwd not in mapping:continue
            if payload.get('source','cli')!='cli':continue
            native=payload.get('id')
            with reg.connect() as db:
                if db.execute('SELECT 1 FROM research_conversations WHERE native_id=?',(native,)).fetchone():continue
            conv=reg.register(mapping[cwd],objective='Imported earlier conversation for '+reg.resolve(mapping[cwd])['title'],new=True)
            reg.attach(conv['id'],cwd,native,str(path));capture_transcript(reg,conv['id'])
            with reg.transaction() as db:
                db.execute("UPDATE research_conversations SET status=CASE WHEN status='active' THEN 'interrupted' ELSE status END WHERE id=?",(conv['id'],))
                reg._event(db,'conversation_imported',conv['id'],conv['node_id'],{'native_id':native,'transcript':str(path)})
            imported.append(conv['id'])
        except (ValueError,OSError,KeyError):continue
    return {'imported':imported,'count':len(imported),'coverage':'Exact app-owned workspaces only. Existing native sessions and research files were not changed.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--app',default=str(APP));p.add_argument('--source',default=SOURCE)
    sub=p.add_subparsers(dest='action',required=True)
    q=sub.add_parser('search');q.add_argument('query',nargs='?',default='')
    sub.add_parser('status');sub.add_parser('import-sessions')
    q=sub.add_parser('new');q.add_argument('--node',required=True);q.add_argument('--objective',required=True);q.add_argument('--predecessor')
    q=sub.add_parser('ask');q.add_argument('conversation');q.add_argument('question')
    q=sub.add_parser('history');q.add_argument('conversation');q.add_argument('--after',type=int,default=0)
    q=sub.add_parser('link');q.add_argument('source_node');q.add_argument('target_node');q.add_argument('--relation',required=True);q.add_argument('--evidence',required=True)
    q=sub.add_parser('conversations');q.add_argument('--node')
    q=sub.add_parser('recover');q.add_argument('conversation')
    q=sub.add_parser('checkpoint');q.add_argument('conversation');q.add_argument('--summary',required=True);q.add_argument('--details',default='{}');q.add_argument('--status')
    q=sub.add_parser('plan');q.add_argument('conversation');q.add_argument('--spec',help='JSON file with purpose, name, kind, anchor, inputs, code_sources, parameters and optional command');q.add_argument('--spec-json',help='Inline JSON, avoiding a temporary specification file')
    q=sub.add_parser('plan-status');q.add_argument('plan')
    q=sub.add_parser('retire-plan');q.add_argument('plan');q.add_argument('--reason',required=True)
    q=sub.add_parser('review-plan');q.add_argument('plan');q.add_argument('--reason',required=True)
    q=sub.add_parser('create');q.add_argument('plan')
    q=sub.add_parser('recover-create');q.add_argument('plan')
    q=sub.add_parser('write');q.add_argument('conversation');q.add_argument('node');q.add_argument('--path',required=True);q.add_argument('--content-json',required=True,help='A JSON-encoded string containing the file contents')
    q=sub.add_parser('run');q.add_argument('conversation');q.add_argument('node');q.add_argument('command',nargs=argparse.REMAINDER)
    q=sub.add_parser('collection');q.add_argument('--title',required=True);q.add_argument('--parent',required=True);q.add_argument('--children',nargs='+',required=True)
    a=p.parse_args();reg=Registry(a.app,a.source,read_only=a.action in ('search','status','conversations','recover','history','plan-status'))
    if a.action=='search':result=reg.search(a.query)
    elif a.action=='status':result=reg.overview()
    elif a.action=='conversations':result=reg.conversations(a.node)
    elif a.action=='recover':
        result=reg.recovery(a.conversation)
    elif a.action=='new':result=reg.register(a.node,a.objective,new=True,predecessor=a.predecessor)
    elif a.action=='ask':result=reg.ask_manager(a.conversation,a.question)
    elif a.action=='history':result=reg.history(a.conversation,a.after)
    elif a.action=='link':result=reg.link(a.source_node,a.target_node,a.relation,a.evidence)
    elif a.action=='checkpoint':result=reg.checkpoint(a.conversation,a.summary,json.loads(a.details),a.status)
    elif a.action=='plan':result=reg.plan(a.conversation,json.loads(a.spec_json if a.spec_json else Path(a.spec).read_text()))
    elif a.action=='plan-status':result=reg.get_plan(a.plan)
    elif a.action=='retire-plan':result=reg.retire_plan(a.plan,a.reason)
    elif a.action=='review-plan':result=reg.review_plan(a.plan,a.reason)
    elif a.action=='recover-create':result=reg.recover_creation(a.plan)
    elif a.action=='create':result=reg.create_analysis(a.plan)
    elif a.action=='write':result=reg.write_analysis_file(a.conversation,a.node,a.path,json.loads(a.content_json))
    elif a.action=='run':result=reg.execute(a.conversation,a.node,a.command[1:] if a.command[:1]==['--'] else a.command)
    elif a.action=='collection':result=reg.collection(a.title,a.parent,a.children)
    elif a.action=='import-sessions':result=import_sessions(reg)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,sqlite3.Error) as error:print(json.dumps({'error':str(error)}),file=sys.stderr);sys.exit(1)
