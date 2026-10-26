"""Generic evidence discovery without assumptions about a research domain."""
from pathlib import Path
from records import build_records, stable_id

def build_project(inventory, root, catalog=None):
    model = build_records(inventory, root, catalog, anchors=[e['path'] for e in inventory['entries'] if e['directory']])
    root_id = stable_id(inventory['scope'])
    for node in model['nodes']:
        node['kind'] = 'analysis'
        if node['id'] == root_id:
            node['title'] = Path(root).name
    model.update(project=True, root_id=root_id, overview_ids=[], figure_index={}, findings=[])
    return model
