from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import generate_demo
from inventory import scan
from folder_model import build_folder_model

class DemoTests(unittest.TestCase):
    def test_fictional_packages_and_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'Orchard Study'
            with patch.object(generate_demo, 'ROOT', root): generate_demo.generate()
            before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch.object(generate_demo, 'ROOT', root): generate_demo.generate()
            self.assertEqual(before,{p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()})
            model=build_folder_model(scan(root,''),root,{})
            nodes={n['folder_path']:n for n in model['nodes']}
            for name in ('baseline','faster-growth'):
                node=nodes['analyses/growth-model/'+name]
                self.assertTrue(node['inspectable'])
                self.assertTrue(node['code']);self.assertTrue(node['data']);self.assertTrue(node['figures'])
                self.assertTrue((root/node['folder_path']/'figures/growth.png').read_bytes().startswith(b'\x89PNG'))
            self.assertEqual(nodes['analyses/growth-model/baseline']['parent_id'],nodes['analyses/growth-model/faster-growth']['parent_id'])

if __name__=='__main__':unittest.main()
