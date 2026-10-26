import json
import tempfile
import unittest
from pathlib import Path
from inventory import scan
from records import build_records, stable_id, node_adapter, SCHEMA


class RecordTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.scope=self.root/'work'
        source=self.scope/'extraction'
        variant=self.scope/'comparison'/'variant'
        source.mkdir(parents=True)
        variant.mkdir(parents=True)
        (source/'values.csv').write_text('x,y\n1,2')
        (source/'report.json').write_text(json.dumps({'description':'Extract per-grain values'}))
        (self.root/'generator.py').write_text('print("not executed")')
        (variant/'analysis_report.json').write_text(json.dumps({'description':'Compare calculated work distributions','formula':'work = stress * strain','alpha':0.02,'source':str(source/'values.csv'),'source_scripts':[str(self.root/'generator.py')]}))
        (variant/'plot.png').write_text('fixture')
        (variant/'plot.pdf').write_text('fixture')
        (variant/'raw'/'nested').mkdir(parents=True)
        (variant/'raw'/'nested'/'unknown.bin').write_bytes(b'raw')
        self.inventory=scan(self.root,'work')
        self.model=build_records(self.inventory,self.root)

    def tearDown(self):self.temp.cleanup()

    def test_records_are_report_scopes_not_every_directory(self):
        self.assertEqual(len(self.model['nodes']),3)
        self.assertEqual(self.model['coverage']['unassigned_files'],0)
        self.assertEqual(self.model['coverage']['assigned_files'],self.inventory['counts']['files'])
        self.assertFalse(any(n['title']=='raw' for n in self.model['nodes']))
        for n in self.model['nodes']:
            self.assertTrue(set(SCHEMA['required']).issubset(n))

    def test_descriptions_and_resources_retain_evidence(self):
        n=next(n for n in self.model['nodes'] if n['id']==stable_id('work/comparison/variant'))
        self.assertIn('work = stress * strain',n['description'])
        self.assertIn('Alpha: 0.02',n['description'])
        self.assertEqual(len(n['figures']),1)
        self.assertEqual(len(n['figures'][0]['exports']),2)
        self.assertEqual(n['code'][0]['path'],str(self.root/'generator.py'))
        self.assertEqual(n['code'][0]['status'],'declared reference')
        self.assertEqual(n['other'][0]['name'],'unknown.bin')
        self.assertEqual(json.loads(json.dumps(n)),n)

    def test_declared_dataflow_distinguished_from_inferred_relationship(self):
        edges=[e for e in self.model['edges'] if e['type']=='uses_data']
        self.assertEqual(len(edges),1)
        self.assertEqual(edges[0]['source'],stable_id('work/extraction'))
        self.assertEqual(edges[0]['target'],stable_id('work/comparison/variant'))
        self.assertEqual(edges[0]['status'],'declared reference')
        n=next(n for n in self.model['nodes'] if n['id']==edges[0]['target'])
        self.assertEqual(n['data'][0]['role'],'Declared input')
        self.assertTrue(any(e['status']=='inferred' for e in self.model['edges']))

    def test_adapter_exposes_code_and_figures_for_existing_preview_api(self):
        n=next(n for n in self.model['nodes'] if n['title']=='variant')
        adapted=node_adapter(n,self.root)
        paths={f['path'] for f in adapted['files']}
        self.assertIn('generator.py',paths)
        self.assertIn('work/comparison/variant/plot.png',paths)


if __name__=='__main__':unittest.main()
