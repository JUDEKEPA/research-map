import json
import tempfile
import unittest
from pathlib import Path
from inventory import scan
from records import stable_id
from folder_model import build_folder_model

class FolderModelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        files={'collection/method/report.json':json.dumps({'source':'plot.py'}),'collection/method/plot.py':'print("never run")','collection/method/variant/figures/result.png':'image','collection/method/variant/figures/result.pdf':'pdf','collection/method/variant/figures/._result.png':'metadata','collection/method/variant/data/table.csv':'a,b\n1,2','empty/.keep':''}
        for name,value in files.items():
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
        self.inventory=scan(self.root,'');self.model=build_folder_model(self.inventory,self.root);self.nodes={n['id']:n for n in self.model['nodes']}
    def tearDown(self):self.temp.cleanup()
    def node(self,path):return self.nodes[stable_id(path)]
    def test_graph_matches_direct_folder_hierarchy(self):
        self.assertEqual(len(self.nodes),self.inventory['counts']['folders'])
        self.assertEqual(len(self.model['edges']),len(self.nodes)-1)
        for e in self.model['edges']:
            child=self.nodes[e['target']];parent=self.nodes[e['source']]
            self.assertEqual(Path(child['folder_path']).parent.as_posix(),parent['folder_path'] or '.')
            self.assertEqual(e['type'],'contains_folder')
    def test_navigation_has_no_descendant_resources(self):
        for path in ('','collection','collection/method','collection/method/variant'):
            n=self.node(path);self.assertFalse(n['inspectable']);self.assertEqual(n['figures'],[]);self.assertEqual(n['data'],[]);self.assertFalse(any(n['resource_counts'].values()));self.assertEqual(n['member_ids'],[])
    def test_analysis_has_direct_resources_and_linked_code(self):
        n=self.node('collection/method/variant/figures')
        self.assertTrue(n['inspectable']);self.assertEqual(len(n['figures']),1);self.assertEqual(len(n['figures'][0]['exports']),2)
        self.assertTrue(any(c.get('path')==str(self.root/'collection/method/plot.py') and 'unverified' in c['status'] for c in n['code']))
        self.assertFalse(n['data'])
        data=self.node('collection/method/variant/data');self.assertTrue(data['inspectable']);self.assertEqual(len(data['data']),1);self.assertFalse(data['figures'])
    def test_generated_package_is_inspectable_with_standard_subfolders(self):
        path=self.root/'generated';(path/'code').mkdir(parents=True);(path/'data').mkdir();(path/'figures').mkdir()
        (path/'metadata.json').write_text(json.dumps({'schema_version':1,'node_id':'node-'+'a'*32,'description':'Generated analysis package'}))
        (path/'code/run.py').write_text('print("fixture only")')
        (path/'data/result.csv').write_text('x,y\n1,2')
        (path/'figures/result.png').write_text('fixture image')
        model=build_folder_model(scan(self.root,''),self.root)
        record=next(n for n in model['nodes'] if n['folder_path']=='generated')
        self.assertTrue(record['inspectable']);self.assertEqual(record['stable_node_id'],'node-'+'a'*32)
        self.assertTrue(record['code']);self.assertTrue(record['data']);self.assertTrue(record['figures'])

    def test_every_file_keeps_its_physical_owner(self):
        for e in self.inventory['entries']:
            if not e['directory']:
                self.assertEqual(self.model['resource_owner'][e['id']],stable_id('' if str(Path(e['path']).parent)=='.' else str(Path(e['path']).parent)))

if __name__=='__main__':unittest.main()
