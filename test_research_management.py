import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from research_registry import Registry,stamp
from research_hook import handle,read_only_call
from manager_worker import ManagerWorker,capture_transcript

READY={'decision':'ready','summary':'Reviewed the supplied records; no conflict found. Scientific outputs remain unverified.','related_ids':[],'next_steps':['Inspect outputs before interpreting them.'],'uncertainties':[]}

class ResearchManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Path(self.temp.name);self.source=self.app/'Sample project';self.source.mkdir()
        self.reg=Registry(self.app,self.source)
        definitions=[('root','Sample project','',None,False),('back','growth_analysis','collection/dynamic analysis/growth_analysis','root',True),
                     ('model','growth_model','collection/dynamic analysis/growth_analysis/growth_model','back',False),
                     ('a','alpha_0.1','collection/dynamic analysis/growth_analysis/growth_model/alpha_0.1','model',True),
                     ('b','alpha_0.7','collection/dynamic analysis/growth_analysis/growth_model/alpha_0.7','model',True)]
        self.model={'root_id':'root','nodes':[]}
        for key,title,relative,parent,inspectable in definitions:
            path=self.source/relative;path.mkdir(parents=True,exist_ok=True)
            self.model['nodes'].append({'id':key,'title':title,'storage':{'folders':[str(path)]},'parent_id':parent,'inspectable':inspectable,'description':'Back-stress test fixture'})
        self.mapping=self.reg.sync_nodes(self.model);self.conv=self.reg.register('a','Compare recorded growth-rate variants')
        self.worker=ManagerWorker(self.reg,'unused',runner=lambda bundle:(dict(READY),'test-native-manager'))
    def tearDown(self):self.temp.cleanup()
    def drain(self):
        for _ in range(20):
            if not self.worker.process_one():break
    def plan(self,**kwargs):
        self.drain();spec=dict(kind='variant',anchor='a',inputs=['a'],name='alpha_0.2_new',purpose='A distinct parameter variant',command=[sys.executable,'code/run.py']);spec.update(kwargs)
        return self.reg.plan(self.conv['id'],spec)
    def test_conversation_graph_nodes_exclude_unrelated_and_excluded_sessions(self):
        self.assertIn('a',self.reg.overview()['conversation_node_ids'])
        self.assertNotIn('b',self.reg.overview()['conversation_node_ids'])
        with self.reg.transaction() as db:
            self.reg._event(db,'native_session_excluded',self.conv['id'])
        self.assertNotIn('a',self.reg.overview()['conversation_node_ids'])

    def test_delete_conversation_filters_lists_search_selection_and_graph_and_can_undo(self):
        cid=self.conv['id'];history=self.reg.recovery(cid)
        self.reg.delete_conversation(cid)
        self.assertNotIn(cid,[c['id'] for c in self.reg.conversations()])
        self.assertEqual(self.reg.node_conversations('a')['conversations'],[])
        self.assertNotIn(cid,[c['id'] for c in self.reg.search('')['conversations']])
        self.assertNotIn('a',self.reg.overview()['conversation_node_ids'])
        self.assertIsNone(self.reg.preferred_conversation('a'))
        with self.assertRaises(ValueError):self.reg.register('a',cid=cid)
        self.assertEqual(self.reg.recovery(cid)['conversation']['native_id'],history['conversation']['native_id'])
        self.reg.delete_conversation(cid,restore=True)
        self.assertIn(cid,[c['id'] for c in self.reg.conversations()])
        self.assertIn('a',self.reg.overview()['conversation_node_ids'])
        self.assertEqual(self.reg.preferred_conversation('a')['id'],cid)

    def test_stable_ids_aliases_and_idempotent_registration(self):
        self.assertEqual(self.mapping,self.reg.sync_nodes(self.model));self.assertEqual(self.reg.resolve('a')['id'],self.mapping['a'])
        self.assertEqual(self.reg.register('a')['id'],self.conv['id'])
        self.assertNotEqual(self.reg.register('a',new=True)['id'],self.conv['id'])
        with self.assertRaises(ValueError):self.reg.register('b',cid=self.conv['id'])
    def test_variant_and_synthesis_level(self):
        plan=self.plan();self.assertEqual(plan['parent_id'],self.mapping['model'])
        self.assertEqual(Path(plan['path']).parent,Path(self.reg.resolve('a')['path']).parent)
        combined=self.plan(kind='synthesis',name='comparison',inputs=['a','b'])
        self.assertEqual(combined['parent_id'],self.mapping['model'])
        with self.assertRaises(ValueError):self.plan(kind='synthesis',name='bad',inputs=['a'])
        with self.assertRaises(ValueError):self.plan(kind='method',name='method')
    def test_child_and_name_collisions_and_traversal(self):
        plan=self.plan(kind='child',name='narrow_question');self.assertEqual(plan['parent_id'],self.mapping['a'])
        with self.assertRaises(ValueError):self.plan(kind='child',name='narrow_question')
        with self.assertRaises(ValueError):self.plan(name='../escape')
        with self.assertRaises(ValueError):self.plan(name='alpha_0.7')
    def test_review_gate_creation_code_copy_and_execution(self):
        code=Path(self.reg.resolve('a')['path'])/'safe_fixture.py'
        code.write_text('from pathlib import Path\nimport json\nPath("data/result.json").write_text(json.dumps({"fixture":True}))\n')
        plan=self.plan(code_sources=[str(code)])
        with self.assertRaises(ValueError):self.reg.create_analysis(plan['id'])
        self.drain();node=self.reg.create_analysis(plan['id']);path=Path(node['path'])
        self.assertEqual({p.name for p in path.iterdir()},{'code','data','figures','metadata.json','description.md'})
        self.assertEqual((path/'code/safe_fixture.py').read_bytes(),code.read_bytes())
        self.assertEqual(self.reg.create_analysis(plan['id'])['id'],node['id'])
        self.reg.write_analysis_file(self.conv['id'],node['id'],'code/run.py',code.read_text())
        with self.assertRaises(ValueError):self.reg.write_analysis_file(self.conv['id'],node['id'],'../escape.py','x')
        with self.assertRaises(ValueError):self.reg.execute(self.conv['id'],node['id'],['echo','unreviewed'])
        execution=self.reg.execute(self.conv['id'],node['id'],[sys.executable,'code/run.py'])
        self.assertEqual(execution['exit_code'],0);self.assertTrue((path/'data/result.json').exists())
        self.assertEqual(execution['evidence']['scientific_validation'],'not_performed')
        self.assertIn('code/run.py',execution['evidence']['code_fingerprints'])
    def test_parent_revision_invalidates_plan(self):
        plan=self.plan();self.drain()
        with self.reg.transaction() as db:db.execute('UPDATE research_nodes SET revision=revision+1 WHERE id=?',(plan['parent_id'],))
        with self.assertRaises(ValueError):self.reg.create_analysis(plan['id'])
    def test_symlink_destination_cannot_escape_source(self):
        plan=self.plan();self.drain();target=Path(plan['path']);target.symlink_to(self.app,target_is_directory=True)
        with self.assertRaises(ValueError):self.reg.create_analysis(plan['id'])
    def test_reservation_conflict_and_existing_work_search(self):
        self.plan();found=self.reg.search('growth_rate');self.assertTrue(found['nodes'])
        with self.assertRaises(ValueError):self.plan()
    def test_parent_collection_preserves_conversation_and_paths(self):
        before=self.reg.resolve('a');group=self.reg.collection('Parameter variants','model',['a','b'])
        self.assertEqual(self.reg.resolve('a')['parent_id'],group['id'])
        self.assertEqual(self.reg.resolve('a')['path'],before['path'])
        self.assertEqual(self.reg.conversation(self.conv['id'])['node_id'],before['id'])
        self.reg.sync_nodes(self.model);self.assertEqual(self.reg.resolve('a')['parent_id'],group['id'])
        proposed=self.plan(name='logical_group_variant');self.assertEqual(proposed['parent_id'],group['id']);self.assertEqual(Path(proposed['path']).parent,Path(self.reg.resolve('model')['path']))
        with self.assertRaises(ValueError):self.reg.collection('cycle','a',['root'])
    def test_metadata_identity_survives_move_and_copy_does_not_merge(self):
        original=Path(self.reg.resolve('a')['path']);nid=self.mapping['a']
        (original/'metadata.json').write_text(json.dumps({'schema_version':1,'node_id':nid}))
        moved=original.with_name('renamed');original.rename(moved)
        model=json.loads(json.dumps(self.model));model['nodes'][3].update(id='new-path-id',storage={'folders':[str(moved)]})
        self.reg.sync_nodes(model);self.assertEqual(self.reg.resolve('new-path-id')['id'],nid)
        self.assertEqual(self.reg.resolve(str(original))['id'],nid)
        copy=moved.with_name('copied');copy.mkdir();(copy/'metadata.json').write_text((moved/'metadata.json').read_text())
        model['nodes'].append(dict(model['nodes'][3],id='copy',storage={'folders':[str(copy)]}))
        self.reg.sync_nodes(model);self.assertNotEqual(self.reg.resolve('copy')['id'],nid)
    def test_manager_failure_registration_and_durable_retry(self):
        failing=ManagerWorker(self.reg,'none',runner=lambda bundle:(_ for _ in ()).throw(ValueError('offline')))
        failing.process_one();self.assertEqual(self.reg.conversation(self.conv['id'])['review'],'pending')
        state=self.reg.overview();self.assertEqual(state['jobs'][0]['state'],'retry');self.assertIn('offline',state['jobs'][0]['error'])
        reg=Registry(self.app,self.source)
        with reg.transaction() as db:db.execute('UPDATE manager_jobs SET next_at=0')
        self.drain();self.assertEqual(reg.conversation(self.conv['id'])['review'],'ready')
    def test_expired_job_lease_reclaimed(self):
        with self.reg.transaction() as db:db.execute("UPDATE manager_jobs SET state='running',lease_until=0")
        self.drain();self.assertEqual(self.reg.overview()['jobs'][0]['state'],'done')
    def test_stale_manager_review_cannot_overwrite_new_objective(self):
        def runner(bundle):
            with self.reg.transaction() as db:db.execute("UPDATE research_conversations SET objective='Changed',revision=revision+1 WHERE id=?",(self.conv['id'],))
            return dict(READY),None
        ManagerWorker(self.reg,'none',runner).process_one()
        self.assertEqual(self.reg.conversation(self.conv['id'])['review'],'pending')
        self.assertIn('stale',[j['state'] for j in self.reg.overview()['jobs']])
        self.drain();self.assertEqual(self.reg.conversation(self.conv['id'])['review'],'ready')
    def test_checkpoint_recovery_restart_and_unavailable_source(self):
        self.reg.checkpoint(self.conv['id'],'Code prepared; execution not started',{'pending':['run']},'interrupted')
        recovered=Registry(self.app,self.source).recovery(self.conv['id'])
        self.assertEqual(recovered['checkpoint']['summary'],'Code prepared; execution not started')
        self.assertEqual(recovered['executions'],[])
        self.source.rename(self.app/'disconnected')
        self.assertFalse(self.reg.recovery(self.conv['id'])['source_available'])
        self.assertEqual(self.reg.conversation(self.conv['id'])['node_id'],self.mapping['a'])
    def test_unresolved_execution_prevents_rerun(self):
        plan=self.plan();self.drain();node=self.reg.create_analysis(plan['id'])
        with self.reg.transaction() as db:db.execute('INSERT INTO research_executions(id,conversation_id,node_id,command,cwd,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',('unknown',self.conv['id'],node['id'],'[]',node['path'],'unknown',stamp(),stamp()))
        with self.assertRaises(ValueError):self.reg.execute(self.conv['id'],node['id'],[sys.executable,'code/run.py'])
    def test_hooks_observe_prompts_finish_and_deny_mutations(self):
        work=self.app/'.codex-terminals'/'fixture';work.mkdir(parents=True);self.reg.attach(self.conv['id'],work)
        common={'session_id':'native-fixture-001','cwd':str(work)}
        handle(self.reg,self.conv['id'],dict(common,hook_event_name='SessionStart'))
        handle(self.reg,self.conv['id'],dict(common,hook_event_name='UserPromptSubmit',prompt='Compare variants',turn_id='t1'))
        result=handle(self.reg,self.conv['id'],dict(common,hook_event_name='PreToolUse',tool_name='Bash',tool_input={'command':'mkdir forbidden'}))
        self.assertEqual(result['hookSpecificOutput']['permissionDecision'],'deny')
        handle(self.reg,self.conv['id'],dict(common,hook_event_name='Stop',last_assistant_message='Read-only comparison finished'))
        recovery=self.reg.recovery(self.conv['id']);self.assertEqual(recovery['conversation']['native_id'],'native-fixture-001')
        self.assertEqual(recovery['checkpoint']['summary'],'Read-only comparison finished')
        self.assertTrue((work/'active-conversation.json').exists())
    def test_readonly_shell_guard_cannot_be_bypassed_by_compound_commands(self):
        def call(command):return read_only_call({'tool_name':'Bash','tool_input':{'command':command}},self.app)
        self.assertTrue(call('rg --files'))
        self.assertTrue(call("python3 "+str(self.app.resolve()/'research_cli.py')+" write c n --path code/run.py --content-json '\"if x > 1: print(x); print(2)\\n\"'"))
        for command in ('cat x > output','ls; rm x','rg --pre=malicious x','find . -delete','echo $(touch x)','python3 -c "print(1)"'):
            self.assertFalse(call(command),command)
    def test_generated_node_finds_its_parent_conversation_without_rebinding(self):
        plan=self.plan();self.drain();node=self.reg.create_analysis(plan['id'])
        result=self.reg.node_conversations(node['id'])
        self.assertEqual([c['id'] for c in result['conversations']],[self.conv['id']])
        self.assertEqual(result['conversations'][0]['node_relationship'],'Created this analysis')
        self.assertNotEqual(result['conversations'][0]['node_id'],node['id'])
        self.assertEqual(self.reg.conversation(self.conv['id'])['node_id'],self.reg.resolve('a')['id'])
        direct=self.reg.register(node['id'],'Direct child discussion',new=True)
        self.assertEqual({c['id'] for c in self.reg.node_conversations(node['id'])['conversations']},{direct['id'],self.conv['id']})
        with self.reg.transaction() as db:self.reg._event(db,'native_session_excluded',direct['id'],payload={'reason':'fixture internal reviewer'})
        self.assertEqual([c['id'] for c in self.reg.node_conversations(node['id'])['conversations']],[self.conv['id']])
        self.assertNotIn(direct['id'],{c['id'] for c in self.reg.conversations()})

    def test_readonly_registry_inspection_never_initializes_or_mutates_database(self):
        readonly=Registry(self.app,self.source,read_only=True)
        self.assertEqual(readonly.recovery(self.conv['id'])['conversation']['id'],self.conv['id'])
        self.assertEqual(readonly.overview()['counts']['research_conversations'],1)
        with self.assertRaises(sqlite3.OperationalError):readonly.checkpoint(self.conv['id'],'Must not write')

    def test_blocked_operational_review_allows_owned_code_repair_but_not_execution(self):
        plan=self.plan();self.drain();node=self.reg.create_analysis(plan['id'])
        with self.reg.transaction() as db:db.execute("UPDATE research_conversations SET review='needs_attention' WHERE id=?",(self.conv['id'],))
        self.reg.write_analysis_file(self.conv['id'],node['id'],'code/run.py','print("repaired dependency")')
        with self.assertRaisesRegex(ValueError,'manager review'):self.reg.execute(self.conv['id'],node['id'],['python3','code/run.py'])
        self.drain();self.assertEqual(self.reg.conversation(self.conv['id'])['review'],'ready')

    def test_retire_unused_proposal_and_reconsider_after_resolution(self):
        plan=self.plan();self.drain()
        retired=self.reg.retire_plan(plan['id'],'Wrong parent; replacement uses source ownership')
        self.assertEqual(retired['state'],'retired')
        with self.assertRaises(ValueError):self.reg.create_analysis(plan['id'])
        replacement=self.plan()
        with self.reg.transaction() as db:db.execute("UPDATE placement_plans SET state='needs_attention' WHERE id=?",(replacement['id'],))
        with self.assertRaises(ValueError):self.reg.review_plan(replacement['id'],'')
        reviewed=self.reg.review_plan(replacement['id'],'Earlier unused proposal retired; provenance supplied')
        self.assertEqual(reviewed['state'],'pending')
        self.assertEqual(reviewed['revision'],2)
        self.drain();self.assertEqual(self.reg.get_plan(reviewed['id'])['state'],'approved')
        self.reg.create_analysis(reviewed['id'])
        with self.assertRaises(ValueError):self.reg.retire_plan(reviewed['id'],'Cannot retire a created package')

    def test_clear_creates_continuation_preserving_original_native_id(self):
        work=self.app/'.codex-terminals'/'fixture';work.mkdir(parents=True);self.reg.attach(self.conv['id'],work,'native-original')
        handle(self.reg,self.conv['id'],{'hook_event_name':'SessionStart','source':'clear','session_id':'native-next','cwd':str(work)})
        self.assertEqual(self.reg.conversation(self.conv['id'])['native_id'],'native-original')
        items=self.reg.conversations('a');self.assertEqual(len(items),2)
        new=next(c for c in items if c['native_id']=='native-next');self.assertEqual(new['predecessor'],self.conv['id'])
    def test_transcript_capture_is_scoped_incremental_and_partial_line_safe(self):
        home=self.app/'codex-home';home.mkdir();work=self.app/'.codex-terminals'/'fixture';work.mkdir(parents=True)
        transcript=home/'session.jsonl';meta={'type':'session_meta','payload':{'id':'native-001','cwd':str(work)}}
        message={'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'A recorded result'}]}}
        transcript.write_text(json.dumps(meta)+'\n'+json.dumps(message))
        self.reg.attach(self.conv['id'],work,'native-001',str(transcript))
        with patch.dict(os.environ,{'CODEX_HOME':str(home)}):
            self.assertEqual(capture_transcript(self.reg,self.conv['id']),0)
            with transcript.open('a') as f:f.write('\n')
            self.assertEqual(capture_transcript(self.reg,self.conv['id']),1)
            self.assertEqual(capture_transcript(self.reg,self.conv['id']),0)
        self.assertEqual(self.reg.conversation(self.conv['id'])['transcript_offset'],transcript.stat().st_size)
    def test_linked_continuation_contains_predecessor_checkpoint(self):
        self.reg.checkpoint(self.conv['id'],'Preserved decisions and unfinished validation',{'pending':['validate figures']},'interrupted')
        continuation=self.reg.register('a','Continue the previous work',new=True,predecessor=self.conv['id'])
        recovered=self.reg.recovery(continuation['id'])
        self.assertEqual(recovered['predecessor_context']['conversation']['id'],self.conv['id'])
        self.assertEqual(recovered['predecessor_context']['checkpoint']['summary'],'Preserved decisions and unfinished validation')
        self.assertEqual(self.reg.conversation(self.conv['id'])['status'],'interrupted')

    def test_explicit_conversation_choice_survives_manager_updates(self):
        newer=self.reg.register('a','Newer conversation',new=True)
        self.reg.register('a',cid=self.conv['id'])
        self.reg.checkpoint(newer['id'],'Later manager activity does not select this conversation')
        self.assertEqual(self.reg.register('a')['id'],self.conv['id'])
        self.assertEqual(self.reg.preferred_conversation('a')['id'],self.conv['id'])

    def test_code_edits_are_frozen_for_unresolved_execution(self):
        plan=self.plan();self.drain();node=self.reg.create_analysis(plan['id'])
        with self.reg.node_lock(node['id']):
            with self.assertRaises(ValueError):self.reg.write_analysis_file(self.conv['id'],node['id'],'code/run.py','print(1)')
        with self.reg.transaction() as db:db.execute('INSERT INTO research_executions(id,conversation_id,node_id,command,cwd,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',('pending-outcome',self.conv['id'],node['id'],'[]',node['path'],'unknown',stamp(),stamp()))
        with self.assertRaises(ValueError):self.reg.write_analysis_file(self.conv['id'],node['id'],'code/run.py','print(1)')

    def test_summary_cursor_does_not_claim_events_arriving_during_review(self):
        self.drain();self.reg.checkpoint(self.conv['id'],'Before summary')
        def runner(bundle):
            self.reg.checkpoint(self.conv['id'],'Arrived during summary')
            return dict(READY),None
        ManagerWorker(self.reg,'unused',runner).process_one()
        with self.reg.connect() as db:
            summary=db.execute("SELECT through_seq FROM research_checkpoints WHERE source='manager_interpretation' ORDER BY id DESC LIMIT 1").fetchone()[0]
            later=db.execute("SELECT MAX(seq) FROM research_events WHERE kind='checkpoint_saved'").fetchone()[0]
        self.assertLess(summary,later)
        self.assertTrue(any(j['state']=='pending' for j in self.reg.overview()['jobs']))

    def test_registry_rejects_a_different_research_root(self):
        other=self.app/'unrelated';other.mkdir()
        with self.assertRaises(ValueError):Registry(self.app,other)

    def test_relationship_cycles_and_manager_questions(self):
        self.reg.link('a','b','depends_on','Fixture dependency')
        with self.assertRaises(ValueError):self.reg.link('b','a','derived_from','Invalid cycle')
        job=self.reg.ask_manager(self.conv['id'],'Has a growth-rate comparison already been done?')
        self.assertEqual(job['kind'],'question');self.drain()
        self.assertIn('manager_reviewed',[e['kind'] for e in self.reg.history(self.conv['id'])['events']])

    def test_interrupted_complete_creation_can_be_finalized_without_overwrite(self):
        plan=self.plan();self.drain();node=self.reg.create_analysis(plan['id'])
        with self.reg.transaction() as db:
            db.execute("UPDATE placement_plans SET state='creating' WHERE id=?",(plan['id'],))
            db.execute('DELETE FROM node_paths WHERE node_id=?',(node['id'],));db.execute('DELETE FROM research_nodes WHERE id=?',(node['id'],))
        recovered=self.reg.recover_creation(plan['id']);self.assertEqual(recovered['id'],node['id'])
        self.assertEqual(self.reg.get_plan(plan['id'])['state'],'created')

    def test_manager_jobs_are_serialized_across_workers(self):
        self.reg.register('b','Another independent review',new=True)
        entered=threading.Event();release=threading.Event()
        def runner(bundle):entered.set();release.wait(3);return dict(READY),None
        first=ManagerWorker(self.reg,'unused',runner);thread=threading.Thread(target=first.process_one);thread.start()
        self.assertTrue(entered.wait(2));self.assertFalse(self.worker.process_one());release.set();thread.join(3)
        self.assertFalse(thread.is_alive());self.drain()

    def test_native_discovery_is_limited_to_registered_workspaces(self):
        from manager_worker import discover_sessions
        home=self.app/'native-home';home.mkdir();work=self.app/'.codex-terminals'/'fixture';work.mkdir(parents=True)
        self.reg.attach(self.conv['id'],work)
        transcript=home/'session.jsonl'
        transcript.write_text(json.dumps({'type':'session_meta','payload':{'id':'native-discovered','cwd':str(work)}})+'\n'+json.dumps({'type':'event_msg','payload':{'type':'task_complete','last_agent_message':'Read-only task completed'}})+'\n')
        with sqlite3.connect(home/'state_5.sqlite') as db:
            db.execute('CREATE TABLE threads(id TEXT,cwd TEXT,rollout_path TEXT,created_at REAL,source TEXT)')
            db.execute('INSERT INTO threads VALUES(?,?,?,?,?)',('native-discovered',str(work.resolve()),str(transcript),stamp(),'cli'))
            db.execute('INSERT INTO threads VALUES(?,?,?,?,?)',('internal-review',str(work.resolve()),str(transcript),stamp()+1,'{"subagent":{"other":"guardian"}}'))
            db.execute('INSERT INTO threads VALUES(?,?,?,?,?)',('unrelated-native',str(self.app/'unrelated'),str(transcript),stamp(),'cli'))
        with patch.dict(os.environ,{'CODEX_HOME':str(home)}):
            self.assertEqual(discover_sessions(self.reg),1);self.assertEqual(capture_transcript(self.reg,self.conv['id']),1)
        recovery=self.reg.recovery(self.conv['id']);self.assertEqual(recovery['conversation']['native_id'],'native-discovered')
        self.assertEqual(recovery['checkpoint']['summary'],'Read-only task completed')
        self.assertEqual(len(self.reg.conversations()),1)

    def test_multiple_registration_threads_do_not_duplicate_default_conversation(self):
        ids=[]
        threads=[threading.Thread(target=lambda:ids.append(self.reg.register('b')['id'])) for _ in range(5)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(len(set(ids)),1)

if __name__=='__main__':unittest.main()
