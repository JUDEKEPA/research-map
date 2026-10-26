import json
import tempfile
import unittest
from pathlib import Path

from inventory import scan, identity, parameters, write_snapshot
import server


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.base='analysis'
        self.scope=self.root/self.base
        self.scope.mkdir()
        branches=['model/alpha_0.02/Sample','model/alpha_0.2/Sample','backup/alpha_0.02/Sample-B-repeat','empty']
        for rel in branches:
            p=self.scope/rel
            p.mkdir(parents=True)
            if rel!='empty':
                for name in ['figure.png','figure.pdf','values.csv']:
                    (p/name).write_text('fixture')
        (self.scope/'.hidden').write_text('hidden')
        (self.scope/'._metadata').write_text('metadata')
        (self.root/'outside.txt').write_text('outside')
        (self.scope/'escape.txt').symlink_to(self.root/'outside.txt')

    def tearDown(self):
        self.temp.cleanup()

    def test_every_file_folder_and_empty_directory_included(self):
        result=scan(self.root,self.base)
        expected={p.relative_to(self.root).as_posix() for p in self.scope.rglob('*')}|{self.base}
        self.assertEqual({e['path'] for e in result['entries']},expected)
        self.assertEqual(len(result['entries']),len(expected))
        self.assertTrue(result['complete'])
        self.assertEqual(result['counts']['files'],12)
        self.assertEqual(result['counts']['png'],3)
        empty=next(e for e in result['entries'] if e['path']=='analysis/empty')
        self.assertEqual(empty['child_count'],0)
        self.assertEqual(result['counts']['system_metadata'],1)

    def test_parameters_are_not_inferred_from_names(self):
        self.assertEqual(parameters('alpha_0.1/Sample/figure.png'), {})

    def test_rollups_parents_and_rescan_stability(self):
        first=scan(self.root,self.base)
        by={e['id']:e for e in first['entries']}
        root=by[identity(self.base)]
        self.assertEqual(root['file_count'],first['counts']['files'])
        self.assertEqual(root['folder_count']+1,first['counts']['folders'])
        self.assertEqual(root['figure_count'],3)
        for e in first['entries']:
            if e['parent']:self.assertIn(e['parent'],by)
        (self.scope/'new.csv').write_text('new')
        second=scan(self.root,self.base)
        self.assertTrue({e['id'] for e in first['entries']}.issubset({e['id'] for e in second['entries']}))
        self.assertEqual(second['counts']['files'],first['counts']['files']+1)
        write_snapshot(self.root,second)
        self.assertEqual(json.loads((self.root/'inventory.json').read_text())['counts'],second['counts'])

    def test_link_escape_blocked_and_nearby_evidence_stays_in_branch(self):
        old=server.SOURCE,server.INVENTORY,server.ENTRIES,server.CHILDREN,server.ALLOWED,server.APP,server.DB,server.RESEARCH
        try:
            (self.scope/'model/alpha_0.02/report.json').write_text('{"alpha":0.02}')
            (self.scope/'model/alpha_0.2/report.json').write_text('{"alpha":0.2}')
            server.SOURCE=self.root
            server.APP=self.root/'app';server.APP.mkdir(exist_ok=True);server.DB=server.APP/'workspace.sqlite3';server.RESEARCH=None
            result=scan(self.root,self.base)
            server.load_inventory(result)
            with self.assertRaises(ValueError):server.safe_source('analysis/escape.txt')
            e=next(e for e in result['entries'] if e['path'].endswith('model/alpha_0.02/Sample/figure.png'))
            node=server.inventory_node(e)
            self.assertEqual(len(node['files']),2)
            self.assertIn('analysis/model/alpha_0.02/report.json',node['evidence'])
            self.assertNotIn('analysis/model/alpha_0.2/report.json',node['evidence'])
        finally:
            server.SOURCE,server.INVENTORY,server.ENTRIES,server.CHILDREN,server.ALLOWED,server.APP,server.DB,server.RESEARCH=old

    def test_unavailable_disk_is_not_a_complete_empty_scan(self):
        result=scan(self.root,'missing')
        self.assertFalse(result['complete'])
        self.assertTrue(result['errors'])


if __name__=='__main__':unittest.main()
