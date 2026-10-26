'use strict';
const assert=require('node:assert/strict');
const {FolderGraphState,terminalObstacleLayout}=require('./force-graph.js');
const nodes=[{id:'root',title:'Sample project',folder_path:''},{id:'collection',parent_id:'root',title:'collection',folder_path:'collection'},{id:'dataset',parent_id:'root',title:'Sample',folder_path:'Sample'},{id:'analysis',parent_id:'collection',title:'growth_analysis',folder_path:'collection/growth_analysis'},{id:'figure',parent_id:'analysis',title:'figures',folder_path:'collection/growth_analysis/figures'}];
const make=()=>new FolderGraphState({root_id:'root',nodes});
{
 const g=make();assert.deepEqual(new Set(g.visible()),new Set(['root','collection','dataset']));
 g.toggle('collection');assert(g.visible().includes('analysis'));assert(g.visible().includes('dataset'),'Siblings remain visible while expanding');
 g.toggle('collection');assert(!g.visible().includes('analysis'));assert(g.visible().includes('collection'),'Second click restores compact branch');
}
{
 const g=make();g.ensurePath('figure',false);assert(g.visible().includes('figure'),'Sidebar selection reveals full ancestry');
 g.required.clear();g.toggle('collection');assert(!g.visible().includes('figure'),'Collapse hides all descendants even when they were open');
 g.toggle('collection');assert(g.visible().includes('figure'),'Reopening restores nested exploration');
}
{
 const g=make();g.toggle('dataset');assert(g.large.has('dataset'));g.toggle('dataset');assert(!g.large.has('dataset'),'Leaf enlargement toggles without inventing children');
 const result=g.search('figures');assert.equal(result.total,1);assert.deepEqual(new Set(result.ids),new Set(['root','collection','analysis','figure']));
}
{
 const many=Array.from({length:80},(_,i)=>({id:'x'+i,parent_id:'root',title:String(i).padStart(3,'0'),folder_path:'p'+i}));
 const g=new FolderGraphState({root_id:'root',nodes:[nodes[0],...many]});assert.equal(g.visible().length,25);g.more('root');assert.equal(g.visible().length,49);
 g.ensurePath('x79',false);assert(g.visible().includes('x79'),'A selected folder outside the first batch is still reachable');
 const restored=new FolderGraphState({root_id:'root',nodes:[nodes[0],...many]},{open:[...g.open]});assert.equal(restored.open.get('root'),48);
}
{
 const g=make();g.ensurePath('analysis',true);g.toggle('analysis');
 const restored=new FolderGraphState({root_id:'root',nodes},{open:[...g.open]});
 restored.ensurePath('analysis',false);
 assert(!restored.open.has('analysis'),'Restoring a selected collapsed folder must not expand it again');
 assert(restored.open.has('collection'),'The selected folder ancestry stays revealed');
 assert(restored.visible().includes('analysis'));
 assert(!restored.visible().includes('figure'));
}
console.log('Graph interaction model: expansion, collapse, context, search, leaf sizing and batching passed.');

{
 const obstacle={left:200,right:700,top:200,bottom:440};
 const points=[{id:'covered',x:450,y:300},{id:'outside',x:70,y:90}];
 const moved=terminalObstacleLayout(points,obstacle,1000,700);
 assert(moved.every(p=>p.y>=468),'Nodes move into available space below the window');
 assert.deepEqual(points[0],{id:'covered',x:450,y:300},'Avoidance never changes saved or pinned positions');
 assert.deepEqual(terminalObstacleLayout(points,null,1000,700),points,'Hiding the terminal restores the original layout');
 const edge=terminalObstacleLayout([{x:100,y:350}],{left:-80,right:500,top:0,bottom:680},1000,700)[0];
 assert(edge.x>528,'A window against the canvas edge moves the graph toward reachable space');
 const triangle=[{x:100,y:100},{x:200,y:100},{x:100,y:200}];
 const shifted=terminalObstacleLayout(triangle,obstacle,1000,700);
 assert(Math.abs((shifted[1].x-shifted[0].x)-(shifted[2].y-shifted[0].y))<1e-8,'The constellation retains its proportions');
 assert.deepEqual(terminalObstacleLayout(points,{left:-100,right:1100,top:-100,bottom:800},1000,700),points,'Maximizing never ejects nodes from the canvas');
 console.log('Terminal avoidance: free space, edge constraints, pinned positions, graph proportions and release passed.');
}

{
 const g=make();g.ensurePath('figure');g.hide('analysis');
 assert(!g.visible().includes('analysis'));assert(!g.visible().includes('figure'),'Hiding a branch hides its descendants');
 assert.equal(g.search('figures').total,0,'Search respects hidden branches');
 assert.deepEqual(g.hiddenChildren('collection'),['analysis']);
 g.showHidden('collection');assert(g.visible().includes('analysis'));assert(g.visible().includes('figure'));
 assert(g.ghost('analysis'));assert(g.ghost('figure'),'Revealed descendants inherit transparency');
 const restored=new FolderGraphState({root_id:'root',nodes},g.snapshot());assert(restored.ghost('analysis'));assert(restored.visible().includes('figure'));
 restored.concealHidden('collection');assert(!restored.visible().includes('analysis'));
 restored.ensurePath('figure',false);assert(restored.visible().includes('figure'),'Selecting via folders can reveal a hidden path without losing the hidden marker');
 restored.unhide('analysis');assert(!restored.ghost('figure'));assert(restored.visible().includes('analysis'));
 restored.hide('root');assert(!restored.hidden.has('root'),'Root remains available for recovery');
 console.log('Node visibility: subtree hiding, parent recovery, faint descendants, persistence, search and unhide passed.');
}

{
 const g=make();
 assert.deepEqual([...g.branchIds('collection')],['collection','analysis','figure'],'Concentration includes the complete descendant branch');
 assert(!g.branchIds('collection').has('dataset'),'Sibling branches stay outside concentration');
 assert.deepEqual([...g.branchIds('dataset')],['dataset'],'Leaf concentration stays local');
 assert.equal(g.branchIds('missing').size,0);
 g.hide('figure');assert(!g.visible().includes('figure'),'Concentration membership does not unhide nodes');
 console.log('Concentration: descendant membership, sibling exclusion, leaf focus and hidden-node preservation passed.');
}
{
 const previous={root_id:'root',nodes},updated={root_id:'root',nodes:[...nodes,{id:'new-analysis',parent_id:'analysis',title:'New analysis'}]};
 const nav=new FolderGraphState(updated);nav.ensurePath('analysis',true);
 const view={model:previous,graph:make(),localFocus:'analysis',camera:{x:21,y:34,k:1.4},resize(){},updateObstacle(){},rebuild(refit){this.didRefit=refit;}};
 globalThis.FolderForceGraph.prototype.update.call(view,updated,'analysis',{navigation:nav,preserveView:true});
 assert.equal(view.localFocus,'analysis');assert.equal(view.didRefit,false);
 assert.deepEqual(view.camera,{x:21,y:34,k:1.4});assert.equal(view.graph,nav);
 console.log('Automatic graph refresh preserves camera and local focus while adopting the new navigation model.');
}
{
 const initial={root_id:'root',nodes:[{id:'root',title:'root'},{id:'leaf',parent_id:'root',title:'leaf'}]};
 const original=new FolderGraphState(initial);original.toggle('leaf');assert(original.large.has('leaf'));
 const after=new FolderGraphState({...initial,nodes:[...initial.nodes,{id:'new',parent_id:'leaf',title:'new analysis'}]},original.snapshot());
 assert(after.open.has('leaf'));assert(after.visible().includes('new'));assert(!after.large.has('leaf'));
 console.log('An enlarged leaf remains expanded when a newly created analysis makes it a parent.');
}
{
 globalThis.cancelAnimationFrame=()=>{};
 const proto=globalThis.FolderForceGraph.prototype;
 const view={graph:make(),camera:{x:21,y:34,k:1.4},concentrated:'collection',localFocus:'analysis',query:'test',selected:'analysis',pins:{analysis:{x:8,y:9}},points:new Map([['analysis',{x:8,y:9,vx:0,vy:0}]]),
  rebuild(){this.active=[];for(const p of this.points.values())p.x+=10;},updateObstacle(){},paint(){},save(){this.saved=true;}};
 proto.setManagerView.call(view,['analysis']);
 assert.deepEqual([...view.managerIds],['analysis']);
 assert.equal(view.managerSnapshot.points.get('analysis').x,8,'Snapshot is isolated from temporary simulation');
 view.graph.open.set('analysis',24);view.camera={x:200,y:300,k:2};view.pins.analysis.x=100;
 proto.endManagerView.call(view);
 assert.deepEqual(view.camera,{x:21,y:34,k:1.4});assert.equal(view.concentrated,'collection');
 assert(!view.graph.open.has('analysis'));assert.equal(view.points.get('analysis').x,8);assert.equal(view.pins.analysis.x,8);
 assert.equal(view.managerIds,null);assert(view.saved);
 console.log('Closing Manager restores camera, concentration, expansion, pins and node positions.');
}

{
 const focus=globalThis.FolderForceGraph.prototype.focus;
 const view={camera:{x:0,y:0,k:.25},width:1200,height:800,graph:{children:new Map()},elements:new Map(),bounds(){return {x:2000,y:-1000,w:190,h:125};},moveCamera(target){this.target=target;}};
 focus.call(view,'leaf',true);
 assert(view.target.k<=.25*1.12,'Clicking a small leaf cannot jump from overview to extreme zoom');
 assert(Math.abs(view.target.x)<=1200*.18);assert(Math.abs(view.target.y)<=800*.18,'Click panning is bounded');
 view.camera={x:10,y:20,k:2};view.bounds=()=>({x:0,y:0,w:5000,h:5000});focus.call(view,'branch',true);
 assert(view.target.k>=2*.85,'Opening a large branch avoids sudden zoom-out');
 console.log('Node clicks limit magnification and camera travel in both directions.');
}
