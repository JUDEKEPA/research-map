import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

import server


class WorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.old = server.APP, server.DB, server.SOURCE, server.CATALOG, server.INVENTORY, server.ENTRIES, server.CHILDREN, server.ALLOWED
        server.APP = cls.root
        server.DB = cls.root/'state.sqlite3'
        server.SOURCE = cls.root/'source'
        server.SOURCE.mkdir()
        (server.SOURCE/'script.py').write_text('print("fixture only")\n')
        (cls.root/'private.txt').write_text('outside project')
        (server.SOURCE/'escape.txt').symlink_to(cls.root/'private.txt')
        base = dict(kind='analysis',description='Example result',files=[dict(path='script.py',name='script.py',exists=True,directory=False)],
                    parameters={'k':'0.1'},caveats=['Historical settings unverified'],evidence=[],origin='Imported reference',verified_run=False,x=0,y=0)
        catalog = dict(nodes=[dict(base,id='a',title='Analysis A'),dict(base,id='b',title='Analysis B')],edges=[],source=str(server.SOURCE))
        (cls.root/'catalog.json').write_text(json.dumps(catalog))
        server.initialize()
        cls.http = ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.url = 'http://127.0.0.1:'+str(cls.http.server_port)
        cls.thread = threading.Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        server.APP,server.DB,server.SOURCE,server.CATALOG,server.INVENTORY,server.ENTRIES,server.CHILDREN,server.ALLOWED = cls.old
        cls.temp.cleanup()

    def request(self,path,body=None,token=True,origin=None):
        headers={}
        if token: headers['X-Workspace-Token']=server.TOKEN
        if origin: headers['Origin']=origin
        req=Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with urlopen(req) as r:
                return r.status,r.read()
        except HTTPError as e:
            return e.code,e.read()

    def test_portable_state_saved_and_json_bootstrap_is_not_html(self):
        with patch.object(server,'PORTABLE_PROJECT',{'project_id':'fixture-project'}),patch.object(server,'LAUNCHER_URL','http://127.0.0.1:8767'):
            saved={'analysis-focus':'fixture','research-conversation-window':'{"x":10}','label':'</script><script>unexpected</script>'}
            status,body=self.request('/api/ui-state',{'settings':saved})
            self.assertEqual(status,200)
            self.assertEqual(json.loads((server.APP/'ui-state.json').read_text()),saved)
            status,body=self.request('/')
            self.assertEqual(status,200);html=body.decode()
            import re
            config=json.loads(re.search(r'<script id="portable-settings" type="application/json">(.*?)</script>',html).group(1))
            self.assertEqual(config['settings'],saved);self.assertNotIn('<script>unexpected</script>',html)

    def test_project_summary_and_paginated_resources(self):
        record=dict(id='project-fixture',title='Project fixture',description='Context',kind='project',storage={'folders':[]},code=[],data=[],figures=[],documents=[],other=[],relationships=[],provenance={},member_ids=['method-fixture'])
        method=dict(record,id='method-fixture',member_ids=[],code=[dict(path=str(server.SOURCE/'script.py'),name='script.py')])
        model=dict(project=True,nodes=[record,method],edges=[],root_id=record['id'])
        with patch.object(server,'ANALYSES',model),patch.object(server,'ANALYSIS_INDEX',{n['id']:n for n in model['nodes']}),patch.object(server,'MODEL_SUMMARY',None):
            status,body=self.request('/api/analyses')
            self.assertEqual(status,200)
            self.assertEqual(json.loads(body)['nodes'][1]['code'],[])
            status,body=self.request('/api/record-resources?id=project-fixture&category=code&limit=1')
            result=json.loads(body)
            self.assertEqual(status,200)
            self.assertEqual(result['total'],1)
            self.assertEqual(result['items'][0]['path'],str(server.SOURCE/'script.py'))
            status,body=self.request('/api/record-resources?id=project-fixture&category=code&offset=1')
            self.assertEqual(json.loads(body)['items'],[])
            record['inspectable']=False
            status,body=self.request('/api/record-resources?id=project-fixture&category=code')
            self.assertEqual(json.loads(body)['total'],0)

    def test_shared_graph_visibility_routes(self):
        model=dict(root_id='r',nodes=[dict(id='r',title='Root'),dict(id='child',title='Child',parent_id='r')],edges=[])
        with patch.object(server,'analysis_model',return_value=model):
            self.assertEqual(self.request('/api/graph-visibility',{'hide':['child']},token=False)[0],403)
            self.assertEqual(self.request('/api/graph-visibility',{'hide':['child']},origin='http://another-site.example')[0],403)
            self.assertEqual(self.request('/api/graph-visibility',{'hide':['missing']})[0],400)
            self.assertEqual(self.request('/api/graph-visibility',{'hide':['r']})[0],400)
            status,body=self.request('/api/graph-visibility',{'hide':['child']})
            self.assertEqual(status,200)
            self.assertEqual(json.loads(body)['hidden'],['child'])
            from graph_visibility import update_state
            update_state(server.APP/'graph-visibility.json',{'reveal':['child']},model['nodes'],'r')
            status,body=self.request('/api/graph-visibility')
            self.assertEqual(json.loads(body)['revealed'],['child'])

    def test_research_routes_auth_registration_plan_and_recovery(self):
        reg=server.research_registry()
        model={'root_id':'research-root','nodes':[
            dict(id='research-root',title='Project',storage={'folders':[str(server.SOURCE)]}),
            dict(id='research-a',title='Analysis A',parent_id='research-root',inspectable=True,storage={'folders':[str(server.SOURCE/'a')]}),
            dict(id='research-b',title='Analysis B',parent_id='research-root',inspectable=True,storage={'folders':[str(server.SOURCE/'b')]})]}
        reg.sync_nodes(model)
        payload=dict(action='register',node_id='research-a',objective='Compare variants through API')
        self.assertEqual(self.request('/api/research',payload,token=False)[0],403)
        self.assertEqual(self.request('/api/research',payload,origin='http://another-site.example')[0],403)
        status,body=self.request('/api/research',payload);self.assertEqual(status,201)
        conv=json.loads(body)
        self.assertEqual(self.request('/api/research/recovery?id='+conv['id'])[0],200)
        status,body=self.request('/api/research',dict(action='plan',conversation_id=conv['id'],specification=dict(kind='variant',anchor='research-a',name='new_variant',purpose='New parameter variant')))
        self.assertEqual(status,201);plan=json.loads(body)
        self.assertEqual(self.request('/api/research',dict(action='create',plan_id=plan['id']))[0],400)
        self.assertEqual(self.request('/api/research',dict(action='checkpoint',conversation_id=conv['id'],summary='Inspection complete',details={'pending':['placement review']}))[0],200)
        self.assertEqual(self.request('/api/research',dict(action='override',conversation_id=conv['id'],plan_id=plan['id'],reason=''))[0],400)
        self.assertEqual(self.request('/api/research/search?q=Compare')[0],200)

    def test_project_terminal_start_without_analysis_selection(self):
        with patch.object(server,'terminal_manager') as manager:
            manager.return_value.start.return_value={'node_id':server.PROJECT_TERMINAL_ID,'running':True}
            status,body=self.request('/api/terminal/start',dict(node_id=server.PROJECT_TERMINAL_ID))
            self.assertEqual(status,200)
            node,context,*_=manager.return_value.start.call_args.args
            self.assertEqual(node['id'],server.PROJECT_TERMINAL_ID)
            self.assertEqual(context['scope'],'project')
            self.assertEqual(context['research_root'],str(server.SOURCE))
            self.assertEqual(self.request('/api/terminal/start',dict(node_id=server.PROJECT_TERMINAL_ID),token=False)[0],403)

    def test_terminal_routes_require_origin_token_and_binding(self):
        with patch.object(server,'terminal_manager') as manager:
            body=dict(node_id='a',terminal_id='foreign',cursor=0)
            self.assertEqual(self.request('/api/terminal/start',body,token=False)[0],403)
            self.assertEqual(self.request('/api/terminal/input',body,origin='http://another-site.example')[0],403)
            manager.assert_not_called()
            manager.return_value.get.side_effect=ValueError('Terminal does not belong to this analysis')
            self.assertEqual(self.request('/api/terminal/poll',body)[0],400)
            manager.return_value.get.assert_called_with('foreign','a')
        req=Request(self.url+'/api/status',headers={'Host':'example.com'})
        with self.assertRaises(HTTPError) as error:urlopen(req)
        self.assertEqual(error.exception.code,403)

    def test_basic_file_previews_are_read_only_and_bounded(self):
        files={'example.json':'{"alpha": 0.1}', 'example.yaml':'alpha: 0.1', 'example.html':'<script>throw new Error("must not execute")</script>', 'example.svg':'<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>', 'large.log':'x'*120010}
        for name,text in files.items():(server.SOURCE/name).write_text(text)
        (server.SOURCE/'figure.gif').write_bytes(b'GIF89a')
        with patch.object(server,'ALLOWED',set(server.ALLOWED)|set(files)|{'figure.gif'}):
            for name,text in files.items():
                with urlopen(self.url+'/api/file?path='+name) as response:
                    self.assertIn('text/plain',response.headers['Content-Type'])
                    body=response.read().decode()
                    if name=='large.log':self.assertIn('Preview truncated',body);self.assertLess(len(body),120100)
                    else:self.assertEqual(body,text)
                self.assertEqual((server.SOURCE/name).read_text(),text)
            with urlopen(self.url+'/api/file?path=figure.gif') as response:
                self.assertIn('image/gif',response.headers['Content-Type']);self.assertEqual(response.read(),b'GIF89a')

    def test_project_snapshot_is_coherent_and_unchanged_poll_is_small(self):
        with patch.object(server,'INVENTORY',dict(scanned_at='fixture-snapshot',entries=[])):
            status,body=self.request('/api/project-snapshot?since=old')
            unchanged_status,unchanged_body=self.request('/api/project-snapshot?since=fixture-snapshot')
        self.assertEqual(status,200);snapshot=json.loads(body)
        self.assertEqual(snapshot['revision'],snapshot['inventory']['scanned_at'])
        self.assertIn('nodes',snapshot['model'])
        self.assertEqual(unchanged_status,200)
        self.assertEqual(json.loads(unchanged_body),{'revision':snapshot['revision']})

    def test_node_conversation_lookup_returns_relationships(self):
        reg=server.research_registry()
        reg.sync_nodes({'root_id':'lookup-fixture','nodes':[dict(id='lookup-fixture',title='Fixture node',storage={'folders':[str(server.SOURCE)]},inspectable=True)]})
        node=reg.resolve('lookup-fixture')
        conv=reg.register('lookup-fixture','Node history lookup fixture',new=True)
        status,body=self.request('/api/research/node-conversations?node=lookup-fixture')
        self.assertEqual(status,200);result=json.loads(body)
        self.assertEqual(result['node']['id'],node['id'])
        self.assertIn(conv['id'],{c['id'] for c in result['conversations']})

    def test_failed_model_build_retains_the_published_inventory(self):
        previous=server.INVENTORY
        with patch.object(server,'build_folder_model',side_effect=OSError('fixture disk interruption')):
            with self.assertRaises(OSError):server.load_inventory(dict(previous,entries=previous.get('entries',[]),scope='',scanned_at='new-failed-snapshot'))
        self.assertIs(server.INVENTORY,previous)

    def test_source_access_is_bounded(self):
        status,body=self.request('/api/file?path=script.py')
        self.assertEqual(status,200)
        self.assertIn(b'fixture only',body)
        for path in ['../private.txt','escape.txt','unattached.txt','/etc/passwd']:
            with self.subTest(path=path):
                self.assertEqual(self.request('/api/file?path='+path)[0],400)

    def test_mutations_require_same_origin_and_token(self):
        body=dict(node_id='a',title='A note',body='Test')
        self.assertEqual(self.request('/api/notes',body,token=False)[0],403)
        self.assertEqual(self.request('/api/notes',body,origin='http://another-site.example')[0],403)

    def test_note_and_edge_persist_across_initialization(self):
        status,data=self.request('/api/notes',dict(node_id='a',title='Decision',body='Keep original inputs'))
        self.assertEqual(status,201)
        note=json.loads(data)
        server.initialize()
        g=server.graph()
        self.assertTrue(any(n['id']==note['id'] and n['description']=='Keep original inputs' for n in g['nodes']))
        self.assertTrue(any(e['source']=='a' and e['target']==note['id'] for e in g['edges']))

    def test_saved_reply_belongs_to_its_node(self):
        m=server.save_message('a','assistant','Preserved answer','guide')
        body=dict(node_id='b',title='Reply',body='Changed content',message_id=m['id'])
        self.assertEqual(self.request('/api/notes',body)[0],400)
        body['node_id']='a'
        status,data=self.request('/api/notes',body)
        self.assertEqual(status,201)
        self.assertEqual(json.loads(data)['body'],'Preserved answer')

    def test_conversations_are_separate_and_durable(self):
        server.save_message('a','user','Context for A','guide')
        server.save_message('b','user','Context for B','guide')
        server.initialize()
        self.assertFalse(any(m['content']=='Context for B' for m in server.history('a')))
        self.assertTrue(any(m['content']=='Context for A' for m in server.history('a')))

    def test_note_on_note_has_one_graph_identity(self):
        _,data=self.request('/api/notes',dict(node_id='a',title='Parent note',body='Parent'))
        parent=json.loads(data)
        status,_=self.request('/api/notes',dict(node_id=parent['id'],title='Nested note',body='Child'))
        self.assertEqual(status,201)
        ids=[n['id'] for n in server.graph()['nodes']]
        self.assertEqual(len(ids),len(set(ids)))

    def test_saved_context_survives_missing_inventory_entry(self):
        node=dict(server.node_for('a'),id='fs-disappeared',title='Archived alpha context')
        with server.connect() as db:
            db.execute('INSERT OR REPLACE INTO node_records VALUES (?,?)',(node['id'],json.dumps(node)))
        server.initialize()
        record=server.node_for(node['id'])
        self.assertEqual(record['title'],'Archived alpha context')
        self.assertIn('absent',record['origin'])

    def test_rescan_preserves_messages_and_offline_scan_retains_snapshot(self):
        from inventory import scan
        folder=server.SOURCE/'analysis'
        folder.mkdir(exist_ok=True)
        (folder/'report.json').write_text('{"alpha":0.02}')
        data=scan(server.SOURCE,'analysis')
        old=server.INVENTORY,server.ENTRIES,server.CHILDREN,server.ALLOWED
        try:
            m=server.save_message('a','user','Keep through rescan','guide')
            with patch('server.scan',return_value=data):
                self.assertEqual(self.request('/api/rescan',{})[0],200)
            self.assertEqual(len(server.INVENTORY['entries']),2)
            self.assertTrue(any(row['id']==m['id'] for row in server.history('a')))
            with patch('server.scan',return_value={'entries':[]}):
                self.assertEqual(self.request('/api/rescan',{})[0],409)
            self.assertEqual(len(server.INVENTORY['entries']),2)
            path='analysis/report.json'
            self.assertEqual(self.request('/api/file?path='+path)[0],200)
            self.assertEqual(self.request('/api/download?path='+path)[0],200)
        finally:
            server.INVENTORY,server.ENTRIES,server.CHILDREN,server.ALLOWED=old
            (server.APP/'inventory.json').unlink(missing_ok=True)

    def test_analysis_description_edit_persists_without_changing_resources(self):
        from inventory import scan
        from records import build_records
        folder=server.SOURCE/'records-fixture'
        folder.mkdir(exist_ok=True)
        (folder/'report.json').write_text('{"description":"Recorded method"}')
        model=build_records(scan(server.SOURCE,'records-fixture'),server.SOURCE)
        with patch.object(server,'ANALYSES',model):
            record=model['nodes'][0]
            status,data=self.request('/api/record-update',dict(node_id=record['id'],title='Readable analysis',description='Purpose and method, edited by the researcher.'))
            self.assertEqual(status,200)
            edited=json.loads(data)['record']
            self.assertEqual(edited['documents'],record['documents'])
            self.assertEqual(edited['storage'],record['storage'])
            status,data=self.request('/api/analyses')
            self.assertEqual(json.loads(data)['nodes'][0]['title'],'Readable analysis')
            context=server.context_for(server.node_for(record['id']))
            self.assertEqual(context['selected_node']['title'],'Readable analysis')
            self.assertEqual(context['selected_node']['storage'],record['storage'])
            self.assertIn('related_analyses',context)

    def test_chat_job_returns_real_persisted_guide_answer(self):
        status,data=self.request('/api/chat',dict(node_id='a',message='Explain this node',engine='guide'))
        self.assertEqual(status,202)
        job_id=json.loads(data)['job_id']
        for _ in range(100):
            job=server.JOBS[job_id]
            if job['status']!='running':break
            threading.Event().wait(.01)
        self.assertEqual(job['status'],'done')
        self.assertIn('not an AI-generated analysis',job['message']['content'])
        self.assertEqual(job['message']['node_id'],'a')

    def test_codex_command_and_error_handling(self):
        event=json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'Source-based answer'}})
        result=type('Result',(),dict(returncode=0,stdout=event,stderr=''))()
        with patch('server.codex_binary',return_value='/fixture/codex'),patch('server.subprocess.run',return_value=result) as run:
            server.run_chat('mock-ok',server.node_for('a'),'Explain','codex')
        self.assertEqual(server.JOBS['mock-ok']['message']['content'],'Source-based answer')
        args=run.call_args.args[0]
        self.assertIn('read-only',args)
        self.assertIn('--ephemeral',args)
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',args)
        self.assertIn('selected_node',run.call_args.kwargs['input'])
        with patch('server.codex_binary',return_value=None):
            server.run_chat('mock-error',server.node_for('a'),'Explain','codex')
        self.assertEqual(server.JOBS['mock-error']['status'],'error')
        self.assertIn('not installed',server.JOBS['mock-error']['error'])


if __name__=='__main__':
    unittest.main()
