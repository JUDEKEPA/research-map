/* Folder membership is independent of layout and inspection. */
(function (global) {
 'use strict';
 class FolderGraphState {
  constructor(model, saved={}) {
   this.root=model.root_id;this.records=new Map(model.nodes.map(n=>[n.id,n]));this.children=new Map();
   for(const n of model.nodes){if(n.parent_id){if(!this.children.has(n.parent_id))this.children.set(n.parent_id,[]);this.children.get(n.parent_id).push(n.id);}}
   for(const a of this.children.values())a.sort((x,y)=>this.records.get(x).title.localeCompare(this.records.get(y).title,undefined,{numeric:true}));
   this.open=new Map((saved.open||[[this.root,24]]).filter(([id])=>this.records.has(id)));
   this.hidden=new Set((saved.hidden||[]).filter(id=>id!==this.root&&this.records.has(id)));
   this.revealed=new Set((saved.revealed||[]).filter(id=>this.hidden.has(id)));
   this.large=new Set((saved.large||[]).filter(id=>this.records.has(id)));
   for(const id of [...this.large])if(this.children.get(id)?.length){this.large.delete(id);if(!this.open.has(id))this.open.set(id,24);}
   this.required=new Set();this.limit=400;
  }
  ensurePath(id,expand=true){
   this.required.clear();let n=this.records.get(id);const seen=new Set();
   while(n&&!seen.has(n.id)){seen.add(n.id);this.required.add(n.id);if(this.hidden.has(n.id))this.revealed.add(n.id);if(n.parent_id&&!this.open.has(n.parent_id))this.open.set(n.parent_id,24);n=this.records.get(n.parent_id);}
   if(expand&&(this.children.get(id)||[]).length&&!this.open.has(id))this.open.set(id,24);
  }
  branchIds(id){const ids=new Set(),visit=key=>{if(ids.has(key)||!this.records.has(key))return;ids.add(key);for(const child of this.children.get(key)||[])visit(child);};visit(id);return ids;}
  snapshot(){return {open:[...this.open],hidden:[...this.hidden],revealed:[...this.revealed],large:[...this.large]};}
  lineage(id){const out=[],seen=new Set();let n=this.records.get(id);while(n&&!seen.has(n.id)){seen.add(n.id);out.push(n.id);n=this.records.get(n.parent_id);}return out;}
  suppressed(id){return this.lineage(id).some(key=>this.hidden.has(key)&&!this.revealed.has(key));}
  ghost(id){return this.lineage(id).some(key=>this.hidden.has(key));}
  hide(id){if(id===this.root||!this.records.has(id))return;this.hidden.add(id);this.revealed.delete(id);}
  unhide(id){this.hidden.delete(id);this.revealed.delete(id);}
  hiddenChildren(id){return (this.children.get(id)||[]).filter(key=>this.hidden.has(key));}
  showHidden(id){const ids=this.hiddenChildren(id);for(const key of ids)this.revealed.add(key);if(ids.length){const all=this.children.get(id)||[];this.open.set(id,Math.max(this.open.get(id)||0,...ids.map(key=>all.indexOf(key)+1)));}}
  concealHidden(id){for(const key of this.hiddenChildren(id))this.revealed.delete(key);}
  toggle(id){if(this.open.has(id)||this.large.has(id)){this.open.delete(id);this.large.delete(id);}else{this.large.add(id);if((this.children.get(id)||[]).length)this.open.set(id,24);}}
  more(id){this.open.set(id,(this.open.get(id)||0)+24);}
  visible(){
   const out=[],seen=new Set(),walk=id=>{if(seen.has(id)||out.length>=this.limit||this.suppressed(id))return;seen.add(id);out.push(id);if(!this.open.has(id))return;
    const all=this.children.get(id)||[],kids=all.filter((k,i)=>i<this.open.get(id)||this.required.has(k));
    kids.sort((a,b)=>Number(this.required.has(b))-Number(this.required.has(a)));for(const k of kids)walk(k);
   };walk(this.root);return out;
  }
  search(query){const matches=[...this.records.values()].filter(n=>!this.suppressed(n.id)&&(n.folder_path+' '+n.title).toLowerCase().includes(query.toLowerCase()));const ids=new Set([this.root]);for(const m of matches.slice(0,60)){let n=m;while(n&&!ids.has(n.id)){ids.add(n.id);n=this.records.get(n.parent_id);}}return {ids:[...ids].slice(0,this.limit),total:matches.length};}
 }
 // Screen-space avoidance preserves the research layout and user-pinned positions.
 function terminalObstacleLayout(points,obstacle,width,height){
  if(!obstacle)return points.map(p=>({...p}));
  // Keep the constellation's shape in the largest free region instead of piling nodes along an edge.
  const gap=28,left=Math.max(0,obstacle.left-gap),right=Math.min(width,obstacle.right+gap),top=Math.max(0,obstacle.top-gap),bottom=Math.min(height,obstacle.bottom+gap);
  const spaces=[{x:0,y:0,w:width,h:top},{x:0,y:bottom,w:width,h:height-bottom},{x:0,y:0,w:left,h:height},{x:right,y:0,w:width-right,h:height}]
   .filter(r=>r.w>=140&&r.h>=100).sort((a,b)=>b.w*b.h-a.w*a.h);
  if(!spaces.length)return points.map(p=>({...p}));
  const r=spaces[0],scale=Math.min(r.w/width,r.h/height),cx=r.x+r.w/2,cy=r.y+r.h/2;
  return points.map(p=>({...p,x:cx+(p.x-width/2)*scale,y:cy+(p.y-height/2)*scale}));
 }
 global.FolderGraphState=FolderGraphState;
 if(typeof module!=='undefined'&&module.exports)module.exports={FolderGraphState,terminalObstacleLayout};
 const NS='http://www.w3.org/2000/svg';
 function el(name,attrs,text){const n=document.createElementNS(NS,name);for(const [k,v] of Object.entries(attrs||{}))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;return n;}
 class FolderForceGraph {
  constructor({svg,panel,onSelect,tooltip,onStatus,onExpansionChange=()=>{}}){
   Object.assign(this,{svg,panel,onSelect,tooltip,onStatus,onExpansionChange});this.points=new Map();this.camera={x:0,y:0,k:1};this.width=800;this.height=500;this.frame=0;this.query='';this.selected=null;this.pins={};
   try{this.saved=JSON.parse(localStorage.getItem('folder-force-map-v1')||'{}');this.pins=this.saved.pins||{};this.concentrated=this.saved.concentrated||null;}catch(e){this.saved={};}
   this.svg.classList.add('force-canvas');this.panel.classList.add('force-panel');this.svg.setAttribute('aria-label','Interactive folder graph');this.svg.setAttribute('tabindex','0');
   this.svg.innerHTML='<defs><radialGradient id="folder-ball" cx="32%" cy="25%"><stop offset="0" stop-color="#dedede"/><stop offset="0.48" stop-color="#9a9a9a"/><stop offset="1" stop-color="#555555"/></radialGradient><radialGradient id="folder-nav" cx="30%" cy="25%"><stop offset="0" stop-color="#777777"/><stop offset="1" stop-color="#383838"/></radialGradient></defs>';
   this.world=el('g',{class:'force-world'});this.edgeLayer=el('g',{class:'force-links'});this.nodeLayer=el('g',{class:'force-nodes'});this.world.append(this.edgeLayer,this.nodeLayer);this.svg.append(this.world);
   this.svg.addEventListener('pointerdown',e=>this.pointerDown(e));this.svg.addEventListener('pointermove',e=>this.pointerMove(e));this.svg.addEventListener('pointerup',e=>this.pointerUp(e));this.svg.addEventListener('pointercancel',()=>{this.drag=null;this.svg.classList.remove('is-dragging');});
   this.svg.addEventListener('wheel',e=>{e.preventDefault();const r=this.svg.getBoundingClientRect();this.zoom(Math.exp(-e.deltaY*.0015),e.clientX-r.left,e.clientY-r.top);},{passive:false});
   this.svg.addEventListener('keydown',e=>{if(e.target!==this.svg)return;if(e.key==='Home'||e.key==='Escape'){e.preventDefault();this.fit();}if(['+','=','-'].includes(e.key)){e.preventDefault();this.zoom(e.key==='-'?.82:1.22);}const moves={ArrowLeft:[35,0],ArrowRight:[-35,0],ArrowUp:[0,35],ArrowDown:[0,-35]};if(moves[e.key]){e.preventDefault();this.camera.x+=moves[e.key][0];this.camera.y+=moves[e.key][1];this.paint();this.wake();}});
   window.addEventListener('manager-layout',()=>this.updateObstacle());
   this.observer=new ResizeObserver(()=>{this.resize();this.updateObstacle();});this.observer.observe(panel);
   this.moreButton=document.getElementById('graph-more');this.moreButton.onclick=()=>{this.graph.more(this.menuNode||this.selected);this.rebuild(true);this.save();};
   document.getElementById('graph-reset').onclick=()=>this.resetLayout();
   this.setupMenu();
   document.getElementById('graph-inspect').onclick=()=>global.inspectNode?.(this.menuNode);
   document.getElementById('graph-conversations').onclick=()=>global.researchManager?.showNode(this.menuNode);
   document.getElementById('graph-copy-path').onclick=()=>this.copyNodePath();
   document.getElementById('graph-concentrate').onclick=()=>this.concentrate(this.menuNode);
   document.getElementById('graph-clear-concentration').onclick=()=>this.concentrate(null);
   document.getElementById('graph-hide-node').onclick=()=>this.changeVisibility('hide');
   document.getElementById('graph-unhide-node').onclick=()=>this.changeVisibility('unhide');
   document.getElementById('graph-show-hidden').onclick=()=>this.changeVisibility('show');
   document.getElementById('graph-conceal-hidden').onclick=()=>this.changeVisibility('conceal');
  }
  setupMenu(){
   this.menu=document.getElementById('graph-menu');
   this.closeMenu=(restore=false)=>{if(this.menu.hidden)return;this.menu.hidden=true;if(restore)this.menuAnchor?.focus();};
   const show=(x,y,target)=>{
    if(!this.graph)return;
    document.getElementById('node-tooltip').hidden=true;
    this.menuAnchor=target?.closest('[data-node-id]')||this.svg;
    this.menuNode=this.menuAnchor.dataset.nodeId||this.selected;
    document.getElementById('graph-menu-context').textContent=this.graph.records.get(this.menuNode)?.title||'Graph';
    this.updateMore(this.menuNode);
    const nodeMenu=this.menuAnchor!==this.svg,hiddenKids=this.graph.hiddenChildren(this.menuNode);
    document.getElementById('graph-inspect').hidden=!nodeMenu||this.graph.records.get(this.menuNode)?.inspectable===false;
    document.getElementById('graph-conversations').hidden=!nodeMenu;
    document.getElementById('graph-copy-path').hidden=!nodeMenu||!this.nodePath(this.menuNode);
    document.getElementById('graph-concentrate').hidden=!nodeMenu;
    document.getElementById('graph-clear-concentration').hidden=!this.concentrated;
    document.getElementById('graph-hide-node').hidden=!nodeMenu||this.menuNode===this.graph.root;
    document.getElementById('graph-unhide-node').hidden=!nodeMenu||!this.graph.hidden.has(this.menuNode);
    document.getElementById('graph-show-hidden').hidden=!nodeMenu||!hiddenKids.some(key=>!this.graph.revealed.has(key));
    document.getElementById('graph-conceal-hidden').hidden=!nodeMenu||!hiddenKids.some(key=>this.graph.revealed.has(key));
    this.menu.hidden=false;
    const r=this.menu.getBoundingClientRect();
    this.menu.style.left=Math.max(8,Math.min(x,innerWidth-r.width-8))+'px';
    this.menu.style.top=Math.max(8,Math.min(y,innerHeight-r.height-8))+'px';
    this.menu.querySelector('button:not([hidden]):not(:disabled)')?.focus();
   };
   const openMenu=e=>{e.preventDefault();show(e.clientX,e.clientY,e.target);};
   this.panel.closest('.browser-pane').addEventListener('contextmenu',openMenu);
   document.querySelector('.navigation-strip').addEventListener('contextmenu',openMenu);
   this.panel.addEventListener('keydown',e=>{
    if(e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10')){e.preventDefault();e.stopPropagation();const r=e.target.getBoundingClientRect();show(r.left+r.width/2,r.top+Math.min(r.height,40),e.target);}
   });
   this.menu.addEventListener('keydown',e=>{
    const buttons=[...this.menu.querySelectorAll('button:not([hidden]):not(:disabled)')],index=buttons.indexOf(document.activeElement);
    if(e.key==='Escape'){e.preventDefault();e.stopPropagation();this.closeMenu(true);return;}
    if(e.key==='Tab'){this.closeMenu();return;}
    if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();buttons[e.key==='Home'?0:e.key==='End'?buttons.length-1:(index+(e.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus();}
   });
   this.menu.addEventListener('click',e=>{if(e.target.closest('button'))this.closeMenu(true);});
   document.addEventListener('pointerdown',e=>{if(!this.menu.contains(e.target))this.closeMenu();});
   this.panel.addEventListener('wheel',()=>this.closeMenu(),{passive:true});
   window.addEventListener('resize',()=>this.closeMenu());
  }
  nodePath(id){return this.graph.records.get(id)?.storage?.folders?.[0]||'';}
  async copyNodePath(){
   const path=this.nodePath(this.menuNode);if(!path)return;
   try{
    try{await navigator.clipboard.writeText(path);}
    catch(error){
     const field=document.createElement('textarea');field.value=path;field.setAttribute('aria-label','Node path');Object.assign(field.style,{position:'fixed',left:'-9999px',top:'0'});document.body.append(field);
     try{field.select();if(!document.execCommand('copy'))throw error;}finally{field.remove();}
    }
    if(typeof global.toast==='function')global.toast('Node path copied');
   }catch(error){if(typeof global.toast==='function')global.toast('Could not copy the node path. Please allow clipboard access and try again.');}
  }
  concentrate(id){
   this.concentrated=id;this.query='';
   if(id){this.graph.ensurePath(id,false);this.graph.large.add(id);if((this.graph.children.get(id)||[]).length)this.graph.open.set(id,Math.max(24,this.graph.open.get(id)||0));this.selected=id;this.localFocus=id;}
   this.rebuild(false);this.save();
   if(id){this.focusConcentration();this.onSelect(id);}else this.fit();
  }
  focusConcentration(animate=true){
   if(!this.concentrated)return;
   const branch=this.graph.branchIds(this.concentrated),ids=this.active.filter(n=>branch.has(n.id)).map(n=>n.id);
   if(!ids.length)return;
   const b=this.bounds(ids),k=Math.max(.3,Math.min(1.8,(this.width-140)/b.w,(this.height-120)/b.h));
   this.moveCamera({x:-b.x*k,y:-b.y*k,k},animate);
  }
  changeVisibility(action){
   const id=this.menuNode,parent=this.graph.records.get(id)?.parent_id||this.graph.root;
   if(action==='hide')this.graph.hide(id);
   if(action==='unhide')this.graph.unhide(id);
   if(action==='show')this.graph.showHidden(id);
   if(action==='conceal')this.graph.concealHidden(id);
   const selectionHidden=this.graph.suppressed(this.selected);
   if(selectionHidden)this.selected=action==='hide'?parent:id;
   if(this.concentrated&&this.graph.suppressed(this.concentrated))this.concentrated=null;
   this.localFocus=action==='hide'?parent:id;
   this.rebuild(false);this.save();this.focus(this.localFocus,true);
   if(selectionHidden)this.onSelect(this.selected);
  }
  updateMore(id){
   const total=(this.graph.children.get(id)||[]).length,count=this.graph.open.get(id)||0;
   this.moreButton.hidden=total<=count||!!this.query;
   this.moreButton.disabled=this.active?.length>=this.graph.limit;
   this.moreButton.textContent='Show more children';
  }
  setManagerView(ids){
   if(!this.graph)return;
   if(!this.managerSnapshot){
    cancelAnimationFrame(this.cameraFrame);
    this.managerSnapshot={camera:{...this.camera},concentrated:this.concentrated,localFocus:this.localFocus,query:this.query,selected:this.selected,navigation:this.graph.snapshot(),required:[...this.graph.required],pins:structuredClone(this.pins),points:new Map([...this.points].map(([id,p])=>[id,{...p}]))};
   }
   const signature=JSON.stringify([...ids].sort());
   if(this.managerSignature===signature){this.updateObstacle();return;}
   this.managerSignature=signature;this.managerIds=new Set(ids.filter(id=>this.graph.records.has(id)));
   this.rebuild(false);this.updateObstacle();
   const visible=this.active.filter(n=>this.managerIds.has(n.id)).map(n=>n.id);
   if(visible.length){const b=this.bounds(visible),k=Math.max(.3,Math.min(1.8,(this.width-140)/b.w,(this.height-120)/b.h));this.moveCamera({x:-b.x*k,y:-b.y*k,k});}
  }
  endManagerView(){
   const saved=this.managerSnapshot;if(!saved)return;
   cancelAnimationFrame(this.cameraFrame);cancelAnimationFrame(this.frame);this.frame=0;
   this.managerSnapshot=null;this.managerIds=null;this.managerSignature=null;
   Object.assign(this,{camera:saved.camera,concentrated:saved.concentrated,localFocus:saved.localFocus,query:saved.query,selected:saved.selected,pins:saved.pins});
   this.graph.open=new Map(saved.navigation.open);this.graph.large=new Set(saved.navigation.large);this.graph.required=new Set(saved.required);
   this.points=new Map([...saved.points].map(([id,p])=>[id,{...p}]));this.updateObstacle();this.rebuild(false);
   cancelAnimationFrame(this.frame);this.frame=0;
   // Rebuilding updates styles; restoring the captured coordinates preserves the prior view.
   for(const [id,p] of saved.points)this.points.set(id,{...p,avoidX:0,avoidY:0});
   this.camera={...saved.camera};this.paint();this.save();
  }
  updateObstacle(){
   const manager=document.getElementById('research-window'),r=this.svg.getBoundingClientRect();
   let next=null;
   if(manager&&!manager.hidden&&this.managerSnapshot&&r.width&&r.height&&!this.panel.hidden){
    const t=manager.getBoundingClientRect();
    if(t.right>r.left&&t.left<r.right&&t.bottom>r.top&&t.top<r.bottom)next={left:t.left-r.left,right:t.right-r.left,top:t.top-r.top,bottom:t.bottom-r.top};
   }
   if(JSON.stringify(next)===JSON.stringify(this.obstacle))return;
   this.obstacle=next;if(this.active)this.wake();
  }
  avoidTerminal(){
   if(!this.active)return;
   const c=this.camera,screen=this.active.map(n=>{const p=this.points.get(n.id);return {id:n.id,x:this.width/2+c.x+p.x*c.k,y:this.height/2+c.y+p.y*c.k};});
   const targets=terminalObstacleLayout(screen,this.obstacle,this.width,this.height);
   const basis=terminalObstacleLayout([{x:0,y:0},{x:1,y:0}],this.obstacle,this.width,this.height);this.avoidScale=basis[1].x-basis[0].x;
   for(let i=0;i<screen.length;i++){
    const p=this.points.get(screen[i].id),dx=(targets[i].x-screen[i].x)/c.k,dy=(targets[i].y-screen[i].y)/c.k;
    const ease=this.drag?.id===screen[i].id||matchMedia('(prefers-reduced-motion: reduce)').matches?1:.2;
    p.avoidX=(p.avoidX||0)+(dx-(p.avoidX||0))*ease;p.avoidY=(p.avoidY||0)+(dy-(p.avoidY||0))*ease;
    p.drawX=p.x+p.avoidX;p.drawY=p.y+p.avoidY;
   }
  }
  update(model,selected,{external=false,query='',navigation=null,preserveView=false}={}){
   const changed=this.model!==model;if(changed){this.model=model;this.graph=navigation||new FolderGraphState(model,this.saved);}
   this.selected=selected;this.query=query;
   if(this.concentrated&&(!this.graph.records.has(this.concentrated)||this.graph.suppressed(this.concentrated)))this.concentrated=null;
   if(external||(changed&&!preserveView)){this.localFocus=null;if(!navigation)this.graph.ensurePath(selected,!(changed&&this.saved.open));}
   this.resize(false);this.updateObstacle();this.rebuild(external||(changed&&!preserveView));
  }
  resize(refit=true){if(this.panel.hidden)return;const r=this.svg.getBoundingClientRect();if(!r.width||!r.height)return;const changed=this.width!==r.width||this.height!==r.height;this.width=r.width;this.height=r.height;this.svg.setAttribute('viewBox',`0 0 ${this.width} ${this.height}`);if(refit&&changed&&this.active){if(this.concentrated)this.focusConcentration(false);else if(this.localFocus)this.focus(this.localFocus,true);else this.fit(false);}}
  save(){const data={...this.graph.snapshot(),pins:this.pins,concentrated:this.concentrated};try{localStorage.setItem('folder-force-map-v1',JSON.stringify(data));}catch(e){}this.saved=data;this.onExpansionChange();}
  activate(id){
   const willOpen=!this.graph.open.has(id)&&!this.graph.large.has(id);
   const focusId=willOpen?id:(this.graph.records.get(id)?.parent_id||this.graph.root);
   this.graph.toggle(id);this.graph.required.clear();this.query='';this.selected=id;this.localFocus=focusId;
   this.save();this.rebuild(false);this.focus(focusId,true);this.onSelect(id);
  }
  rebuild(refit=false){
   if(!this.graph)return;const result=this.query&&!this.managerIds?this.graph.search(this.query):{ids:this.graph.visible()};if(this.managerIds){const paths=[...this.managerIds].flatMap(id=>this.graph.suppressed(id)?[]:this.graph.lineage(id));result.ids=[...new Set([...paths,...result.ids])].slice(0,this.graph.limit);}this.active=result.ids.map(id=>this.graph.records.get(id));const concentrated=this.managerIds||(this.concentrated?this.graph.branchIds(this.concentrated):null);const visible=new Set(result.ids);this.links=[];
   this.edgeLayer.replaceChildren();this.nodeLayer.replaceChildren();this.elements=new Map();
   for(let i=0;i<this.active.length;i++){
    const n=this.active[i];if(!this.points.has(n.id)){
     const parent=this.points.get(n.parent_id),angle=i*2.399963,rad=parent?80+((i%5)*9):0;
     this.points.set(n.id,{x:(parent?.x||0)+Math.cos(angle)*rad,y:(parent?.y||0)+Math.sin(angle)*rad,vx:0,vy:0,...(this.pins[n.id]||{})});
    }
    const open=this.graph.open.has(n.id)||this.graph.large.has(n.id),selected=n.id===this.selected,has=(this.graph.children.get(n.id)||[]).length;
    const p=this.points.get(n.id);p.radius=concentrated?(concentrated.has(n.id)?(this.managerIds?14:n.id===this.concentrated?20:12):3):(open?12:n.id===this.graph.root?10:n.inspectable?7:6);p.open=open;
    const g=el('g',{class:`force-node ${n.inspectable?'is-analysis':'is-folder'} ${open?'is-open':''} ${selected?'is-selected':''} ${this.graph.ghost(n.id)?'is-ghost':''} ${concentrated?(concentrated.has(n.id)?'is-concentrated':'is-muted'):''}`,role:'button',tabindex:0,'data-node-id':n.id,'aria-label':n.title,'aria-description':concentrated&&!concentrated.has(n.id)?(this.managerIds?'No registered conversation':'Outside concentrated branch'):this.graph.ghost(n.id)?'Hidden node, temporarily shown at reduced opacity':'','aria-pressed':String(open),'aria-expanded':has?String(open):'false'});
    g.append(el('circle',{r:23,class:'node-hit'}),el('circle',{r:p.radius+7,class:'node-halo'}),el('circle',{r:p.radius,class:'node-ball'}));
    const title=n.title.length>28?n.title.slice(0,26)+'…':n.title;g.append(el('text',{y:p.radius+19,'text-anchor':'middle',class:'node-name'},title));
    g.append(el('title',{},n.title+'\n'+(n.inspectable?'Analysis folder':'Navigation folder')+' · '+(has?`click to ${open?'collapse':'expand'}`:'click to enlarge / restore')));
    g.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();this.activate(n.id);document.querySelector(`[data-node-id="${n.id}"]`)?.focus();}if(e.key==='Escape'){e.preventDefault();this.fit();}});
    g.addEventListener('click',e=>{if(e.detail===0)this.activate(n.id);});
    this.tooltip(g,n);this.nodeLayer.append(g);this.elements.set(n.id,g);
    if(n.parent_id&&visible.has(n.parent_id)){const line=el('line',{class:'force-link'+(selected?' is-selected':'')+(this.graph.ghost(n.id)||this.graph.ghost(n.parent_id)?' is-ghost':'')+(concentrated?(concentrated.has(n.id)&&concentrated.has(n.parent_id)?' is-concentrated':' is-muted'):'')});this.edgeLayer.append(line);this.links.push({a:n.parent_id,b:n.id,line});}
   }
   for(let i=0;i<(refit?90:12);i++)this.step();this.paint();if(refit){if(this.concentrated)this.focusConcentration(false);else this.fit(false);}this.wake();
   this.updateMore(this.selected);
   this.onStatus({visible:this.active.length,branches:this.active.filter(n=>this.graph.open.has(n.id)).length,matches:result.total,limited:this.active.length>=this.graph.limit});
  }
  step(){
   const ids=this.active.map(n=>n.id),points=ids.map(id=>this.points.get(id));
   for(let i=0;i<points.length;i++)for(let j=i+1;j<points.length;j++){
    const a=points[i],b=points[j];let dx=a.x-b.x,dy=a.y-b.y;if(Math.abs(dx)+Math.abs(dy)<.01){dx=.1;dy=.1;}
    const d2=dx*dx+dy*dy,d=Math.sqrt(d2),force=Math.min(3,2600/(d2+150)),fx=dx/d*force,fy=dy/d*force;a.vx+=fx;a.vy+=fy;b.vx-=fx;b.vy-=fy;
    // Reserve horizontal space for short labels, not only the node circles.
    if(Math.abs(dx)<118&&Math.abs(dy)<42){const push=(1-Math.abs(dx)/118)*(1-Math.abs(dy)/42)*1.6;a.vy+=Math.sign(dy||1)*push;b.vy-=Math.sign(dy||1)*push;}
   }
   for(const e of this.links){const a=this.points.get(e.a),b=this.points.get(e.b),dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy)||1,rest=a.open?112:88,f=(d-rest)*.009;a.vx+=dx/d*f;a.vy+=dy/d*f;b.vx-=dx/d*f;b.vy-=dy/d*f;}
   for(let i=0;i<points.length;i++){const p=points[i],id=ids[i];if(this.pins[id]||(this.drag?.id===id)){p.vx=0;p.vy=0;continue;}p.vx=(p.vx-p.x*.0007)*.82;p.vy=(p.vy-p.y*.0007)*.82;p.x+=p.vx;p.y+=p.vy;}
  }
  paint(){this.avoidTerminal();for(const n of this.active){const p=this.points.get(n.id);this.elements.get(n.id).setAttribute('transform',`translate(${p.drawX},${p.drawY})`);}for(const e of this.links){const a=this.points.get(e.a),b=this.points.get(e.b);for(const [k,v] of Object.entries({x1:a.drawX,y1:a.drawY,x2:b.drawX,y2:b.drawY}))e.line.setAttribute(k,v);}this.applyCamera();}
  wake(){if(matchMedia('(prefers-reduced-motion: reduce)').matches){for(let i=0;i<80;i++)this.step();this.paint();return;}this.until=performance.now()+2800;if(this.frame)return;const tick=()=>{this.frame=0;if(this.panel.hidden)return;this.step();this.paint();if(performance.now()<this.until)this.frame=requestAnimationFrame(tick);};this.frame=requestAnimationFrame(tick);}
  applyCamera(){const c=this.camera;this.world.setAttribute('transform',`translate(${this.width/2+c.x},${this.height/2+c.y}) scale(${c.k})`);document.getElementById('graph-zoom').textContent=Math.round(c.k*100)+'%';}
  bounds(ids){const ps=ids.map(id=>this.points.get(id)).filter(Boolean);if(!ps.length)return {x:0,y:0,w:300,h:250};const xs=ps.map(p=>p.x),ys=ps.map(p=>p.y);return {x:(Math.min(...xs)+Math.max(...xs))/2,y:(Math.min(...ys)+Math.max(...ys))/2,w:Math.max(...xs)-Math.min(...xs)+190,h:Math.max(...ys)-Math.min(...ys)+125};}
  moveCamera(target,animate=true){cancelAnimationFrame(this.cameraFrame);if(!animate||matchMedia('(prefers-reduced-motion: reduce)').matches){this.camera=target;this.paint();this.wake();return;}const from={...this.camera},start=performance.now();const tick=now=>{const t=Math.min(1,(now-start)/600),q=(1-Math.cos(Math.PI*t))/2;for(const k of ['x','y','k'])this.camera[k]=from[k]+(target[k]-from[k])*q;this.paint();if(t<1)this.cameraFrame=requestAnimationFrame(tick);else this.wake();};this.cameraFrame=requestAnimationFrame(tick);}
  fit(animate=true){this.localFocus=null;if(!this.active)return;const b=this.bounds(this.active.map(n=>n.id)),k=Math.max(.18,Math.min(1.3,(this.width-70)/b.w,(this.height-100)/b.h));this.moveCamera({x:-b.x*k,y:-b.y*k,k},animate);}
  focus(id,enlarge){
   if(!enlarge){this.fit();return;}
   const ids=[id,...(this.graph.children.get(id)||[]).filter(k=>this.elements.has(k))],b=this.bounds(ids),c=this.camera;
   // Routine exploration keeps context: no abrupt fit-to-branch magnification.
   // Explicit Fit and manual zoom remain available for larger view changes.
   const desired=Math.max(.15,Math.min(1,(this.width-120)/b.w,(this.height-100)/b.h));
   const k=Math.max(c.k*.85,Math.min(c.k*1.12,desired));
   const limit=(value,current,span)=>current+Math.max(-span*.18,Math.min(span*.18,value-current));
   this.moveCamera({x:limit(-b.x*k,c.x,this.width),y:limit(-b.y*k,c.y,this.height),k});
  }
  zoom(factor,x=this.width/2,y=this.height/2){cancelAnimationFrame(this.cameraFrame);const basis=terminalObstacleLayout([{x:0,y:0},{x:1,y:0}],this.obstacle,this.width,this.height),s=basis[1].x-basis[0].x;x=(x-basis[0].x)/s;y=(y-basis[0].y)/s;const c=this.camera,k=Math.max(.15,Math.min(3,c.k*factor)),ratio=k/c.k;c.x=(x-this.width/2)-(x-this.width/2-c.x)*ratio;c.y=(y-this.height/2)-(y-this.height/2-c.y)*ratio;c.k=k;this.paint();this.wake();}
  pointerDown(e){if(e.button!==0)return;cancelAnimationFrame(this.cameraFrame);document.getElementById('node-tooltip').hidden=true;const target=e.target.closest('[data-node-id]'),id=target?.dataset.nodeId;this.drag={id,x:e.clientX,y:e.clientY,lastX:e.clientX,lastY:e.clientY,moved:false};this.svg.setPointerCapture(e.pointerId);this.svg.classList.add('is-dragging');}
  pointerMove(e){if(!this.drag)return;document.getElementById('node-tooltip').hidden=true;const d=this.drag,dx=e.clientX-d.lastX,dy=e.clientY-d.lastY;if(Math.hypot(e.clientX-d.x,e.clientY-d.y)>5)d.moved=true;if(d.moved){if(d.id){const p=this.points.get(d.id);p.x+=dx/(this.camera.k*(this.avoidScale||1));p.y+=dy/(this.camera.k*(this.avoidScale||1));this.pins[d.id]={x:p.x,y:p.y};this.wake();}else{this.camera.x+=dx/(this.avoidScale||1);this.camera.y+=dy/(this.avoidScale||1);}this.paint();}d.lastX=e.clientX;d.lastY=e.clientY;}
  pointerUp(e){if(!this.drag)return;const d=this.drag;this.drag=null;this.svg.classList.remove('is-dragging');if(this.svg.hasPointerCapture(e.pointerId))this.svg.releasePointerCapture(e.pointerId);if(d.moved){this.save();this.wake();}else if(d.id)this.activate(d.id);}
  overview(){this.concentrated=null;this.graph.open=new Map([[this.graph.root,24]]);this.graph.large.clear();this.graph.required.clear();this.query='';this.selected=this.graph.root;this.localFocus=null;this.rebuild(true);this.save();this.onSelect(this.graph.root);}
  resetLayout(){this.pins={};this.points.clear();this.rebuild(true);this.save();}
 }
 global.FolderForceGraph=FolderForceGraph;
 if(typeof module!=='undefined'&&module.exports)module.exports.FolderForceGraph=FolderForceGraph;
})(typeof window!=='undefined'?window:globalThis);
