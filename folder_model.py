"""Physical folder navigation; only direct analysis resources are inspected."""
import json
import re
from pathlib import Path
from records import build_records, stable_id
from project import build_project

CATEGORIES=('code','data','figures','documents','other')

def build_folder_model(inventory, root, catalog=None):
    root=Path(root)
    folders={e['id']:e for e in inventory['entries'] if e['directory']}
    model=build_records(inventory,root,catalog,anchors=[e['path'] for e in folders.values()])
    evidence=build_project(inventory,root,catalog)
    sources={}
    for n in evidence['nodes']:
        if n['storage']['folders'] and n['kind']=='analysis':
            direct_refs=[c for c in n['code'] if 'inherited' not in c.get('status','').lower()]
            if direct_refs:sources.setdefault(str(Path(n['storage']['folders'][0])),dict(n,code=direct_refs))
    nodes={n['id']:n for n in model['nodes']}
    entries={e['id']:e for e in inventory['entries']}
    edges=[]
    for folder in folders.values():
        n=nodes[stable_id(folder['path'])]
        n.update(title=folder['name'],folder_path=folder['path'],parent_id=stable_id(entries[folder['parent']]['path']) if folder.get('parent') in folders else None,member_ids=[],relationships=[])
        # Data declared elsewhere are input references, not files owned by this folder.
        n['declared_inputs']=[r for r in n['data'] if model['resource_owner'].get(r['id'])!=n['id']]
        n['data']=[r for r in n['data'] if model['resource_owner'].get(r['id'])==n['id']]
        for category in ('code','data','documents','other'):
            n[category]=[r for r in n[category] if not entries.get(r.get('id'),{}).get('system_metadata')]
        figs=[]
        for f in n['figures']:
            exports=[r for r in f['exports'] if not entries.get(r['id'],{}).get('system_metadata')]
            if exports:figs.append(dict(f,exports=exports))
        n['figures']=figs
        # JSON numerical data count as data; reports and manifests remain documents.
        docs=[]
        for r in n['documents']:
            name=r['name'].lower()
            if name.endswith('.json') and not any(t in name for t in ('report','summary','manifest','config','catalog','status','settings','metadata')):
                n['data'].append(r)
            else:docs.append(r)
        n['documents']=docs
        package=None;meta=root/folder['path']/'metadata.json'
        if meta.is_file() and meta.resolve().is_relative_to(root.resolve()) and meta.stat().st_size<100000:
            try:
                candidate=json.loads(meta.read_text())
                if isinstance(candidate,dict) and candidate.get('schema_version')==1 and re.fullmatch(r'node-[0-9a-f]{32}',candidate.get('node_id','')):package=candidate
            except (OSError,ValueError,TypeError):pass
        if package:n['generated_package']=package
        n['inspectable']=bool((package and package.get('role')!='collection') or n['data'] or n['figures']) and folder['id']!=inventory['root_id']
        n['kind']='analysis' if n['inspectable'] else 'navigation'
        if n['inspectable']:
            cursor=root/folder['path'];match=None
            while cursor.is_relative_to(root):
                if str(cursor) in sources:match=sources[str(cursor)];break
                if cursor==root:break
                cursor=cursor.parent
            if match:
                for ref in match['code']:
                    if not any(c.get('path')==ref.get('path') and c.get('original_reference')==ref.get('original_reference') for c in n['code']):
                        inherited=cursor!=root/folder['path']
                        n['code'].append(dict(ref,role='Parent-analysis source candidate' if inherited else ref.get('role','Source candidate'),status='inherited association; exact generator unverified' if inherited else ref.get('status','candidate'),associated_folder=str(cursor)))
            n['description']='Direct contents of '+folder['path']+'. '+n['description']
        else:
            n['description']='Navigation folder. Open a child folder to find an analysis; resources from descendants are not combined here.'
        n['resource_counts']={k:len(n[k]) if n['inspectable'] else 0 for k in CATEGORIES}
        n['provenance']['discovery']='Direct folder contents'
        if n['parent_id']:
            edges.append(dict(source=n['parent_id'],target=n['id'],type='contains_folder',status='filesystem',evidence='Direct parent folder on disk'))
    # Generated packages explicitly own their standard code/data/figures subtrees.
    # Historical folders retain the original direct-content inspection policy.
    for n in nodes.values():
        package=n.get('generated_package')
        if not package:continue
        n['description']=package.get('description',n['description'])
        n['stable_node_id']=package['node_id']
        for category,subfolder in (('code','code'),('data','data'),('figures','figures')):
            prefix=n['folder_path']+'/'+subfolder
            refs=[];seen=set()
            for child in nodes.values():
                if child['folder_path']!=prefix and not child['folder_path'].startswith(prefix+'/'):continue
                for ref in child[category]:
                    key=ref.get('path') or ref.get('id')
                    if key not in seen:refs.append(ref);seen.add(key)
            n[category]=refs
        n['resource_counts']={k:len(n[k]) for k in CATEGORIES}
        n['provenance']['discovery']='Generated research package; execution verification is recorded separately'
    for edge in edges:
        nodes[edge['source']]['relationships'].append(dict(target=edge['target'],type='child_folder',direction='outgoing',status='filesystem',evidence=edge['evidence']))
        nodes[edge['target']]['relationships'].append(dict(target=edge['source'],type='parent_folder',direction='outgoing',status='filesystem',evidence=edge['evidence']))
    root_id=stable_id(inventory['scope'])
    return dict(schema_version=3,project=True,folder_model=True,nodes=list(nodes.values()),edges=edges,resource_owner=model['resource_owner'],root_id=root_id,overview_ids=[],figure_index={},findings=[],coverage=dict(model['coverage'],analyses=sum(n['inspectable'] for n in nodes.values()),navigation_folders=sum(not n['inspectable'] for n in nodes.values()),records=len(nodes)))
