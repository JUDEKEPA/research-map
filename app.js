'use strict';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fileURL=p=>'/api/file?path='+encodeURIComponent(p), downloadURL=p=>'/api/download?path='+encodeURIComponent(p);
const state={inventory:null,entries:new Map(),children:new Map(),legacy:null,scope:null,selected:null,node:null,view:'graph',page:0,query:'',type:'',model:null,records:new Map(),analysisFocus:null,tab:'overview',expanded:new Set(),token:'',messages:[],pending:new Map(),errors:new Map(),request:0,zoom:1};
let folderForceGraph=null;
let results=[],pageItems=[],gallery=[],toastTimer,noteParent,noteMessage,previewItem;
const num=n=>Number(n||0).toLocaleString();
const label=e=>e.directory?e.name.replaceAll('_',' '):e.name;
function toast(s){$('#toast').textContent=s;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,5000);}
async function api(path,options={}){const headers={...options.headers};if(options.body){headers['Content-Type']='application/json';headers['X-Workspace-Token']=state.token;}const r=await fetch(path,{...options,headers});const b=await r.json();if(!r.ok)throw new Error(b.error||'Request failed');return b;}
function ingest(data){state.inventory=data;state.entries=new Map(data.entries.map(e=>[e.id,e]));state.children=new Map();for(const e of data.entries){if(!state.children.has(e.parent))state.children.set(e.parent,[]);state.children.get(e.parent).push(e);}for(const list of state.children.values())list.sort(sortEntries);}
// Both navigation surfaces read and mutate this one model.
function setupFolderNavigation(model){
 if(!model.folder_model)return;
 let saved=state.navigation?state.navigation.snapshot():null;
 if(!saved){try{saved=JSON.parse(localStorage.getItem('folder-navigation-v1')||localStorage.getItem('folder-force-map-v1')||'{}');}catch(e){saved={};}}
 state.navigation=new FolderGraphState(model,saved);
 state.folderRecords=new Map(model.nodes.map(n=>[n.inventory_folder_id,n]));
 if(state.records.has(state.analysisFocus))state.navigation.ensurePath(state.analysisFocus,false);
 saveFolderNavigation();
}
function saveFolderNavigation(){if(state.navigation){queueVisibilitySync();try{localStorage.setItem('folder-navigation-v1',JSON.stringify(state.navigation.snapshot()));}catch(e){}}}
// Local view actions and CLI edits share one small metadata document.
let visibilityBaseline=null,visibilityRevision=-1,visibilityPending=0,visibilityGeneration=0,visibilityChain=Promise.resolve();
function visibilityShape(){return {hidden:[...state.navigation.hidden].sort(),revealed:[...state.navigation.revealed].sort()};}
function applyVisibility(remote){
 const before=JSON.stringify(visibilityShape());
 state.navigation.hidden=new Set(remote.hidden.filter(id=>state.records.has(id)));
 state.navigation.revealed=new Set(remote.revealed.filter(id=>state.navigation.hidden.has(id)));
 visibilityBaseline=visibilityShape();visibilityRevision=remote.revision;
 if(before!==JSON.stringify(visibilityBaseline)){
  saveFolderNavigation();
  if(folderForceGraph){
   if(state.view==='graph'&&state.navigation.suppressed(state.analysisFocus)){
    const parent=state.navigation.lineage(state.analysisFocus).find(id=>!state.navigation.suppressed(id))||state.navigation.root;
    folderForceGraph.localFocus=parent;selectItem(parent,{fromGraph:true});folderForceGraph.focus(parent,true);
   }else folderForceGraph.rebuild(false);
  }
 }
}
function queueVisibilitySync(){
 if(!visibilityBaseline||!state.navigation)return;
 const current=visibilityShape(),patch={};
 for(const [key,add,remove] of [['hidden','hide','unhide'],['revealed','reveal','conceal']]){
  patch[add]=current[key].filter(id=>!visibilityBaseline[key].includes(id));
  patch[remove]=visibilityBaseline[key].filter(id=>!current[key].includes(id));
 }
 if(!Object.values(patch).some(ids=>ids.length))return;
 visibilityBaseline=current;visibilityPending++;const generation=++visibilityGeneration;
 visibilityChain=visibilityChain.catch(()=>{}).then(async()=>{
  try{const remote=await api('/api/graph-visibility',{method:'POST',body:JSON.stringify(patch)});if(generation===visibilityGeneration)applyVisibility(remote);}
  catch(error){visibilityRevision=-1;toast('Graph visibility was not saved: '+error.message);}
  finally{visibilityPending--;}
 });
}
async function initializeVisibility(){
 try{
  let remote=await api('/api/graph-visibility');
  if(!remote.initialized)remote=await api('/api/graph-visibility',{method:'POST',body:JSON.stringify({initialize:true,hide:[...state.navigation.hidden],reveal:[...state.navigation.revealed]})});
  applyVisibility(remote);
  setInterval(async()=>{
   if(document.hidden||visibilityPending)return;
   const generation=visibilityGeneration;
   try{const next=await api('/api/graph-visibility');if(!visibilityPending&&generation===visibilityGeneration&&next.revision!==visibilityRevision)applyVisibility(next);}catch{/* A later poll reconnects after a server restart. */}
  },1500);
 }catch(error){toast('CLI graph controls unavailable: '+error.message);}
}
function revealSelectedFolder(){if(state.view==='files')requestAnimationFrame(()=>$('#tree .tree-folder.selected')?.scrollIntoView({block:'nearest'}));}
function toggleFolderBranch(inventoryId){
 const record=state.folderRecords?.get(inventoryId);
 if(!record){state.expanded.has(inventoryId)?state.expanded.delete(inventoryId):state.expanded.add(inventoryId);renderTree();return;}
 state.navigation.toggle(record.id);state.navigation.required.clear();saveFolderNavigation();
 // Match graph collapse: when a branch hides the selection, select its parent node.
 if(!state.navigation.open.has(record.id)&&!state.navigation.large.has(record.id)&&state.scope!==inventoryId&&ancestor(state.entries.get(state.scope),inventoryId)){selectItem(record.id,{fromGraph:true});return;}
 renderTree();renderMap();
}
function sortEntries(a,b){return Number(b.directory)-Number(a.directory)||a.name.localeCompare(b.name,undefined,{numeric:true});}
function ancestor(e,id){while(e){if(e.id===id)return true;e=state.entries.get(e.parent);}return false;}
function chain(e){const a=[];while(e){a.unshift(e);e=state.entries.get(e.parent);}return a;}
function fullPath(e){return state.inventory.source+(e.path?'/'+e.path:'');}
function resourceCounts(r){return r.resource_counts||Object.fromEntries(['code','data','figures','documents','other'].map(k=>[k,r[k]?.length||0]));}
function formatBytes(n){if(n===null)return 'Unknown size';if(n<1024)return n+' B';if(n<1048576)return (n/1024).toFixed(1)+' KB';return (n/1048576).toFixed(1)+' MB';}
function kind(e){if(e.directory)return 'folder';if(['.png','.pdf','.svg','.jpg','.jpeg','.gif','.webp'].includes(e.extension))return 'figure';if(['.md','.txt'].includes(e.extension))return 'note';return 'data';}
function tagHTML(e){return '';}
function rawCandidates(){
 const scope=state.entries.get(state.scope);if(!scope)return [];
 const deep=$('#recursive').checked||!!state.query||!!state.type;
 return state.inventory.entries.filter(e=>e.id!==scope.id&&(deep?(!scope.path||e.path.startsWith(scope.path+'/')):e.parent===scope.id)&&
 (!state.query||e.path.toLowerCase().includes(state.query))&&
 (!state.type||(state.type==='folder'?e.directory:e.extension===state.type)));
}
function semanticFigureCandidates(){if(state.model.project&&state.node?.record){const record=state.records.get(state.analysisFocus),ids=new Set();for(const key of [record.id,...(record.member_ids||[])])for(const id of state.model.figure_index[key]||[])ids.add(id);return state.inventory.entries.filter(e=>ids.has(e.id)&&(!state.query||e.path.toLowerCase().includes(state.query))&&(!state.type||e.extension===state.type));}return rawCandidates().filter(e=>!e.directory&&kind(e)==='figure');}
function grouped(entries){
 const groups=new Map();const output=[];
 for(const e of entries){if(!e.directory&&['.png','.pdf'].includes(e.extension)){const stem=e.path.replace(/\.[^.]+$/,'');if(!groups.has(stem)){groups.set(stem,[]);output.push(stem);}groups.get(stem).push(e);}else output.push(e);}
 return output.map(v=>{if(typeof v!=='string')return v;const exports=groups.get(v);return {...(exports.find(e=>e.extension==='.png')||exports[0]),exports};});
}
function buildResults(){
 if(state.view==='graph'){
   const focus=state.analysisFocus||state.model.nodes[0].id;
   const linked=new Set();for(const e of state.model.edges)if(e.source===focus||e.target===focus){linked.add(e.source);linked.add(e.target);}linked.delete(focus);
   results=state.query?state.model.nodes.filter(n=>JSON.stringify(n).toLowerCase().includes(state.query)):state.model.nodes.filter(n=>linked.has(n.id));
   const order={project:0,observations:1,pipeline:1,topic:2,dataset:3,collection:4,decision:5,finding:6};results.sort((a,b)=>(order[a.kind]??7)-(order[b.kind]??7)||a.title.localeCompare(b.title,undefined,{numeric:true}));
 }else{results=state.view==='figures'?grouped(semanticFigureCandidates()):rawCandidates();results.sort(sortEntries);}
 $('#prev').hidden=false;$('#next').hidden=false;const size=state.view==='graph'?18:state.view==='figures'?24:60;
 state.page=Math.max(0,Math.min(state.page,Math.max(0,Math.ceil(results.length/size)-1)));pageItems=results.slice(state.page*size,(state.page+1)*size);
 gallery=state.view==='figures'?results:grouped(semanticFigureCandidates());
 $('.result-footer').hidden=state.view==='graph'||results.length<=size;$('#page-label').textContent=`Page ${state.page+1}`;$('#prev').disabled=state.page===0;$('#next').disabled=(state.page+1)*size>=results.length;$('#empty-results').hidden=results.length>0;
}
function renderTree(){
 if(state.model.folder_model||state.view==='files'){renderInventoryTree();return;}
 let nodes=state.model.nodes.filter(n=>!state.query||JSON.stringify(n).toLowerCase().includes(state.query));if(state.model.project&&!state.query){const focus=state.analysisFocus,ids=new Set([state.model.root_id,...state.model.overview_ids,focus]);for(const e of state.model.edges)if(e.source===focus||e.target===focus){ids.add(e.source);ids.add(e.target);}nodes=nodes.filter(n=>ids.has(n.id));}const sidebarTotal=nodes.length;nodes=nodes.slice(0,100);
 $('#tree').innerHTML=nodes.map(n=>`<button class="analysis-item ${n.id===state.selected?'selected':''}" data-analysis="${esc(n.id)}"><i></i><span>${esc(n.title)}</span></button>`).join('')+(sidebarTotal>100?`<p class="source-note">Showing 100 of ${num(sidebarTotal)} matches. Refine search; all records remain in the graph.</p>`:'');
 $('#tree').querySelectorAll('[data-analysis]').forEach(b=>{b.onclick=()=>selectItem(b.dataset.analysis);attachTooltip(b,state.records.get(b.dataset.analysis));});
}
function renderInventoryTree(){
 function subtree(parent,depth){return (state.children.get(parent)||[]).map(e=>{
 if(!e.directory)return `<div class="tree-line tree-file-line" style="--depth:${depth}"><span class="tree-file-spacer"></span><button class="tree-file" data-tree-file="${esc(e.id)}" title="${esc(fullPath(e))}"><span class="tree-file-icon">${imageExtensions.has(e.extension)?'▧':'▤'}</span><span>${esc(e.name)}</span></button></div>`;
 const recordId=state.folderRecords?.get(e.id)?.id;
 const opened=state.navigation?(state.navigation.open.has(recordId)||state.navigation.large.has(recordId)):state.expanded.has(e.id),has=(state.children.get(e.id)||[]).length>0;
 return `<div class="tree-line" style="--depth:${depth}"><button class="tree-toggle" data-expand="${esc(e.id)}" aria-expanded="${opened}" aria-label="${opened?'Collapse':'Expand'} ${esc(e.name)}" ${has?'':'disabled'}>${has?(opened?'⌄':'›'):'·'}</button><button class="tree-folder ${e.id===state.scope?'selected':''}" data-folder="${esc(e.id)}" title="${esc(fullPath(e))}"><span>${esc(e.name)}</span></button></div>${opened?subtree(e.id,depth+1):''}`;}).join('');}
 const root=state.entries.get(state.inventory.root_id),rootOpen=!state.navigation||state.navigation.open.has(state.model.root_id);
 $('#tree').innerHTML=state.navigation?`<div class="tree-line" style="--depth:0"><button class="tree-toggle" data-expand="${esc(root.id)}" aria-expanded="${rootOpen}" aria-label="${rootOpen?'Collapse':'Expand'} ${esc(root.name)}">${rootOpen?'⌄':'›'}</button><button class="tree-folder ${root.id===state.scope?'selected':''}" data-folder="${esc(root.id)}" title="${esc(root.path)}"><span>${esc(root.name)}</span></button></div>${rootOpen?subtree(root.id,1):''}`:subtree(root.id,0);
 $('#tree').querySelectorAll('[data-expand]').forEach(b=>b.onclick=()=>{toggleFolderBranch(b.dataset.expand);});
 $('#tree').querySelectorAll('[data-folder]').forEach(b=>b.onclick=()=>openFolder(b.dataset.folder));
 $('#tree').querySelectorAll('[data-tree-file]').forEach(b=>b.onclick=()=>{const entry=state.entries.get(b.dataset.treeFile);gallery=(state.children.get(entry.parent)||[]).filter(e=>!e.directory&&imageExtensions.has(e.extension));showPreview(entry);});
}
function renderSaved(){const nodes=state.legacy.nodes;$('#saved-list').innerHTML=nodes.map(n=>`<button data-saved="${esc(n.id)}" title="${esc(n.title)}">${n.origin==='Workspace note'?'≡':'◇'} ${esc(n.title)}</button>`).join('');$('#saved-list').querySelectorAll('button').forEach(b=>b.onclick=()=>selectItem(b.dataset.saved));}
function renderHeader(){
 const scope=state.entries.get(state.scope),c=state.inventory.counts,record=state.records.get(state.analysisFocus);
 if(state.view==='graph'&&state.model.folder_model){const folder=state.entries.get(record?.inventory_folder_id);$('#breadcrumbs').innerHTML=chain(folder).map(e=>`<button data-folder-crumb="${esc(e.id)}">${esc(e.name)}</button>`).join('<span> / </span>');$$('[data-folder-crumb]').forEach(b=>b.onclick=()=>openFolder(b.dataset.folderCrumb));$('#up').disabled=!record?.parent_id;}else if(state.view==='graph'){$('#breadcrumbs').innerHTML=`<button id="analysis-home">All analyses</button>${record?'<span> / </span><span>'+esc(record.title)+'</span>':''}`;$('#analysis-home').onclick=()=>selectItem(state.model.nodes[0].id);$('#up').disabled=state.analysisFocus===state.model.nodes[0].id;}
 else{$('#breadcrumbs').innerHTML=chain(scope).map((e,i)=>`${i?'<span> / </span>':''}<button data-breadcrumb="${esc(e.id)}" title="${esc(e.path)}">${esc(e.id===state.inventory.root_id?'Storage':e.name)}</button>`).join('');$('#breadcrumbs').querySelectorAll('button').forEach(b=>b.onclick=()=>openFolder(b.dataset.breadcrumb));$('#up').disabled=!scope.parent;}
 $('#active-context').innerHTML=state.query?`<span class="chip">Search: ${esc(state.query)}</span><button id="search-whole">Search all resources ↗</button>`:'';
 if($('#search-whole'))$('#search-whole').onclick=()=>{state.scope=state.inventory.root_id;renderBrowser();};
}
function attachTooltip(element,record){if(!record)return;function show(event){const box=$('#node-tooltip');if(inspectorWindow.id===record.id&&!inspectorWindow.panel.hidden){box.hidden=true;return;}box.innerHTML=`<strong>${esc(record.title)}</strong><p>${esc(record.description)}</p>`;box.hidden=false;const r=element.getBoundingClientRect();const x=event?.clientX||r.right,y=event?.clientY||r.top;box.style.left=Math.max(12,Math.min(window.innerWidth-365,x+16))+'px';box.style.top=Math.max(12,Math.min(window.innerHeight-260,y+14))+'px';element.setAttribute('aria-describedby','node-tooltip');}element.onmouseenter=show;element.onfocus=show;element.onmousemove=event=>{if(!$('#node-tooltip').hidden)show(event);};element.onmouseleave=()=>$('#node-tooltip').hidden=true;element.onblur=()=>$('#node-tooltip').hidden=true;}

function svg(tag,attrs={},text){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e;}
function renderMap(){
 if(state.model.folder_model){
  $('#node-tooltip').hidden=true;
  if(!folderForceGraph)folderForceGraph=new FolderForceGraph({svg:$('#graph'),panel:$('#graph-panel'),tooltip:attachTooltip,onExpansionChange:()=>{saveFolderNavigation();renderTree();},onSelect:id=>{resetFilters();selectItem(id,{fromGraph:true});},onStatus:info=>{
   const message=info.limited?'Collapse a branch to explore more.':info.matches>60?'Refine your search to see more matches.':info.matches===0?'No matching folders.':'';
   $('#graph-notice').textContent=message;$('#graph-notice').hidden=!message;
   if(state.view==='graph'){$('#page-label').textContent='';$('#prev').hidden=true;$('#next').hidden=true;$('#empty-results').hidden=true;}
  }});
  folderForceGraph.update(state.model,state.analysisFocus,{external:!!state.graphExternal,query:state.query,navigation:state.navigation,preserveView:!!state.preserveGraphView});state.graphExternal=false;return;
 }
 $('#node-tooltip').hidden=true;
 $('#graph-panel').scrollTop=0;
 const vp=$('#viewport');vp.replaceChildren();const focus=state.records.get(state.analysisFocus)||state.model.nodes[0];
 const width=Math.max(540,$('#graph-panel').clientWidth-20),cols=width>850?4:3,rows=Math.ceil(pageItems.length/cols),compact=pageItems.length<=12,gap=compact?64:92,startY=compact?105:185,height=(compact?100:180)+rows*gap;
 $('#graph').setAttribute('viewBox',`0 0 ${width} ${height}`);$('#graph').style.height=Math.max(220,height*Math.min(1,$('#graph-panel').clientWidth/width)*state.zoom)+'px';
 const cx=width/2,cy=compact?35:65;
 function dot(record,x,y,active){const g=svg('g',{transform:`translate(${x},${y})`,class:'analysis-dot '+(active?'active':'')+' kind-'+(record.kind||'analysis'),role:'button',tabindex:0,'aria-label':record.title});g.append(svg('rect',{x:-85,y:-18,width:170,height:55,fill:'transparent','pointer-events':'all',rx:8}));g.append(svg('circle',{r:active?9:6}));g.append(svg('text',{x:0,y:25,'text-anchor':'middle'},record.title.length>30?record.title.slice(0,29)+'…':record.title));g.append(svg('title',{},record.description));g.onclick=()=>{$('#node-tooltip').hidden=true;selectItem(record.id);};g.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();selectItem(record.id);}};attachTooltip(g,record);vp.append(g);}
 for(let i=0;i<pageItems.length;i++){const n=pageItems[i],x=(i%cols+.5)*width/cols,y=startY+Math.floor(i/cols)*gap;const edges=state.model.edges.filter(e=>(e.source===focus.id&&e.target===n.id)||(e.target===focus.id&&e.source===n.id));const declared=edges.some(e=>e.status==='declared reference');const path=svg('path',{d:`M${cx},${cy+9} C${cx},${cy+65} ${x},${y-55} ${x},${y-7}`,class:'semantic-edge '+(declared?'declared':'inferred')});path.append(svg('title',{},edges.map(e=>e.type+' · '+e.evidence).join('\n')||'Search result; no direct relationship asserted'));if(edges.length)vp.append(path);dot(n,x,y,false);}
 dot(focus,cx,cy,true);
}

function renderFiles(){
 const scope=state.entries.get(state.scope);
 $('#results').innerHTML=`<div class="file-table"><div class="file-table-head"><span>Name / relative path</span><span>Type</span><span>Size</span></div>${pageItems.map(e=>`<div class="inventory-file ${e.id===state.selected?'selected':''}"><button data-entry="${esc(e.id)}" title="${esc(e.path)}"><strong><span class="type-symbol ${kind(e)}">${e.directory?'▸':kind(e)==='figure'?'▧':'▤'}</span>${esc(e.name)}</strong><small>${esc(e.path.slice(scope.path?scope.path.length+1:0)||'.')}</small><span>${tagHTML(e)}</span></button><span class="file-type">${e.directory?'Folder':esc(e.extension.slice(1).toUpperCase()||'File')}</span><span class="file-size">${e.directory?num(e.file_count)+' files':formatBytes(e.size)}</span></div>`).join('')}</div>`;
 bindEntries();
}
function renderFigures(){
 $('#results').innerHTML='<div class="figure-grid">'+pageItems.map(e=>`<article class="figure-tile ${e.id===state.selected?'selected':''}"><button class="thumbnail" data-preview="${esc(e.id)}" aria-label="Preview ${esc(e.name)}">${['.png','.jpg','.jpeg','.gif','.webp'].includes(e.extension)?`<img loading="lazy" decoding="async" src="${fileURL(e.path)}" alt="${esc(e.name)}">`:'<span class="pdf-tile">PDF figure · open preview</span>'}</button><button class="figure-name" data-select="${esc(e.id)}" title="${esc(e.path)}">${esc(e.name.replace(/\.[^.]+$/,''))}</button><div class="figure-tags">${tagHTML(e)}<span class="format-chip">${(e.exports||[e]).map(v=>esc(v.extension.slice(1).toUpperCase())).join(' · ')}</span></div><p title="${esc(e.path)}">${esc(e.path.slice(state.inventory.scope?state.inventory.scope.length+1:0))}</p><button class="tile-open" data-select="${esc(e.id)}">Context & conversation ↗</button></article>`).join('')+'</div>';
 $('#results').querySelectorAll('[data-preview]').forEach(b=>b.onclick=()=>openPreview(b.dataset.preview));$('#results').querySelectorAll('[data-select]').forEach(b=>b.onclick=()=>selectItem(b.dataset.select));
}
function bindEntries(){$$('#results [data-entry]').forEach(b=>b.onclick=()=>{const e=state.entries.get(b.dataset.entry);e.directory?openFolder(e.id):selectItem(e.id);});}
function renderBrowser(){
 if(!state.inventory)return;
 const folders=state.view!=='graph';
 document.body.classList.add('graph-view');document.body.classList.toggle('folder-view',folders);
 folderWindow.sync(folders);
 $('#filetype').hidden=true;$('.recursive-label').hidden=true;
 $('#clear-filters').hidden=!state.query&&!state.type&&!(folders&&$('#recursive').checked);
 renderProjectContext();renderHeader();$('#graph-panel').hidden=false;renderMap();buildResults();
 $('#results').hidden=!folders;
 $$('[data-view]').forEach(b=>{b.classList.toggle('selected',b.dataset.view===state.view);b.setAttribute('aria-pressed',String(b.dataset.view===state.view));});
 if(state.view==='files')renderFiles();else if(state.view==='figures')renderFigures();
 $('#folder-window-context').textContent=state.entries.get(state.scope)?.name||state.projectName||'Project';
}
function renderProjectContext(){if(state.model.folder_model){$('#project-context').innerHTML='';return;}const n=state.records.get(state.analysisFocus),box=$('#project-context');if(!state.model.project||state.view!=='graph'){box.innerHTML='';return;}if(n.kind==='project'){box.innerHTML='<div class="research-route"><strong>A way into the project</strong><p>Choose a question → inspect a method → select the experiment and variant → retrieve the recorded data, code and figure.</p><small>Research, processing, writing and review are separate entry points below.</small></div>';}else if(n.research_question){box.innerHTML=`<div class="research-route"><strong>${esc(n.research_question)}</strong><small>${esc(n.dataset?'Dataset: '+n.dataset:'Cross-dataset / method view')} · ${esc(n.lifecycle||'unverified')}</small></div>`;}else if(n.kind==='review'){box.innerHTML='<div class="research-route"><strong>Evidence to resolve</strong><p>Open an item to see the actual files and affected analysis. Source data has not been changed.</p></div>';}else box.innerHTML='';}
function resetFilters(){state.query='';state.type='';$('#search').value='';$('#filetype').value='';state.page=0;}
async function openFolder(id,{keepFilters=false}={}){if(state.model.folder_model){const r=state.model.nodes.find(n=>n.inventory_folder_id===id);if(r){if(!keepFilters)resetFilters();if(state.navigation&&!state.navigation.open.has(r.id)&&!state.navigation.large.has(r.id)){state.navigation.open.set(r.id,24);saveFolderNavigation();}return selectItem(r.id);}}const e=state.entries.get(id);if(!e?.directory)return;state.scope=id;localStorage.setItem('inventory-scope',id);state.page=0;if(!keepFilters)resetFilters();for(const p of chain(e))state.expanded.add(p.id);renderTree();renderBrowser();await selectItem(id);}
function getLocalNode(id){if(state.records.has(id)){const r=state.records.get(id);return {id:r.id,title:r.title,description:r.description,kind:'analysis',record:r,files:[],parameters:{},evidence:[],origin:'Analysis record'};}const e=state.entries.get(id);if(!e)return state.legacy.nodes.find(n=>n.id===id);return {id:e.id,title:e.name,kind:e.directory?'analysis':kind(e),description:e.directory?`Discovered folder with ${num(e.file_count)} files, ${num(e.folder_count)} nested folders and ${num(e.figure_count)} PNG figures.`:'Discovered file; scientific provenance not independently verified.',files:e.directory?[]:[{path:e.path,name:e.name,exists:true,directory:false}],parameters:e.parameters,caveats:[],evidence:[],origin:'Filesystem inventory',path:e.path,directory:e.directory,parent:e.parent};}
async function selectItem(id,{fromGraph=false}={}){
 if(inspectorWindow.id&&inspectorWindow.id!==id)inspectorWindow.close();
 state.graphExternal=!fromGraph;
 if(state.selected)sessionStorage.setItem('draft:'+state.selected,$('#chat-input').value);
 state.selected=id;state.node=getLocalNode(id);if(state.records.has(id)){state.analysisFocus=id;if(state.navigation){state.navigation.ensurePath(id,!fromGraph);saveFolderNavigation();}state.resourceCategory=['code','data','figures','documents','other'].find(k=>resourceCounts(state.records.get(id))[k]>0)||'data';state.resourceOffset=0;const folder=state.inventory.entries.find(e=>e.directory&&fullPath(e)===state.records.get(id).storage.folders[0]);if(folder){state.scope=folder.id;localStorage.setItem('inventory-scope',folder.id);if(!state.navigation)for(const p of chain(folder))state.expanded.add(p.id);}else if(!state.records.get(id).storage.folders.length)state.scope=state.inventory.root_id;state.page=0;localStorage.setItem('analysis-focus',id);renderBrowser();renderTree();revealSelectedFolder();}state.messages=[];state.request++;const seq=state.request;localStorage.setItem('inventory-selected',id);
 if(state.model.folder_model&&state.node?.record?.inspectable===false){if(state.view==='figures'){state.view='graph';renderBrowser();}renderInspector();return;}
 $('#chat-input').value=sessionStorage.getItem('draft:'+id)||'';renderInspector();renderMessages();
 try{const [node,messages]=await Promise.all([api('/api/node?id='+encodeURIComponent(id)),api('/api/messages?node='+encodeURIComponent(id))]);if(seq!==state.request)return;state.node=node;state.messages=messages;renderInspector();renderMessages();}catch(e){if(seq===state.request)toast(e.message);}
}
function renderInspector(){
 const n=state.node;if(!n)return;const r=n.record;const navigation=state.model.folder_model&&r?.inspectable===false;
 $('#new-note').hidden=navigation;window.codexTerminalPane?.select(n,state.token,()=>state.messages);
 if(navigation||inspectorWindow.id!==n.id){$('.inspector').hidden=true;return;}
 $('.inspector').hidden=false;inspectorWindow.wake();
 if(!r){$('#node-heading').innerHTML=`<div class="kind-label">RESOURCE / SAVED RECORD</div><h2>${esc(n.title)}</h2>`;$('#node-detail').innerHTML=`<p>${esc(n.description)}</p>${n.files.map(f=>`<button class="evidence-file" data-preview-path="${esc(f.path)}">${esc(f.name)}</button>`).join('')}`;}
 else{
 $('#node-heading').innerHTML=`<div class="kind-label">ANALYSIS RECORD</div><h2>${esc(r.title)}</h2><div class="record-tools"><button id="browse-node-files" class="secondary">Files &amp; figures</button><button id="edit-record" class="record-action">Edit description ↗</button></div>`;
 let html='';
 if(state.tab==='overview'){html=`<p class="record-description">${esc(r.description)}</p><div class="section-label">STORAGE LOCATIONS</div>${r.storage.folders.map(p=>`<div class="path">${esc(p)}</div>`).join('')}<div class="resource-counts">${['code','data','figures','documents'].map(k=>`<button data-resource-category="${k}">${esc(k[0].toUpperCase()+k.slice(1))}</button>`).join('')}</div><p class="source-note">${esc(r.provenance.discovery)}. Relationships and source candidates retain their evidence.</p>${r.lifecycle?'<span class="lifecycle-badge">'+esc(r.lifecycle.replaceAll('_',' '))+'</span>':''}${r.execution_notes?'<div class="caveat">'+esc(r.execution_notes.declared_output?'Generator output: '+r.execution_notes.declared_output:JSON.stringify(r.execution_notes))+'</div>':''}`;}
 else if(state.tab==='json'){html=`<button id="open-record-json" class="secondary">Open full JSON ↗</button><pre class="record-json">${esc(JSON.stringify(r,null,2))}</pre>`;}
 else if(state.tab==='files'){
   html=state.model.project?'<div id="resource-browser"></div>':['code','data','figures','documents','other'].map(k=>`<details class="resource-group" ${k==='code'?'open':''}><summary>${esc(k[0].toUpperCase()+k.slice(1))} <span></span></summary>${(r[k]||[]).map(v=>k==='figures'?`<details class="export-group"><summary>${esc(v.title)}</summary>${v.exports.map(resourceRow).join('')}</details>`:resourceRow(v)).join('')||'<p class="source-note">No references recorded.</p>'}</details>`).join('');
 }
 else{html=r.relationships.map(e=>{const target=state.records.get(e.target);return `<button class="connection" data-record-target="${esc(e.target)}">${esc(target?.title||e.target)}<small>${esc(e.type.replaceAll('_',' '))} · ${esc(e.status)}<br>${esc(e.evidence)}</small></button>`;}).join('')||'<p>No relationships recorded.</p>';}
 $('#node-detail').innerHTML=html;
 if(state.tab==='files'&&state.model.project)loadResourcePage();
 $('#browse-node-files').onclick=()=>openNodeFiles(r.id);
 $('#edit-record').onclick=()=>{$('#record-title').value=r.title;$('#record-title').readOnly=!!state.model.folder_model;$('#record-description').value=r.description;$('#record-dialog').showModal();};
 if($('#open-record-json'))$('#open-record-json').onclick=()=>{const b=$('#preview-content'),pre=document.createElement('pre');pre.textContent=JSON.stringify(r,null,2);b.replaceChildren(pre);$('#preview-title').textContent=r.title+' · JSON';$('#preview-context').textContent='Complete analysis record';$('#preview-previous').disabled=true;$('#preview-next').disabled=true;$('#preview-download').href=URL.createObjectURL(new Blob([JSON.stringify(r,null,2)],{type:'application/json'}));$('#preview-download').download=r.id+'.json';openPreviewWindow();};
 $$('#node-detail [data-resource-category]').forEach(b=>b.onclick=()=>{state.resourceCategory=b.dataset.resourceCategory;state.resourceOffset=0;state.tab='files';renderInspector();});
 $$('#node-detail [data-record-target]').forEach(b=>b.onclick=()=>selectItem(b.dataset.recordTarget));
 }
 $('#context-label').textContent='↳ '+n.title;$$('.inspector-tabs button').forEach(b=>b.classList.toggle('selected',b.dataset.tab===state.tab));
 $$('#node-detail [data-preview-path]').forEach(b=>b.onclick=()=>previewPath(b.dataset.previewPath));
}
function resourceTabs(category){
 return '<div class="resource-tabs">'+['code','data','figures','documents','other'].map(k=>`<button data-resource-tab="${k}" class="${k===category?'selected':''}">${k}</button>`).join('')+'</div>';
}
function bindResourceTabs(box){
 box.querySelectorAll('[data-resource-tab]').forEach(b=>b.onclick=()=>{state.resourceCategory=b.dataset.resourceTab;state.resourceOffset=0;loadResourcePage();});
}
let figureFolderCache=null;
function renderFigureFolders(box,id){
 const record=state.records.get(id),path=record?.storage?.folders?.[0];
 const folder=state.entries.get(record?.inventory_folder_id)||state.inventory.entries.find(e=>e.directory&&fullPath(e)===path);
 if(!folder){box.insertAdjacentHTML('beforeend','<p class="source-note">Folder is not available in the saved inventory.</p>');return;}
 // Mark ancestors of every figure once per inventory, including intermediate folders
 // that contain no direct figures. Other files never enter this tree.
 if(figureFolderCache?.inventory!==state.inventory){
  const folders=new Set();
  for(const entry of state.inventory.entries){
   if(entry.directory||entry.system_metadata||!imageExtensions.has(entry.extension))continue;
   let parent=entry.parent;
   while(parent&&!folders.has(parent)){folders.add(parent);parent=state.entries.get(parent)?.parent;}
  }
  figureFolderCache={inventory:state.inventory,folders};
 }
 const inspectGallery=[];
 const collectFigures=folderId=>{for(const entry of state.children.get(folderId)||[]){if(entry.directory){if(figureFolderCache.folders.has(entry.id))collectFigures(entry.id);}else if(!entry.system_metadata&&imageExtensions.has(entry.extension))inspectGallery.push(entry);}};
 collectFigures(folder.id);
 const tree=document.createElement('div');tree.className='figure-folder-tree';tree.setAttribute('aria-label','Figure folders and files');
 const appendContents=(target,folderId)=>{
  for(const entry of state.children.get(folderId)||[]){
   if(entry.directory){
    if(!figureFolderCache.folders.has(entry.id))continue;
    const group=document.createElement('details');group.className='figure-folder';
    const summary=document.createElement('summary');summary.textContent=entry.name;summary.title=fullPath(entry);group.append(summary);
    group.addEventListener('toggle',()=>{if(group.open&&!group.dataset.loaded){group.dataset.loaded='true';const children=document.createElement('div');children.className='figure-folder-contents';appendContents(children,entry.id);group.append(children);}});
    target.append(group);
   }else if(!entry.system_metadata&&imageExtensions.has(entry.extension)){
    const button=document.createElement('button');button.className='figure-tree-file';button.textContent='▧ '+entry.name;button.title=fullPath(entry);
    button.onclick=()=>{gallery=inspectGallery;showPreview(entry);};target.append(button);
   }
  }
 };
 appendContents(tree,folder.id);
 if(!tree.childElementCount){const empty=document.createElement('p');empty.className='source-note';empty.textContent='No figures in this folder or its subfolders.';tree.append(empty);}
 box.insertAdjacentHTML('beforeend','<p class="source-note">Figures · open subfolders to browse</p>');box.append(tree);
}
async function loadResourcePage(){
 const request=state.resourceRequest=(state.resourceRequest||0)+1;
 const id=state.selected,category=state.resourceCategory||'code',offset=state.resourceOffset||0,box=$('#resource-browser');if(!box)return;
 box.innerHTML=resourceTabs(category);bindResourceTabs(box);
 if(category==='figures'){renderFigureFolders(box,id);return;}
 box.insertAdjacentHTML('beforeend','<p class="source-note">Retrieving recorded resources…</p>');
 try{
  const data=await api('/api/record-resources?id='+encodeURIComponent(id)+'&category='+category+'&offset='+offset+'&limit=50');
  if(state.resourceRequest!==request||state.selected!==id||!$('#resource-browser'))return;
  box.innerHTML=resourceTabs(category)+`<p class="source-note">${category==='code'?'Code references':category[0].toUpperCase()+category.slice(1)}${state.model.folder_model?(category==='code'?' · linked to this analysis':' · this folder only'):' · includes linked sub-analyses'}</p>`+data.items.map(resourceRow).join('')+`<div class="resource-pagination" ${data.total<=50?'hidden':''}><button id="resource-prev" ${offset===0?'disabled':''}>←</button><span>Page ${Math.floor(offset/50)+1}</span><button id="resource-next" ${offset+50>=data.total?'disabled':''}>→</button></div>`;
  bindResourceTabs(box);
  box.querySelectorAll('[data-preview-path]').forEach(b=>b.onclick=()=>previewPath(b.dataset.previewPath));
  $('#resource-prev').onclick=()=>{state.resourceOffset=Math.max(0,offset-50);loadResourcePage();};
  $('#resource-next').onclick=()=>{state.resourceOffset=offset+50;loadResourcePage();};
 }catch(e){if(state.resourceRequest===request&&state.selected===id&&$('#resource-browser'))box.textContent=e.message;}
}
function resourceRow(v){if(!v.path)return `<p class="unresolved-reference">${esc(v.original_reference||'Unknown source')}<small>${esc(v.status||'Unresolved')}</small></p>`;const path=v.path.startsWith(state.inventory.source+'/')?v.path.slice(state.inventory.source.length+1):v.path;return `<div class="file-row"><button data-preview-path="${esc(path)}">${esc(v.name||v.path.split('/').pop())}<small>${esc([v.role,v.status].filter(Boolean).join(' · ')||'Recorded resource')}</small><small class="resource-path">${esc(path)}</small></button><a href="${downloadURL(path)}" download title="Retrieve original">↓</a></div>`;}

function renderMessages(){window.codexTerminalPane?.controls();const box=$('#messages');box.innerHTML=state.messages.map(m=>`<div class="message ${esc(m.role)}"><div class="message-label">${m.role==='user'?'YOU':m.engine==='codex'?'CODEX CLI':'LOCAL GUIDE · NO AI'}</div><div class="message-content">${esc(m.content)}</div>${m.role==='assistant'?`<button class="save-reply" data-message="${esc(m.id)}">＋ Save as connected note</button>`:''}</div>`).join('');if(!state.messages.length)box.innerHTML='<p class="empty-chat">This conversation stays with the selected item, including its full folder ancestry and nearby report context.</p>';if(state.pending.has(state.selected))box.innerHTML+='<p class="pending">● Reading selected context… You can browse while the reply runs.</p>';if(state.errors.has(state.selected))box.innerHTML+=`<p class="error-message">${esc(state.errors.get(state.selected))}</p>`;box.querySelectorAll('[data-message]').forEach(b=>b.onclick=()=>openNote(state.messages.find(m=>m.id===b.dataset.message)));$('#send').disabled=state.pending.has(state.selected);box.scrollTop=box.scrollHeight;}
async function loadMessages(id=state.selected){try{const m=await api('/api/messages?node='+encodeURIComponent(id));if(state.selected===id){state.messages=m;renderMessages();}}catch(e){toast(e.message);}}
async function submitChat(message){const id=state.selected;if(!message.trim()||state.pending.has(id))return;state.pending.set(id,'starting');state.errors.delete(id);renderMessages();try{const r=await api('/api/chat',{method:'POST',body:JSON.stringify({node_id:id,message,engine:$('#engine').value})});state.pending.set(id,r.job_id);sessionStorage.setItem('pending:'+id,r.job_id);if(state.selected===id){$('#chat-input').value='';sessionStorage.removeItem('draft:'+id);await loadMessages(id);}pollJob(id,r.job_id);}catch(e){state.pending.delete(id);state.errors.set(id,e.message);if(state.selected===id)renderMessages();}}
async function pollJob(id,job){try{const r=await api('/api/job?id='+encodeURIComponent(job));if(r.status==='running'){setTimeout(()=>pollJob(id,job),1200);return;}state.pending.delete(id);sessionStorage.removeItem('pending:'+id);if(r.status==='error')state.errors.set(id,r.error);if(r.status==='done'){state.legacy=await api('/api/graph');renderSaved();}if(state.selected===id)await loadMessages(id);else toast(r.status==='done'?'A reply is ready on '+(getLocalNode(id)?.title||'your selected item'):r.error);}catch(e){state.pending.delete(id);sessionStorage.removeItem('pending:'+id);state.errors.set(id,e.message);if(state.selected===id)renderMessages();}}
const readableExtensions=new Set(['.json','.py','.md','.txt','.csv','.tsv','.toml','.yaml','.yml','.ini','.cfg','.log','.ipynb','.r','.jl','.sh','.js','.ts','.jsx','.tsx','.css','.html','.htm','.xml','.sql','.tex','.bib','.rst']);
const imageExtensions=new Set(['.png','.jpg','.jpeg','.gif','.webp','.bmp','.svg']);
const figureExtensions=new Set(['.png','.jpg','.jpeg','.gif','.webp','.bmp','.svg','.pdf']);
const fileBrowser={folder:null,filter:'all',query:'',page:0,recursive:false};
function openNodeFiles(id){
 const record=state.records.get(id),path=record?.storage?.folders?.[0];
 const folder=state.entries.get(record?.inventory_folder_id)||state.inventory.entries.find(e=>e.directory&&fullPath(e)===path);
 if(!folder){toast('Folder is not available in the saved inventory.');return;}
 Object.assign(fileBrowser,{folder:folder.id,filter:'all',query:'',page:0,recursive:false});
 $('#files-search').value='';$('#files-recursive').checked=false;renderNodeFiles();
 if(!$('#files-dialog').open)$('#files-dialog').showModal();
}
function renderNodeFiles(){
 const folder=state.entries.get(fileBrowser.folder);if(!folder)return;
 $('#files-up').disabled=!folder.parent;
 $('#files-breadcrumbs').replaceChildren();
 for(const entry of chain(folder)){
  const button=document.createElement('button');button.textContent=entry.name;button.onclick=()=>{fileBrowser.folder=entry.id;fileBrowser.page=0;renderNodeFiles();};$('#files-breadcrumbs').append(button);
 }
 const q=fileBrowser.query,all=fileBrowser.recursive?state.inventory.entries.filter(e=>e.id!==folder.id&&(!folder.path||e.path.startsWith(folder.path+'/'))):state.children.get(folder.id)||[];
 const entries=all.filter(e=>(!fileBrowser.recursive||!e.directory)&&(!q||e.path.toLowerCase().includes(q))&&(e.directory||fileBrowser.filter==='all'||(fileBrowser.filter==='text'?readableExtensions.has(e.extension):figureExtensions.has(e.extension)))).sort(sortEntries);
 gallery=entries.filter(e=>!e.directory&&figureExtensions.has(e.extension));
 const size=fileBrowser.filter==='figures'?24:50;fileBrowser.page=Math.max(0,Math.min(fileBrowser.page,Math.max(0,Math.ceil(entries.length/size)-1)));
 const page=entries.slice(fileBrowser.page*size,(fileBrowser.page+1)*size),box=$('#files-list');box.classList.toggle('files-gallery',fileBrowser.filter==='figures');
 box.innerHTML=page.map(e=>{
  if(fileBrowser.filter==='figures'&&!e.directory){const raster=['.png','.jpg','.jpeg','.gif','.webp','.bmp'].includes(e.extension);return `<button class="files-figure" data-browse-file="${esc(e.id)}"><span class="files-thumbnail">${raster?`<img loading="lazy" src="${fileURL(e.path)}" alt="${esc(e.name)}">`:esc(e.extension.slice(1).toUpperCase())}</span><strong>${esc(e.name)}</strong></button>`;}
  return `<div class="files-entry"><button data-browse-file="${esc(e.id)}"><strong><span>${e.directory?'▸':figureExtensions.has(e.extension)?'▧':'▤'}</span>${esc(e.name)}</strong><small>${esc(e.path.slice(folder.path?folder.path.length+1:0))}</small></button>${e.directory?'':`<a href="${downloadURL(e.path)}" download="${esc(e.name)}" aria-label="Download ${esc(e.name)}">↓</a>`}</div>`;
 }).join('')||'<p class="files-empty">No matching files in this folder. Open a subfolder or enable Include subfolders.</p>';
 box.querySelectorAll('[data-browse-file]').forEach(button=>button.onclick=()=>{const e=state.entries.get(button.dataset.browseFile);if(e.directory){fileBrowser.folder=e.id;fileBrowser.page=0;renderNodeFiles();}else showPreview(e);});
 $$('.files-tabs button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.fileFilter===fileBrowser.filter)));
 $('#files-prev').disabled=fileBrowser.page===0;$('#files-next').disabled=(fileBrowser.page+1)*size>=entries.length;
 $('.files-pages').hidden=entries.length<=size;
}
function sourcePreview(text,ext){
 if(ext==='json'||ext==='ipynb'){try{text=JSON.stringify(JSON.parse(text),null,2);}catch{/* Incomplete or truncated JSON stays readable as original text. */}}
 if(text.length>240000)text=text.slice(0,240000)+'\n[Formatted preview truncated. Download the original for the complete file.]';
 const pre=document.createElement('pre');pre.className='source-reader';pre.setAttribute('aria-label','Read-only file contents');
 for(const [index,line] of text.split('\n').entries()){const row=document.createElement('span');row.className='source-line';const number=document.createElement('span');number.className='source-line-number';number.setAttribute('aria-hidden','true');number.textContent=String(index+1);const code=document.createElement('code');code.textContent=line||' ';row.append(number,code);pre.append(row);}
 return pre;
}
function layoutPreviewWindow(){
 const panel=$('#preview-dialog');if(!panel.open)return;
 const graph=$('#graph-panel').getBoundingClientRect(),navigator=$('#folder-window');
 const left=Math.max(graph.left,navigator.hidden?0:navigator.getBoundingClientRect().right),right=Math.min(innerWidth,graph.right);
 const available=right-left-24,width=Math.min(1200,Math.max(0,available));
 // WebKit collapses a flex child inside a dialog with only max-height. Give
 // the viewer a definite height so text and decoded images have visible space.
 const height=Math.max(100,Math.min(760,Math.min(innerHeight,graph.bottom)-graph.top-24));
 panel.style.visibility=available<80?'hidden':'visible';
 Object.assign(panel.style,{left:(left+12+Math.max(0,(available-width)/2))+'px',top:(graph.top+12)+'px',width:width+'px',height:height+'px',maxHeight:height+'px'});
}
function openPreviewWindow(){
 const panel=$('#preview-dialog');
 // The navigator remains interactive while switching files. Preserve modal
 // stacking only when the separate modal file browser is already open.
 if(!panel.open){if($('#files-dialog').open)panel.showModal();else panel.show();}
 layoutPreviewWindow();
}
window.addEventListener('resize',layoutPreviewWindow);
new ResizeObserver(layoutPreviewWindow).observe($('#graph-panel'));
async function previewPath(path){const e=state.inventory.entries.find(e=>e.path===path);if(e)return openPreview(e.id);await showPreview({path,name:path.split('/').pop(),parameters:{}});}
async function openPreview(id){const e=gallery.find(e=>e.id===id)||state.entries.get(id);if(e)await showPreview(e);}
async function showPreview(e){previewItem=e;$('#preview-title').textContent=e.name;$('#preview-context').innerHTML=`<div>${tagHTML(e)}</div><p class="path">${esc(e.path)}</p>`;$('#preview-download').href=downloadURL(e.path);$('#preview-download').download=e.name;
 const index=gallery.findIndex(x=>x.id===e.id);$('#preview-previous').disabled=index<=0;$('#preview-next').disabled=index<0||index>=gallery.length-1;
 const box=$('#preview-content');box.textContent='Loading original file…';openPreviewWindow();
 const ext=e.path.split('.').pop().toLowerCase();
 try{
  if(['png','jpg','jpeg','gif','webp','bmp','svg'].includes(ext)){
   const img=document.createElement('img');img.alt=e.path;img.tabIndex=0;img.setAttribute('role','button');img.title='Click to toggle original size';img.setAttribute('aria-label','Toggle original size: '+e.name);
   box.classList.remove('actual-size');img.onclick=()=>box.classList.toggle('actual-size');img.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();img.click();}};
   if(ext==='svg'){const response=await fetch(fileURL(e.path));if(!response.ok)throw new Error('SVG file unavailable');const text=await response.text();if(previewItem!==e)return;const url=URL.createObjectURL(new Blob([text],{type:'image/svg+xml'}));img.src=url;img.onload=()=>URL.revokeObjectURL(url);img.onerror=()=>{URL.revokeObjectURL(url);if(previewItem===e)box.textContent='This SVG cannot be displayed. Download the original to inspect it.';};}
   else{img.src=fileURL(e.path);img.onerror=()=>{if(previewItem===e)box.textContent='Image unavailable. Check the source disk and refresh.';};}
   if(previewItem===e)box.replaceChildren(img);
  }else if(ext==='pdf'){const iframe=document.createElement('iframe');iframe.title=e.name;iframe.src=fileURL(e.path);box.replaceChildren(iframe);}
  else if(!readableExtensions.has('.'+ext)){box.textContent='Preview is not available for this file type. Use Download original to open it in another application.';}
  else{const response=await fetch(fileURL(e.path));if(!response.ok){const error=await response.json();throw new Error(error.error);}const text=await response.text();if(previewItem===e)box.replaceChildren(sourcePreview(text,ext));}
 }catch(err){if(previewItem===e)box.textContent=err.message+' The original remains available through Download original.';}
}

function openNote(m=null){noteParent=state.selected;noteMessage=m;$('#note-parent').textContent='Connected to '+state.node.title;$('#note-title').value=m?'Note · '+state.node.title:'';$('#note-body').value=m?.content||'';$('#note-body').readOnly=!!m;$('#note-dialog').showModal();}
$('#note-form').onsubmit=async e=>{e.preventDefault();$('#save-note').disabled=true;try{const n=await api('/api/notes',{method:'POST',body:JSON.stringify({node_id:noteParent,title:$('#note-title').value,body:$('#note-body').value,message_id:noteMessage?.id})});state.legacy=await api('/api/graph');renderSaved();$('#note-dialog').close();await selectItem(n.id);toast('Note saved with its connection and conversation reference');}catch(err){toast(err.message);}finally{$('#save-note').disabled=false;}};
function coverage(){const i=state.inventory,c=i.counts;$('#coverage-detail').innerHTML=`<p><strong>${i.complete?'Scan completed without reported errors.':'Scan incomplete — review errors below.'}</strong></p><p class="path">${esc(i.source+'/'+i.scope)}</p><div class="coverage-grid">${Object.entries(c).filter(([k,v])=>typeof v==='number'&&['files','folders','png','pdf','csv','json','symlinks'].includes(k)).map(([k,v])=>`<div><strong>${num(v)}</strong><small>${esc(k.replaceAll('_',' '))}</small></div>`).join('')}</div><p>Every discovered directory and file has a stable identity derived from its exact relative path. Empty directories, backups and hidden files are included. Folders includes the root directory. Symlinks are recorded without traversing targets.</p><p>Views use pagination. Files is an exact inventory; Figures groups same-folder, same-stem exports. All exports remain individually reachable in Files. No folder or file was excluded by an analysis category.</p><p>Scanned: ${esc(new Date(i.scanned_at).toLocaleString())}. Rescan to discover additions and removals. A rescan preserves notes and conversations.</p><p>Discovery does not establish generating code, scientific correctness or historical reproducibility. Analysis descriptions and relationship evidence are stored in general JSON records.</p><div class="section-label">SCAN ERRORS (${i.errors.length})</div><pre>${esc(i.errors.length?JSON.stringify(i.errors,null,2):'None recorded')}</pre>`;$('#coverage-dialog').showModal();}
function populateFilters(){}
let projectRefreshBusy=false;
async function updateProjectSnapshot(snapshot){
 if(!snapshot.inventory||!snapshot.model)return;
 const oldRecords=state.records,oldFocus=state.analysisFocus;
 const ancestry=state.navigation?.lineage(oldFocus)||[];
 ingest(snapshot.inventory);state.model=snapshot.model;
 state.records=new Map(state.model.nodes.map(n=>[n.id,n]));
 if(!state.records.has(state.analysisFocus))state.analysisFocus=ancestry.find(id=>state.records.has(id))||state.model.root_id;
 setupFolderNavigation(state.model);
 if(!state.entries.has(state.scope))state.scope=state.records.get(state.analysisFocus)?.inventory_folder_id||state.inventory.root_id;
 if(state.selected&&!state.records.has(state.selected)&&!state.entries.has(state.selected))state.selected=state.analysisFocus;
 state.preserveGraphView=true;
 try{renderTree();renderBrowser();}finally{state.preserveGraphView=false;}
 if(!$('#inspect-window').hidden&&state.tab==='resources')loadResourcePage();
 const added=state.model.nodes.filter(n=>n.inspectable&&!oldRecords.has(n.id));
 if(added.length)toast(added.length===1?'Analysis added: '+added[0].title:'New analyses added to the graph');
}
async function pollProjectSnapshot(){
 if(document.hidden||projectRefreshBusy||!state.inventory)return;
 projectRefreshBusy=true;
 try{await updateProjectSnapshot(await api('/api/project-snapshot?since='+encodeURIComponent(state.inventory.scanned_at)));}
 catch{/* Keep the current graph during disconnects or source-disk outages. */}
 finally{projectRefreshBusy=false;}
}
$('#rescan').onclick=async()=>{
 const b=$('#rescan');b.disabled=true;b.textContent='Scanning…';
 try{await api('/api/rescan',{method:'POST',body:'{}'});await updateProjectSnapshot(await api('/api/project-snapshot'));toast('Folders refreshed');}
 catch(e){toast(e.message);}finally{b.disabled=false;b.textContent='↻ Refresh';}
};
setInterval(pollProjectSnapshot,3000);
$('#coverage-open').onclick=coverage;$('#about').onclick=()=>$('#about-dialog').showModal();$$('[data-close]').forEach(b=>b.onclick=()=>$('#'+b.dataset.close).close());
$('#files-up').onclick=()=>{const parent=state.entries.get(fileBrowser.folder)?.parent;if(parent){fileBrowser.folder=parent;fileBrowser.page=0;renderNodeFiles();}};
$$('[data-file-filter]').forEach(b=>b.onclick=()=>{fileBrowser.filter=b.dataset.fileFilter;fileBrowser.page=0;renderNodeFiles();});
$('#files-search').oninput=e=>{fileBrowser.query=e.target.value.trim().toLowerCase();fileBrowser.page=0;renderNodeFiles();};
$('#files-recursive').onchange=e=>{fileBrowser.recursive=e.target.checked;fileBrowser.page=0;renderNodeFiles();};
$('#files-prev').onclick=()=>{fileBrowser.page--;renderNodeFiles();$('#files-list').scrollTop=0;};
$('#files-next').onclick=()=>{fileBrowser.page++;renderNodeFiles();$('#files-list').scrollTop=0;};
$('#preview-dialog').addEventListener('keydown',event=>{
 if(event.key==='Escape'){event.preventDefault();event.stopPropagation();$('#preview-dialog').close();return;}
 if(event.altKey||event.ctrlKey||event.metaKey||event.shiftKey||event.isComposing||event.target.closest('input,textarea,select,[contenteditable="true"]'))return;
 const button=event.key==='ArrowLeft'?$('#preview-previous'):event.key==='ArrowRight'?$('#preview-next'):null;
 if(!button)return;event.preventDefault();event.stopPropagation();if(!button.disabled)button.click();
});
$('#preview-previous').setAttribute('aria-keyshortcuts','ArrowLeft');
$('#preview-next').setAttribute('aria-keyshortcuts','ArrowRight');
$('#preview-previous').onclick=()=>{const i=gallery.findIndex(e=>e.id===previewItem.id);if(i>0)showPreview(gallery[i-1]);};$('#preview-next').onclick=()=>{const i=gallery.findIndex(e=>e.id===previewItem.id);if(i>=0&&i<gallery.length-1)showPreview(gallery[i+1]);};
$('#root').onclick=()=>{resetFilters();if(state.view==='graph'&&folderForceGraph){folderForceGraph.overview();return;}selectItem(state.model.nodes[0].id);};$('#up').onclick=()=>{if(state.view==='graph'){selectItem(state.records.get(state.analysisFocus)?.parent_id||state.model.nodes[0].id);return;}const p=state.entries.get(state.scope)?.parent;if(p)openFolder(p);};
$$('[data-view]').forEach(b=>b.onclick=()=>{state.view=b.dataset.view;localStorage.setItem('workspace-view',state.view);state.page=0;renderBrowser();renderTree();revealSelectedFolder();});
$$('.inspector-tabs button').forEach(b=>b.onclick=()=>{state.tab=b.dataset.tab;renderInspector();});
$('#search').oninput=e=>{state.query=e.target.value.trim().toLowerCase();state.page=0;renderBrowser();renderTree();};
for(const [id,prop] of [['filetype','type']])$('#'+id).onchange=e=>{state[prop]=e.target.value;state.page=0;renderBrowser();};
$('#recursive').onchange=()=>{state.page=0;renderBrowser();};$('#clear-filters').onclick=()=>{resetFilters();renderBrowser();};
$('#prev').onclick=()=>{state.page--;renderBrowser();$('#results').scrollTop=0;};$('#next').onclick=()=>{state.page++;renderBrowser();$('#results').scrollTop=0;};
$('#zoom-out').onclick=()=>{if(folderForceGraph){folderForceGraph.zoom(1/1.25);return;}state.zoom=Math.max(.5,state.zoom/1.2);renderMap();};$('#zoom-in').onclick=()=>{if(folderForceGraph){folderForceGraph.zoom(1.25);return;}state.zoom=Math.min(2,state.zoom*1.2);renderMap();};$('#fit').onclick=()=>{if(folderForceGraph){folderForceGraph.fit();return;}state.zoom=1;renderMap();};
$('#new-note').onclick=()=>openNote();$('#chat-form').onsubmit=e=>{e.preventDefault();submitChat($('#chat-input').value);};$('#chat-input').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();submitChat(e.target.value);}};$('#chat-input').oninput=e=>{if(state.selected)sessionStorage.setItem('draft:'+state.selected,e.target.value);};
$$('[data-prompt]').forEach(b=>b.onclick=()=>{$('#chat-input').value=b.dataset.prompt;$('#chat-input').focus();});
function engineNote(){localStorage.setItem('engine',$('#engine').value);$('#engine-note').textContent=$('#engine').value==='codex'?'Uses your CLI account/provider. Selected context and report excerpts are sent for AI replies. Source files stay read-only.':'Deterministic catalogue lookup, entirely local. Choose Codex CLI for open-ended conversation.';}
$('#engine').onchange=engineNote;window.addEventListener('keydown',e=>{if(e.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){e.preventDefault();$('#search').focus();}});window.addEventListener('resize',()=>{if(state.inventory)renderMap();});
$('#focus-chat').onclick=()=>{const focused=$('.inspector').classList.toggle('chat-focused');$('#focus-chat').textContent=focused?'Show details ↙':'Expand ↗';$('#focus-chat').setAttribute('aria-label',focused?'Show item details':'Expand conversation');$('#focus-chat').setAttribute('aria-pressed',String(focused));};
async function boot(){try{state.view=localStorage.getItem('workspace-view')==='files'?'files':'graph';const [i,s,g,m]=await Promise.all([api('/api/inventory'),api('/api/status'),api('/api/graph'),api('/api/analyses')]);state.model=m;state.records=new Map(m.nodes.map(n=>[n.id,n]));state.analysisFocus=state.records.has(localStorage.getItem('analysis-focus'))?localStorage.getItem('analysis-focus'):m.nodes[0].id;if(m.project&&localStorage.getItem('project-navigation-version')!==(m.folder_model?'folder-1':'3')){state.analysisFocus=m.root_id;localStorage.setItem('project-navigation-version',m.folder_model?'folder-1':'3');}if(!i.entries?.length)throw new Error('Inventory unavailable. Mount the source disk and restart with --refresh.');state.token=s.token;state.projectName=s.project_name||'Research project';document.title='Research Map · '+state.projectName;state.legacy=g;ingest(i);setupFolderNavigation(m);await initializeVisibility();populateFilters();$('#source-status').textContent=s.source_available?'Source disk connected':'Source offline · saved inventory';const pref=localStorage.getItem('engine');$('#engine').value=pref==='codex'&&s.codex?'codex':'guide';if(!s.codex)$('#engine option[value="codex"]').disabled=true;engineNote();state.scope=state.entries.has(localStorage.getItem('inventory-scope'))?localStorage.getItem('inventory-scope'):i.root_id;for(const p of chain(state.entries.get(state.scope)))state.expanded.add(p.id);renderSaved();renderTree();renderBrowser();await selectItem(state.analysisFocus,{fromGraph:true});for(let n=0;n<sessionStorage.length;n++){const key=sessionStorage.key(n);if(key.startsWith('pending:')){const id=key.slice(8),job=sessionStorage.getItem(key);state.pending.set(id,job);pollJob(id,job);}}}catch(e){toast(e.message);}}
$('#record-form').onsubmit=async e=>{e.preventDefault();$('#save-record').disabled=true;try{const n=await api('/api/record-update',{method:'POST',body:JSON.stringify({node_id:state.selected,title:$('#record-title').value,description:$('#record-description').value})});state.node=n;const summary=state.model.project?{...state.records.get(n.id),title:n.title,description:n.description}:n.record;state.records.set(n.id,summary);const i=state.model.nodes.findIndex(v=>v.id===n.id);if(i>=0)state.model.nodes[i]=summary;$('#record-dialog').close();renderTree();renderBrowser();renderInspector();toast('Analysis record saved');}catch(err){toast(err.message);}finally{$('#save-record').disabled=false;}};
async function inspectNode(id){
 const record=state.records.get(id);if(!record||record.inspectable===false)return;
 inspectorWindow.open(id);await selectItem(id,{fromGraph:true});
 if(state.selected===id&&inspectorWindow.id===id){renderInspector();inspectorWindow.track();}
}
class InspectorWindow {
 constructor(){
  this.panel=$('#inspect-window');this.connector=$('#inspect-connector');this.id=null;this.frame=0;this.manual=null;
  let saved={};try{saved=JSON.parse(localStorage.getItem('inspect-window-size')||'{}');}catch{}
  this.width=Number.isFinite(saved.width)?saved.width:390;this.height=Number.isFinite(saved.height)?saved.height:540;
  $('#inspect-close').onclick=()=>this.close();
  this.panel.addEventListener('keydown',e=>{if(e.key==='Escape'){e.stopPropagation();this.close();}});
  this.bindMovement($('#inspect-titlebar'),false);this.bindMovement($('#inspect-resize'),true);
  $('#inspect-resize').onkeydown=e=>{const delta={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]}[e.key];if(!delta)return;e.preventDefault();this.width+=delta[0];this.height+=delta[1];this.track();this.saveSize();};
 }
 saveSize(){localStorage.setItem('inspect-window-size',JSON.stringify({width:this.width,height:this.height}));}
 open(id){this.id=id;this.manual=null;this.side=null;this.panel.hidden=true;this.connector.setAttribute('hidden','');}
 close(){this.id=null;this.panel.hidden=true;this.connector.setAttribute('hidden','');cancelAnimationFrame(this.frame);this.frame=0;}
 wake(){if(this.frame||!this.id)return;const tick=()=>{this.frame=0;if(!this.id||this.panel.hidden)return;this.track();if(this.id)this.frame=requestAnimationFrame(tick);};this.frame=requestAnimationFrame(tick);}
 track(){
  if(!this.id||this.panel.hidden)return;
  const node=$('#graph').querySelector('[data-node-id="'+CSS.escape(this.id)+'"] .node-ball');
  if(!node){this.close();return;}
  const graph=$('#graph').getBoundingClientRect(),ball=node.getBoundingClientRect(),nx=ball.left+ball.width/2,ny=ball.top+ball.height/2;
  const w=Math.min(Math.max(280,this.width),innerWidth-24),h=Math.min(Math.max(230,this.height),innerHeight-78);
  this.width=w;this.height=h;
  if(!this.side)this.side=nx+40+w<graph.right?'right':'left';
  const minX=Math.min(graph.left+8,Math.max(12,innerWidth-w-12));
  const clamp=(v,min,max)=>Math.max(min,Math.min(v,max));
  const x=clamp(this.manual?.x??(this.side==='right'?nx+40:nx-w-40),minX,Math.max(minX,innerWidth-w-12));
  const y=clamp(this.manual?.y??ny-65,Math.max(62,graph.top+8),Math.max(62,innerHeight-h-12));
  Object.assign(this.panel.style,{left:x+'px',top:y+'px',width:w+'px',height:h+'px'});
  const px=clamp(nx,graph.left+5,graph.right-5),py=clamp(ny,graph.top+5,graph.bottom-5);
  const endpoints=[{x:x,y:clamp(py,y+18,y+h-18)},{x:x+w,y:clamp(py,y+18,y+h-18)},{x:clamp(px,x+18,x+w-18),y:y},{x:clamp(px,x+18,x+w-18),y:y+h}].sort((a,b)=>Math.hypot(a.x-px,a.y-py)-Math.hypot(b.x-px,b.y-py));
  const end=endpoints[0],inside=px>=x&&px<=x+w&&py>=y&&py<=y+h;
  this.connector.toggleAttribute('hidden',inside);
  this.connector.setAttribute('viewBox',`0 0 ${innerWidth} ${innerHeight}`);
  this.connector.querySelector('path').setAttribute('d',`M ${px} ${py} L ${end.x} ${end.y}`);
  const dot=this.connector.querySelector('circle');dot.setAttribute('cx',px);dot.setAttribute('cy',py);
 }
 bindMovement(handle,resize){
  handle.addEventListener('pointerdown',e=>{
   if(e.button!==0||(!resize&&e.target.closest('button')))return;e.preventDefault();handle.setPointerCapture(e.pointerId);
   const rect=this.panel.getBoundingClientRect(),origin={x:rect.x,y:rect.y,w:rect.width,h:rect.height},x=e.clientX,y=e.clientY;
   const move=event=>{if(resize){this.width=origin.w+event.clientX-x;this.height=origin.h+event.clientY-y;this.manual={x:origin.x,y:origin.y};}else this.manual={x:origin.x+event.clientX-x,y:origin.y+event.clientY-y};this.track();};
   const finish=()=>{handle.removeEventListener('pointermove',move);this.saveSize();};
   handle.addEventListener('pointermove',move);handle.addEventListener('lostpointercapture',finish,{once:true});
  });
 }
}
const inspectorWindow=new InspectorWindow();
class FolderWindow {
 constructor(){
  this.panel=$('#folder-window');let saved={};try{saved=JSON.parse(localStorage.getItem('folder-tree-window-v1')||'{}');}catch{}
  this.rect=saved.rect||{x:0,y:74,w:Math.min(320,innerWidth-24),h:Math.max(300,innerHeight-104)};
  this.visibility=saved.visibility||'hidden';this.maximized=!!saved.maximized;
  $('#folder-close').onclick=()=>this.hide(false);$('#folder-minimize').onclick=()=>this.hide(true);$('#folder-dock').onclick=()=>this.show();
  $('#folder-maximize').onclick=()=>this.maximize(!this.maximized);
  $('#folder-titlebar').ondblclick=e=>{if(!e.target.closest('button'))this.maximize(!this.maximized);};
  this.bindMovement($('#folder-titlebar'),false);this.bindMovement($('#folder-resize'),true);
  $('#folder-resize').onkeydown=e=>{const delta={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]}[e.key];if(!delta||this.maximized)return;e.preventDefault();this.rect.w+=delta[0];this.rect.h+=delta[1];this.layout();this.save();};
  window.addEventListener('resize',()=>{this.layout();this.save();});
 }
 save(){localStorage.setItem('folder-tree-window-v1',JSON.stringify({rect:this.rect,visibility:this.visibility,maximized:this.maximized}));}
 sync(open){if(open)this.visibility='shown';else if(this.visibility==='shown')this.visibility='hidden';this.layout();this.save();}
 show(){this.visibility='shown';state.view='files';localStorage.setItem('workspace-view','files');renderBrowser();renderTree();revealSelectedFolder();}
 hide(minimize){this.visibility=minimize?'minimized':'hidden';state.view='graph';localStorage.setItem('workspace-view','graph');renderBrowser();}
 maximize(value){this.maximized=value;this.layout();this.save();}
 layout(){
  const finite=(v,f)=>Number.isFinite(v)?v:f;
  this.rect.w=Math.min(Math.max(finite(this.rect.w,320),Math.min(240,innerWidth-16)),innerWidth-16);
  this.rect.h=Math.min(Math.max(finite(this.rect.h,600),Math.min(260,innerHeight-62)),innerHeight-62);
  this.rect.x=Math.max(0,Math.min(finite(this.rect.x,0),innerWidth-this.rect.w));
  this.rect.y=Math.max(54,Math.min(finite(this.rect.y,74),Math.max(54,innerHeight-this.rect.h-8)));
  const r=this.maximized?{x:0,y:54,w:innerWidth-8,h:innerHeight-62}:this.rect;
  Object.assign(this.panel.style,{left:r.x+'px',top:r.y+'px',width:r.w+'px',height:r.h+'px'});
  this.panel.hidden=this.visibility!=='shown';this.panel.classList.toggle('maximized',this.maximized);
  $('#folder-dock').hidden=this.visibility!=='minimized';
  const expand=$('#folder-maximize');expand.textContent=this.maximized?'❐':'□';expand.setAttribute('aria-pressed',String(this.maximized));expand.title=this.maximized?'Restore size':'Maximize';expand.setAttribute('aria-label',expand.title+' folders');
  const push=this.panel.hidden||this.maximized?0:Math.max(0,Math.min(innerWidth-160,r.x+r.w));
  document.querySelector('.work-area').style.marginLeft=push+'px';
  layoutPreviewWindow();
 }
 bindMovement(handle,resize){
  handle.addEventListener('pointerdown',e=>{
   if(e.button!==0||this.maximized||(!resize&&e.target.closest('button')))return;
   e.preventDefault();handle.setPointerCapture(e.pointerId);const origin={...this.rect},x=e.clientX,y=e.clientY;
   const move=event=>{this.rect=resize?{...origin,w:origin.w+event.clientX-x,h:origin.h+event.clientY-y}:{...origin,x:origin.x+event.clientX-x,y:origin.y+event.clientY-y};this.layout();};
   const finish=()=>{handle.removeEventListener('pointermove',move);this.save();};
   handle.addEventListener('pointermove',move);handle.addEventListener('lostpointercapture',finish,{once:true});
  });
 }
}
const folderWindow=new FolderWindow();
boot();
