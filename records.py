"""Generic analysis records: evidence-backed descriptions and typed resource references."""
import hashlib
import json
from pathlib import Path

SCHEMA = {
 '$schema':'https://json-schema.org/draft/2020-12/schema',
 'title':'Research analysis node','type':'object',
 'required':['id','title','description','storage','code','data','figures','documents','relationships'],
 'properties':{
  'id':{'type':'string'},'title':{'type':'string'},'description':{'type':'string'},
  'storage':{'type':'object','required':['folders'],'properties':{'folders':{'type':'array','items':{'type':'string'}}}},
  'code':{'type':'array','items':{'type':'object'}},'data':{'type':'array','items':{'type':'object'}},
  'figures':{'type':'array','items':{'type':'object'}},'documents':{'type':'array','items':{'type':'object'}},
  'other':{'type':'array','items':{'type':'object'}},'relationships':{'type':'array','items':{'type':'object'}},
  'evidence':{'type':'array','items':{'type':'string'}},'provenance':{'type':'object'}},
 'additionalProperties':True}


def stable_id(path):
    return 'analysis-'+hashlib.sha256(path.encode()).hexdigest()[:20]


def build_records(inventory, root, catalog=None, anchors=None, boundary_filter=None):
    root=Path(root)
    entries=inventory.get('entries',[])
    if not entries:return dict(nodes=[],edges=[],coverage={})
    by_id={e['id']:e for e in entries}
    by_path={e['path']:e for e in entries}
    children={}
    for e in entries:children.setdefault(e['parent'],[]).append(e)
    root_entry=by_id[inventory['root_id']]
    boundaries={root_entry['path']:root_entry}
    for path in anchors or []:
        if path in by_path and by_path[path]['directory']:boundaries[path]=by_path[path]
    reports={}
    for e in entries:
        if e['directory'] or e.get('system_metadata'):continue
        if boundary_filter and not boundary_filter(e['path']):continue
        if e['extension']=='.json' and any(t in e['name'].lower() for t in ['report','summary']):
            parent=by_id.get(e['parent'])
            if parent and (parent['figure_count'] or 'report' in e['name'].lower()):
                boundaries[parent['path']]=parent
                reports.setdefault(parent['path'],[]).append(e)
    nodes={}
    input_references={}
    for path,folder in boundaries.items():
        node_id=stable_id(path)
        metadata=[]
        code=[]
        evidence=[]
        def resolve_script(value, report):
            candidate=Path(value)
            if root.name+'/' in value:
                candidate=root/value.split(root.name+'/',1)[1]
            elif not candidate.is_absolute():
                candidate=(root/report['path']).parent/value
            candidate=candidate.resolve()
            status='declared reference'
            if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
                candidate=(root/Path(value).name).resolve()
                status='filename match; generator not verified'
            if candidate.is_relative_to(root.resolve()) and candidate.is_file():
                code.append(dict(path=str(root/candidate.relative_to(root.resolve())),role='Source reference',status=status,evidence=str(root/report['path']),original_reference=value))
            else:
                code.append(dict(path=None,original_reference=value,role='Unresolved source reference',status='unresolved',evidence=str(root/report['path'])))
        def find_scripts(value,report):
            if isinstance(value,dict):
                for v in value.values():find_scripts(v,report)
            elif isinstance(value,list):
                for v in value:find_scripts(v,report)
            elif isinstance(value,str) and value.strip().endswith('.py') and '\n' not in value:
                resolve_script(value,report)
        def find_inputs(value,report,key=''):
            if isinstance(value,dict):
                for k,v in value.items():find_inputs(v,report,str(k))
            elif isinstance(value,list):
                for v in value:find_inputs(v,report,key)
            elif isinstance(value,str) and any(t in key.lower() for t in ['source','input']) and Path(value).suffix.lower() in {'.csv','.json','.pkl','.npz','.npy'} and '\n' not in value:
                candidate=(root/value.split(root.name+'/',1)[1]) if root.name+'/' in value else Path(value) if Path(value).is_absolute() else (root/report['path']).parent/value
                candidate=candidate.resolve()
                if candidate.is_relative_to(root.resolve()):
                    rel=candidate.relative_to(root.resolve()).as_posix()
                    if rel in by_path:input_references.setdefault(node_id,[]).append((by_path[rel],str(root/report['path'])))
        for report in sorted(reports.get(path,[]),key=lambda e:('report' not in e['name'].lower(),e['name'])):
            evidence.append(str(root/report['path']))
            p=root/report['path']
            try:
                if p.stat().st_size>512000:continue
                value=json.loads(p.read_text(errors='replace'))
                if not isinstance(value,dict):continue
                find_scripts(value,report)
                find_inputs(value,report)
                # Generic summary fields, not UI-specific parameter controls.
                for key,v in value.items():
                    if key in {'formula','method','description','scope','assumption','compatibility','stats','saturation','weighting','validity','alpha','growth_rate_multiplier','hardening_slope'} and isinstance(v,(str,int,float,bool)):
                        s=str(v)
                        if len(s)<700:metadata.append(key.replace('_',' ').capitalize()+': '+s)
            except (OSError,ValueError):pass
        title=folder['name'].replace('_',' ') if not folder['name'].startswith('Sample') else folder['name']
        if path==inventory['scope']:title='Back-stress research'
        # Path-derived facts belong in prose, not specialised UI fields.
        settings='; '.join(k.replace(' (path label)','').replace(' (path)','')+' = '+str(v) for k,v in folder.get('parameters',{}).items())
        description=' '.join(dict.fromkeys(metadata))
        if not description:description='Analysis record assembled from the saved reports and associated outputs at this storage location.'
        if settings:description+=' Recorded path context: '+settings+'.'
        description+=' Source and historical execution have not been independently verified.'
        if path==inventory['scope']:description='Research collection linking recorded analyses, methods, datasets, figures and source references. Each result retains its own resources and description. The complete file inventory remains available separately.'
        nodes[node_id]=dict(id=node_id,title=title,description=description,
            storage={'folders':[str(root/path)]},code=list({(c.get('path'),c.get('original_reference')):c for c in code}.values()),
            data=[],figures=[],documents=[],other=[],relationships=[],evidence=evidence,
            provenance={'discovery':'Report-based import','execution_verified':False,'relationships':'Inferred analysis variants are labelled; file ownership is an import association.'},
            inventory_folder_id=folder['id'],imported=True)
    paths=sorted(boundaries,key=len,reverse=True)
    owner={}
    figure_groups={}
    for e in entries:
        if e['directory']:continue
        # Walk ancestors: avoids scanning every boundary for every file.
        path=str(Path(e['path']).parent)
        if path=='.':path=''
        while path not in boundaries:
            parent=str(Path(path).parent)
            path='' if parent=='.' else parent
        node=nodes[stable_id(path)]
        owner[e['id']]=node['id']
        resource=dict(id=e['id'],path=str(root/e['path']),name=e['name'])
        ext=e['extension']
        if ext in {'.png','.pdf','.svg','.jpg','.jpeg','.webp','.gif'}:
            stem=str(Path(e['path']).with_suffix(''))
            group=figure_groups.setdefault((node['id'],stem),dict(id='figure-'+hashlib.sha256(stem.encode()).hexdigest()[:20],title=Path(stem).name,exports=[]))
            group['exports'].append(resource)
        elif ext in {'.py','.ipynb','.r','.jl','.m','.js','.jsx','.mjs','.ts','.sh','.applescript'}:
            node['code'].append(dict(**resource,role='Stored source file',status='discovered'))
        elif ext in {'.csv','.tsv','.npy','.npz','.pkl','.pickle','.parquet','.h5','.hdf5','.xlsx','.dat','.cpr','.crc'}:node['data'].append(resource)
        elif ext in {'.json','.md','.txt','.docx','.html','.pptx','.key','.qmd','.tex','.bib','.rtf'}:node['documents'].append(resource)
        else:node['other'].append(resource)
    for (node_id,_),figure in sorted(figure_groups.items()):nodes[node_id]['figures'].append(figure)
    # Retain useful prior source candidates, with their provenance explicitly labelled.
    for old in (catalog or {}).get('nodes',[]):
        for f in old.get('files',[]):
            if f.get('directory') and f['path'] in boundaries:
                node=nodes[stable_id(f['path'])]
                node['title']=old['title']
                if node['description'].startswith('Analysis record assembled'):
                    node['description']=old['description']+' '+node['description']
                for code in old['files']:
                    if code['path'].endswith('.py') and (root/code['path']).is_file():
                        p=str(root/code['path'])
                        if not any(c.get('path')==p for c in node['code']):node['code'].append(dict(path=p,role='Prior catalogue source candidate',status='candidate; generation unverified',evidence='Earlier curated catalogue'))
    edges=[]
    for path in boundaries:
        if path==inventory['scope']:continue
        parent=str(Path(path).parent)
        if parent=='.':parent=''
        while parent not in boundaries:
            p=str(Path(parent).parent);parent='' if p=='.' else p
        source,target=stable_id(parent),stable_id(path)
        relationship=dict(source=source,target=target,type='related_analysis' if parent==inventory['scope'] else 'variant_of',
                          evidence='Inferred from report scopes and shared analysis location; not a verified computation dependency',status='inferred')
        edges.append(relationship)
        nodes[target]['relationships'].append(dict(target=source,type=relationship['type'],direction='outgoing',status='inferred',evidence=relationship['evidence']))
        nodes[source]['relationships'].append(dict(target=target,type=relationship['type'],direction='incoming',status='inferred',evidence=relationship['evidence']))
    seen=set()
    flows={}
    for target,refs in input_references.items():
        for entry,evidence in refs:
            source=owner.get(entry['id'])
            if not source or source==target or (source,target,entry['id']) in seen:continue
            seen.add((source,target,entry['id']))
            resource=dict(id=entry['id'],path=str(root/entry['path']),name=entry['name'],role='Declared input',evidence=evidence)
            if not any(r['path']==resource['path'] for r in nodes[target]['data']):nodes[target]['data'].append(resource)
            flow=flows.setdefault((source,target),dict(resources=[],evidence=[]))
            flow['resources'].append(resource['path'])
            if evidence not in flow['evidence']:flow['evidence'].append(evidence)
    for (source,target),flow in flows.items():
        evidence=str(len(flow['resources']))+' declared input references in '+', '.join(flow['evidence'])
        edge=dict(source=source,target=target,type='uses_data',status='declared reference',evidence=evidence,resources=flow['resources'])
        edges.append(edge)
        nodes[target]['relationships'].append(dict(target=source,type='uses_data',direction='outgoing',status=edge['status'],evidence=evidence,resources=flow['resources']))
        nodes[source]['relationships'].append(dict(target=target,type='supplies_data',direction='outgoing',status=edge['status'],evidence=evidence,resources=flow['resources']))
    return dict(schema_version=1,nodes=list(nodes.values()),edges=edges,resource_owner=owner,
                coverage=dict(analyses=len(nodes),assigned_files=len(owner),inventory_files=inventory['counts'].get('files',0),unassigned_files=inventory['counts'].get('files',0)-len(owner)))


def node_adapter(record,root,max_files=None):
    root=Path(root)
    resources=record['code']+record['data']+record['documents']+record.get('other',[])+[f for fig in record['figures'] for f in fig['exports']]
    if max_files is not None:resources=resources[:max_files]
    files=[]
    for r in resources:
        p=Path(r['path']) if r.get('path') else None
        if p and p.is_relative_to(root):files.append(dict(path=p.relative_to(root).as_posix(),name=p.name,exists=p.exists(),directory=False))
    return dict(id=record['id'],title=record['title'],description=record['description'],kind='analysis',origin='Analysis record',
                files=files,parameters={},caveats=[],evidence=[str(Path(p).relative_to(root)) for p in record.get('evidence',[]) if Path(p).is_relative_to(root)],
                record=record,path=None,directory=False,x=0,y=0)
