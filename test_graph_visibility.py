import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from graph_cli import resolve
from graph_visibility import read_state, update_state


class VisibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'graph-visibility.json'
        self.nodes = [dict(id='r', title='Project'),dict(id='a',parent_id='r',title='Result',folder_path='a'),dict(id='b',parent_id='r',title='Result',folder_path='b')]

    def update(self, **patch):
        return update_state(self.path, patch, self.nodes, 'r')

    def test_ui_cli_roundtrip(self):
        self.assertFalse(read_state(self.path)['initialized'])
        first=self.update(hide=['a'])
        shown=self.update(reveal=['a'])
        self.assertIn('a',shown['revealed'])
        self.assertGreater(shown['revision'],first['revision'])
        normal=self.update(unhide=['a'])
        self.assertEqual(normal['revealed'],[])
        self.assertEqual(json.loads(self.path.read_text())['hidden'],[])

    def test_import_only_once(self):
        self.update(initialize=True,hide=['a'])
        self.update(initialize=True,hide=['b'])
        self.assertEqual(read_state(self.path)['hidden'],['a'])

    def test_independent_concurrent_edits_preserved(self):
        with ThreadPoolExecutor(2) as pool:
            list(pool.map(lambda key:self.update(hide=[key]),['a','b']))
        self.assertEqual(read_state(self.path)['hidden'],['a','b'])

    def test_invalid_requests_do_not_write(self):
        for patch in [dict(hide=['r']),dict(hide=['unknown']),dict(hide='a'),dict(delete=['a'])]:
            with self.assertRaises(ValueError):self.update(**patch)
        self.assertFalse(self.path.exists())

    def test_resolve_rejects_ambiguous_titles(self):
        with self.assertRaises(ValueError):resolve(self.nodes,'Result')
        self.assertEqual(resolve(self.nodes,'/example/projects/a')['id'],'a')
        self.assertEqual(resolve(self.nodes,'b')['id'],'b')


if __name__=='__main__':unittest.main()
