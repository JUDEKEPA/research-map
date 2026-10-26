import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from inventory import scan
from inventory_watch import InventoryWatcher
from research_registry import Registry


class InventoryWatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Path(self.temp.name).resolve()
        self.source=self.app/'source';self.source.mkdir()
        self.reg=Registry(self.app,self.source);self.data=scan(self.source,'');self.refreshes=0
        def refresh():
            self.refreshes+=1;self.data=scan(self.source,'')
        self.watch=InventoryWatcher(self.reg,lambda:self.data,refresh,structure_interval=0)

    def tearDown(self):self.temp.cleanup()

    def package(self):
        path=self.source/'analysis';path.mkdir()
        with self.reg.transaction() as db:
            db.execute("INSERT INTO placement_plans(id,conversation_id,parent_id,path,specification,state,created) VALUES('p','c','root',?,'{}','created',0)",(str(path),))
        return path

    def test_new_generated_analysis_and_later_outputs_trigger_single_refresh_each(self):
        path=self.package()
        self.assertTrue(self.watch.poll());self.assertFalse(self.watch.poll())
        (path/'figures').mkdir();(path/'figures/result.png').write_bytes(b'image fixture')
        self.assertTrue(self.watch.poll());self.assertFalse(self.watch.poll())
        self.assertEqual(self.refreshes,2)
        self.assertIn('analysis/figures/result.png',{e['path'] for e in self.data['entries']})

    def test_unregistered_folder_is_discovered_from_parent_mtime(self):
        (self.source/'manual-analysis').mkdir()
        self.assertTrue(self.watch.poll());self.assertFalse(self.watch.poll())

    def test_disconnected_disk_preserves_inventory_and_recovers(self):
        self.package();self.watch.poll();before=self.data
        with patch.object(Path,'is_dir',return_value=False):self.assertFalse(self.watch.poll())
        self.assertIs(self.data,before)
        (self.source/'analysis/data.csv').write_text('x\n1\n')
        self.assertTrue(self.watch.poll())

    def test_failed_refresh_is_retried_without_acknowledging_change(self):
        self.package();original=self.watch.refresh
        self.watch.refresh=lambda:(_ for _ in ()).throw(OSError('temporary offline'))
        with self.assertRaises(OSError):self.watch.poll()
        self.watch.refresh=original;self.assertTrue(self.watch.poll())

    def test_outside_symlink_target_is_not_scanned(self):
        outside=self.app/'outside';outside.mkdir();(self.source/'linked').symlink_to(outside,target_is_directory=True)
        self.watch.poll();(outside/'private.txt').write_text('out of project')
        self.assertFalse(self.watch.poll())

if __name__=='__main__':unittest.main()
