import base64
import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from terminal_bridge import TerminalManager, dimensions, PROJECT_TERMINAL_ID

class TerminalBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Path(self.temp.name);self.db=self.app/'state.sqlite3';self.calls=[]
        self.script=self.app/'fake_cli.py';self.script.write_text('''import os,sys,fcntl,termios,struct,signal
print('READY',os.isatty(0),os.isatty(1),os.open('/dev/tty',os.O_RDONLY)>=0,sys.argv[1],flush=True)
for line in sys.stdin:
 if line.strip()=='size': print('SIZE',struct.unpack('HHHH',fcntl.ioctl(0,termios.TIOCGWINSZ,b'\\0'*8))[:2],flush=True)
 else: print('REPLY:'+line.strip(),flush=True)
''')
        def factory(work,resume):self.calls.append((work,resume));return [sys.executable,str(self.script),str(resume)]
        self.manager=TerminalManager(self.app,self.db,sys.executable,factory)
        self.factory=factory
    def tearDown(self):self.manager.close_all();self.temp.cleanup()
    def node(self,key):return dict(id=key,record=dict(id=key,inspectable=True))
    def read_until(self,process,needle,cursor=0):
        text='';deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            result=process.poll(cursor,timeout=.2);cursor=result['cursor'];text+=base64.b64decode(result['data']).decode(errors='replace')
            if needle in text:return text,cursor
        self.fail('Expected '+needle+' in '+repr(text))
    def test_real_controlling_tty_keyboard_unicode_and_resize(self):
        status=self.manager.start(self.node('a'),{'selected':'a'},80,24);p=self.manager.get(status['terminal_id'],'a')
        text,cursor=self.read_until(p,'READY');self.assertIn('True True True False',text)
        p.write('copper α\n');text,cursor=self.read_until(p,'REPLY:copper α',cursor)
        p.resize(110,36);p.write('size\n');text,cursor=self.read_until(p,'SIZE',cursor);self.assertIn('(36, 110)',text)
    def test_nodes_have_separate_handles_and_workspaces(self):
        a=self.manager.start(self.node('a'),{'selected':'a'});b=self.manager.start(self.node('b'),{'selected':'b'})
        self.assertNotEqual(a['terminal_id'],b['terminal_id']);self.assertNotEqual(a['cwd'],b['cwd'])
        self.assertEqual(self.manager.start(self.node('a'),{})['terminal_id'],a['terminal_id'])
        with self.assertRaises(ValueError):self.manager.get(a['terminal_id'],'b')
        p=self.manager.get(a['terminal_id'],'a');q=self.manager.get(b['terminal_id'],'b')
        _,ac=self.read_until(p,'READY');_,bc=self.read_until(q,'READY');p.write('alpha-only\n');self.read_until(p,'REPLY:alpha-only',ac)
        self.assertNotIn(b'alpha-only',base64.b64decode(q.poll(bc,timeout=0)['data']))
        self.assertEqual(json.loads((Path(b['cwd'])/'context.json').read_text())['selected'],'b')
    def test_binding_resumes_after_manager_restart(self):
        a=self.manager.start(self.node('a'),{});p=self.manager.get(a['terminal_id'],'a');self.read_until(p,'READY');p.stop()
        self.manager.close_all();self.manager=TerminalManager(self.app,self.db,sys.executable,self.factory)
        resumed=self.manager.start(self.node('a'),{});self.assertTrue(resumed['resumed']);self.assertTrue(self.calls[-1][1]);self.assertEqual(resumed['cwd'],a['cwd'])
    def test_project_session_is_isolated_and_resumable(self):
        node=dict(id=PROJECT_TERMINAL_ID,record=dict(inspectable=True,terminal_scope='project'))
        project=self.manager.start(node,{'scope':'project','research_root':'/example/projects/Sample project'})
        analysis=self.manager.start(self.node('a'),{'selected':'a'})
        self.assertNotEqual(project['cwd'],analysis['cwd'])
        self.assertNotEqual(project['terminal_id'],analysis['terminal_id'])
        work=Path(project['cwd'])
        self.assertEqual(json.loads((work/'context.json').read_text())['scope'],'project')
        self.assertIn('whole research project',(work/'AGENTS.md').read_text())
        self.assertIn('single analysis',(Path(analysis['cwd'])/'AGENTS.md').read_text())
        process=self.manager.get(project['terminal_id'],PROJECT_TERMINAL_ID)
        self.read_until(process,'READY');process.stop()
        resumed=self.manager.start(node,{'scope':'project'})
        self.assertTrue(resumed['resumed']);self.assertEqual(project['cwd'],resumed['cwd'])

    def test_new_registered_conversation_does_not_resume_an_unregistered_terminal(self):
        from research_registry import Registry
        reg=Registry(self.app,self.app/'source');(self.app/'source').mkdir(exist_ok=True)
        reg.sync_nodes({'root_id':'a','nodes':[{'id':'a','title':'A','storage':{'folders':[str(self.app/'source')]}}]})
        self.manager.registry=reg
        import sqlite3
        with sqlite3.connect(self.manager.db) as db:db.execute('INSERT OR REPLACE INTO terminal_bindings VALUES (?,?,1)',('a',str(self.manager.workspace('a'))))
        result=self.manager.start(self.node('a'),{},new=True,objective='Fresh conversation')
        self.assertFalse(result['resumed'])

    def test_registered_conversations_keep_separate_workspaces_and_resume_binding(self):
        from research_registry import Registry
        source=self.app/'source';source.mkdir();reg=Registry(self.app,source)
        reg.sync_nodes({'root_id':'a','nodes':[dict(id='a',title='A',storage={'folders':[str(source)]}),dict(id='b',title='B',parent_id='a',storage={'folders':[str(source/'b')]})]})
        self.manager.registry=reg
        first=self.manager.start(self.node('a'),{})
        second=self.manager.start(self.node('a'),{},new=True,objective='Independent conversation')
        self.assertNotEqual(first['conversation_id'],second['conversation_id']);self.assertNotEqual(first['cwd'],second['cwd'])
        self.assertEqual(self.manager.start(self.node('a'),{},conversation_id=first['conversation_id'])['terminal_id'],first['terminal_id'])
        with self.assertRaises(ValueError):self.manager.start(self.node('b'),{},conversation_id=first['conversation_id'])
        self.assertTrue((Path(first['cwd'])/'recovery.json').is_file())
        self.assertEqual(json.loads((Path(first['cwd'])/'context.json').read_text())['research_management']['conversation_id'],first['conversation_id'])

    def test_cursor_replay_and_validation(self):
        a=self.manager.start(self.node('a'),{});p=self.manager.get(a['terminal_id'],'a');self.read_until(p,'READY')
        self.assertEqual(p.poll(0,timeout=0)['data'],p.poll(0,timeout=0)['data'])
        with self.assertRaises(ValueError):p.poll(-1)
        with self.assertRaises(ValueError):p.write('x'*70000)
        with self.assertRaises(ValueError):dimensions(1,2)
        with self.assertRaises(ValueError):self.manager.start(dict(id='missing-record'),{})
        self.assertFalse((self.app/'.codex-terminals'/'missing-record').exists())

if __name__=='__main__':unittest.main()
