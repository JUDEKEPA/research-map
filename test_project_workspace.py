import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from project_workspace import prepare_project,STATE_NAME
from inventory import scan
from folder_model import build_folder_model
from research_registry import Registry

CODE=Path(__file__).resolve().parent
class PortableProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.root=self.base/'Research project';self.root.mkdir()
        folder=self.root/'analysis';folder.mkdir();(folder/'values.csv').write_text('grain,stress\n1,123\n');(folder/'plot.py').write_text('# never executed\n')
    def tearDown(self):self.temp.cleanup()
    def prepare(self):return prepare_project(self.root,CODE)
    def test_metadata_excluded_skills_preserved_and_identity_survives_reopen(self):
        state,manifest=self.prepare();inventory=scan(self.root,'')
        self.assertFalse(any(STATE_NAME in e['path'].split('/') for e in inventory['entries']))
        self.assertEqual(len(list((state/'.agents/skills').glob('*/SKILL.md'))),4)
        skill=state/'.agents/skills/project-scan/SKILL.md';skill.write_text(skill.read_text()+'\nPersonal project rule\n')
        _,again=self.prepare();self.assertEqual(manifest['project_id'],again['project_id'])
        self.assertIn('Personal project rule',skill.read_text())
    def test_move_preserves_node_conversation_history_and_rebases_only_metadata(self):
        state,manifest=self.prepare();reg=Registry(state,self.root);model=build_folder_model(scan(self.root,''),self.root,{})
        mapping=reg.sync_nodes(model);analysis=next(n for n in model['nodes'] if n['title']=='analysis')
        conv=reg.register(analysis['id'],'Back-stress fixture',new=True);work=state/'.codex-terminals/test';work.mkdir(parents=True);reg.attach(conv['id'],work)
        reg.checkpoint(conv['id'],'Saved before moving')
        old=str(self.root);new=self.base/'Moved project';self.root.rename(new);self.root=new
        moved,again=self.prepare();newreg=Registry(moved,new)
        updated=newreg.sync_nodes(build_folder_model(scan(new,''),new,{}))
        self.assertEqual(manifest['project_id'],again['project_id']);self.assertEqual(mapping,updated)
        self.assertEqual(newreg.conversation(conv['id'])['workspace'],str(moved/'.codex-terminals/test'))
        self.assertEqual(newreg.recovery(conv['id'])['checkpoint']['summary'],'Saved before moving')
        self.assertEqual(newreg.lexical_path(old+'/analysis/values.csv'),str((new/'analysis/values.csv').resolve()))
        self.assertEqual((new/'analysis/values.csv').read_text(),'grain,stress\n1,123\n')
    def test_external_disk_appledouble_files_do_not_block_initialization(self):
        state=self.root/STATE_NAME;state.mkdir();(state/'._server.lock').write_bytes(b'filesystem metadata');(state/'.DS_Store').write_bytes(b'filesystem metadata')
        _,manifest=self.prepare();self.assertTrue(manifest['project_id']);self.assertTrue((state/'project.json').exists())

    def test_conflicting_or_symlink_metadata_does_not_get_overwritten(self):
        state=self.root/STATE_NAME;state.mkdir();(state/'unrelated').write_text('keep')
        with self.assertRaises(ValueError):self.prepare()
        self.assertEqual((state/'unrelated').read_text(),'keep')
    def test_legacy_sqlite_backup_preserves_conversations_without_moving_originals(self):
        legacy=self.base/'legacy';legacy.mkdir();reg=Registry(legacy,self.root);reg.sync_nodes(build_folder_model(scan(self.root,''),self.root,{}));conv=reg.register('project:root','Legacy conversation',new=True)
        state,manifest=prepare_project(self.root,CODE,legacy=legacy)
        self.assertTrue((legacy/'research.sqlite3').exists());self.assertEqual(Registry(state,self.root).conversation(conv['id'])['objective'],'Legacy conversation')

if __name__=='__main__':unittest.main()
