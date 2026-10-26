'use strict';
class CodexTerminalPane {
 constructor(){
  this.entries=new Map();this.conversationChoice=new Map();this.current=null;this.sequence=0;this.scope=localStorage.getItem('codex-terminal-scope')==='analysis'?'analysis':'project';
  this.host=document.querySelector('#terminal-host');this.panel=document.querySelector('#terminal-panel');
  let saved={};try{saved=JSON.parse(localStorage.getItem('codex-terminal-window-v2')||'{}');}catch{}
  this.visibility=['shown','minimized','hidden'].includes(saved.visibility)?saved.visibility:'hidden';
  const defaultWidth=Math.min(879,innerWidth-48),defaultHeight=Math.min(207,innerHeight-160);
  this.maximized=!!saved.maximized;this.rect=saved.rect||{x:Math.max(8,(innerWidth-defaultWidth)/2),y:Math.max(120,innerHeight-defaultHeight-48),w:defaultWidth,h:defaultHeight};
  document.querySelector('#terminal-scope').onchange=e=>{this.scope=e.target.value;localStorage.setItem('codex-terminal-scope',this.scope);this.select(this.selectedNode,this.token,this.selectedGetMessages);};
  document.querySelector('#terminal-launch').onclick=()=>this.show();
  document.querySelector('#graph-terminal-launch').onclick=()=>this.show();
  document.querySelector('#terminal-dock').onclick=()=>this.show();
  document.querySelector('#terminal-minimize').onclick=()=>this.setVisibility('minimized');
  document.querySelector('#terminal-hide').onclick=()=>this.setVisibility('hidden');
  document.querySelector('#terminal-open').onclick=()=>this.open();
  document.querySelector('#terminal-connect').onclick=()=>this.open();
  document.querySelector('#terminal-menu').onclick=()=>{const menu=document.querySelector('.terminal-toolbar');menu.hidden=!menu.hidden;document.querySelector('#terminal-menu').setAttribute('aria-expanded',String(!menu.hidden));this.fit();};
  document.addEventListener('pointerdown',e=>{if(e.target.closest('#terminal-menu,.terminal-toolbar'))return;document.querySelector('.terminal-toolbar').hidden=true;document.querySelector('#terminal-menu').setAttribute('aria-expanded','false');});
  document.querySelector('#terminal-stop').onclick=()=>this.stop();
  document.querySelector('#terminal-expand').onclick=()=>this.expand(!this.maximized);
  this.bindMovement(document.querySelector('#terminal-titlebar'),false);
  this.bindMovement(document.querySelector('#terminal-resize'),true);
  document.querySelector('#terminal-titlebar').ondblclick=e=>{if(!e.target.closest('button,select,input,option'))this.expand(!this.maximized);};
  document.querySelector('#terminal-resize').onkeydown=e=>{
   const delta={ArrowLeft:[-20,0],ArrowRight:[20,0],ArrowUp:[0,-20],ArrowDown:[0,20]}[e.key];
   if(!delta||this.maximized)return;e.preventDefault();this.rect.w+=delta[0];this.rect.h+=delta[1];this.layout();this.saveWindow();
  };
  window.addEventListener('resize',()=>{this.layout();this.saveWindow();});
  this.layout();
  document.querySelector('#terminal-conversations').onclick=()=>window.researchManager?.show();
  document.querySelector('#terminal-new-conversation').onclick=()=>window.researchManager?.newConversation();
  document.querySelector('#terminal-history').onclick=()=>{
   const box=document.querySelector('#legacy-transcript');box.replaceChildren();
   for(const message of this.getMessages?.()||[]){const p=document.createElement('p'),label=document.createElement('strong');label.textContent=message.role==='user'?'You':'Assistant';p.append(label,document.createTextNode('\n'+message.content));box.append(p);}
   if(!box.childNodes.length)box.textContent='No earlier messages for this analysis.';
   document.querySelector('#legacy-dialog').showModal();
  };
  this.observer=new ResizeObserver(()=>{clearTimeout(this.resizeTimer);this.resizeTimer=setTimeout(()=>this.fit(),100);});this.observer.observe(this.host);
 }
 async post(action,entry,extra={},signal){
  const response=await fetch('/api/terminal/'+action,{method:'POST',headers:{'Content-Type':'application/json','X-Workspace-Token':this.token},body:JSON.stringify({node_id:entry.node_id,terminal_id:entry.terminal_id,conversation_id:entry.conversation_id||this.conversationChoice.get(entry.node_id),...extra}),signal});
  const body=await response.json();if(!response.ok)throw new Error(body.error||'Terminal connection failed');return body;
 }
 select(node,token,getMessages){
  this.selectedNode=node;this.selectedGetMessages=getMessages;this.token=token;
  const analysis=node?.record,valid=!!analysis;
  const project=this.scope==='project'||!valid;
  const scope=document.querySelector('#terminal-scope');scope.querySelector('[value="analysis"]').disabled=!valid;scope.value=project?'project':'analysis';
  const record=project?{id:'project:root',title:(state.projectName||'Project')+' · Project',storage:{folders:[]}}:analysis;
  this.getMessages=project?()=>[]:getMessages;
  document.querySelector('#terminal-empty p').textContent=project?'A project-wide Codex session.':'A real terminal session, kept with this analysis.';
  const id=record.id;if(this.current===id){this.controls();this.layout();return;}
  this.current=id;this.sequence++;const sequence=this.sequence;
  for(const [key,entry] of this.entries)entry.element.hidden=key!==id;
  document.querySelector('#terminal-context').textContent=record.title;
  document.querySelector('#terminal-context').title=record?.storage?.folders?.[0]||'';
  this.layout();
  const entry=this.entries.get(id);this.controls();
  if(entry){this.fit();return;}
  this.post('status',{node_id:id}).then(status=>{if(this.sequence!==sequence)return;this.status=status;if(status.running)this.open(false);else this.controls();}).catch(error=>{if(this.current===id)this.message(error.message,true);});
 }
 message(text,error=false){const box=document.querySelector('#terminal-state');box.textContent=text;box.classList.toggle('terminal-error',error);const indicator=document.querySelector('#terminal-indicator');indicator.title=text;indicator.classList.toggle('terminal-error',error);if(error){document.querySelector('.terminal-toolbar').hidden=false;document.querySelector('#terminal-menu').setAttribute('aria-expanded','true');}}
 controls(){
  const entry=this.entries.get(this.current),running=!!entry?.running;
  document.querySelector('#terminal-empty').hidden=!!entry;
  document.querySelector('#terminal-indicator').classList.toggle('live',running);
  document.querySelector('#terminal-open').hidden=running;
  document.querySelector('#terminal-open').textContent=entry?(entry.disconnected?'Reconnect':'Resume Codex CLI'):this.status?.node_id===this.current&&this.status.started?'Resume Codex CLI':'Open Codex CLI';
  document.querySelector('#terminal-stop').hidden=!running;
  document.querySelector('#terminal-history').hidden=!(this.getMessages?.()||[]).length;
  if(running)this.message('Live session · starts read-only');
  else if(entry)this.message(entry.disconnected?'Connection lost · reconnect to the same session':'Session closed · resume to continue');
  else this.message(this.current==='project:root'?'Your installed CLI · project-wide session':'Your installed CLI · session saved with this analysis');
 }
 saveWindow(){localStorage.setItem('codex-terminal-window-v2',JSON.stringify({rect:this.rect,visibility:this.visibility,maximized:this.maximized}));}
 setVisibility(value){this.visibility=value;this.layout();this.saveWindow();}
 show(){if(!this.current)return;this.setVisibility('shown');requestAnimationFrame(()=>{this.fit();this.entries.get(this.current)?.terminal.focus();});}
 expand(value){this.maximized=value;this.layout();this.saveWindow();requestAnimationFrame(()=>this.fit());}
 layout(){
  const margin=8,vw=innerWidth,vh=innerHeight;
  const number=(value,fallback)=>Number.isFinite(value)?value:fallback;
  this.rect.w=Math.min(Math.max(number(this.rect.w,879),Math.min(420,vw-16)),vw-16);
  this.rect.h=Math.min(Math.max(number(this.rect.h,207),Math.min(180,vh-16)),vh-16);
  this.rect.x=Math.max(margin,Math.min(number(this.rect.x,margin),vw-this.rect.w-margin));
  this.rect.y=Math.max(margin,Math.min(number(this.rect.y,80),vh-this.rect.h-margin));
  const r=this.maximized?{x:margin,y:margin,w:vw-16,h:vh-16}:this.rect;
  Object.assign(this.panel.style,{left:r.x+'px',top:r.y+'px',width:r.w+'px',height:r.h+'px'});
  this.panel.hidden=!this.current||this.visibility!=='shown';
  this.panel.classList.toggle('maximized',this.maximized);
  const expand=document.querySelector('#terminal-expand');expand.textContent=this.maximized?'❐':'□';expand.title=this.maximized?'Restore size':'Maximize';expand.setAttribute('aria-label',expand.title+' terminal');expand.setAttribute('aria-pressed',String(this.maximized));
  const launcher=document.querySelector('#terminal-launch');launcher.disabled=!this.current;launcher.setAttribute('aria-expanded',String(!this.panel.hidden));launcher.title=this.current?'Open conversation for '+document.querySelector('#terminal-context').textContent:'Select an analysis to open its conversation';
  const graphLauncher=document.querySelector('#graph-terminal-launch');graphLauncher.disabled=launcher.disabled;graphLauncher.title=launcher.title;graphLauncher.setAttribute('aria-expanded',String(!this.panel.hidden));
  document.querySelector('#terminal-dock').hidden=!this.current||this.visibility!=='minimized';
  window.dispatchEvent(new Event('terminal-layout'));
 }
 bindMovement(handle,resize){
  handle.addEventListener('pointerdown',e=>{
   if(e.button!==0||this.maximized||(!resize&&e.target.closest('button,select,input,option')))return;
   e.preventDefault();handle.setPointerCapture(e.pointerId);
   const origin={...this.rect},x=e.clientX,y=e.clientY;this.panel.classList.add('is-moving');
   const move=event=>{this.rect=resize?{...origin,w:origin.w+event.clientX-x,h:origin.h+event.clientY-y}:{...origin,x:origin.x+event.clientX-x,y:origin.y+event.clientY-y};this.layout();};
   const finish=()=>{handle.removeEventListener('pointermove',move);handle.removeEventListener('lostpointercapture',finish);this.panel.classList.remove('is-moving');this.saveWindow();this.fit();};
   handle.addEventListener('pointermove',move);handle.addEventListener('lostpointercapture',finish,{once:true});
  });
 }
 create(id){
  const element=document.createElement('div');element.className='terminal-instance';element.setAttribute('role','region');element.setAttribute('aria-label','Codex CLI terminal');this.host.append(element);
  const terminal=new Terminal({cursorBlink:true,convertEol:false,fontFamily:'Menlo, Monaco, Consolas, monospace',fontSize:11,lineHeight:1.25,scrollback:10000,screenReaderMode:true,theme:{background:'#1e1e1e',foreground:'#cccccc',cursor:'#aeafad',selectionBackground:'#264f78',black:'#1e1e1e',brightBlack:'#666666',green:'#0dbc79',brightGreen:'#23d18b',blue:'#2472c8',brightBlue:'#3b8eea',yellow:'#e5e510',brightYellow:'#f5f543',red:'#cd3131',brightRed:'#f14c4c',cyan:'#11a8cd',brightCyan:'#29b8db',white:'#e5e5e5',brightWhite:'#ffffff',magenta:'#bc3fbc',brightMagenta:'#d670d6'}});
  const fit=new FitAddon.FitAddon();terminal.loadAddon(fit);terminal.open(element);
  const entry={node_id:id,element,terminal,fit,cursor:0,running:false,input:'',inputChain:Promise.resolve(),resizeChain:Promise.resolve(),polling:false};
  terminal.onData(data=>{if(!entry.running)return;entry.input+=data;clearTimeout(entry.inputTimer);entry.inputTimer=setTimeout(()=>this.flushInput(entry),8);});
  terminal.onResize(({cols,rows})=>{if(entry.terminal_id&&entry.running)entry.resizeChain=entry.resizeChain.catch(()=>{}).then(()=>this.post('resize',entry,{cols,rows})).catch(error=>{if(this.current===id)this.message(error.message,true);});});
  this.entries.set(id,entry);return entry;
 }
 fit(){const entry=this.entries.get(this.current);if(!entry||!this.host.getBoundingClientRect().width||!this.host.getBoundingClientRect().height||this.panel.hidden)return;try{entry.fit.fit();}catch(error){/* An inactive panel can be between layouts. */}}
 async open(focus=true){
  const id=this.current;if(!id||this.starting===id)return;this.starting=id;const button=document.querySelector('#terminal-open');button.disabled=true;this.message('Connecting to Codex CLI…');
  let entry=this.entries.get(id);
  try{
   if(!entry)entry=this.create(id);
   if(focus)this.show();this.fit();
   const data=await this.post('start',entry,{cols:Math.max(20,entry.terminal.cols),rows:Math.max(5,entry.terminal.rows)});
   if(entry.terminal_id!==data.terminal_id){entry.controller?.abort();if(entry.pollTask)await entry.pollTask;entry.terminal.reset();entry.cursor=0;entry.terminal_id=data.terminal_id;}
   entry.conversation_id=data.conversation_id;this.conversationChoice.set(id,data.conversation_id);entry.running=data.running;entry.disconnected=false;window.researchManager?.refresh();
   if(this.current===id){this.controls();this.fit();if(focus)entry.terminal.focus();}
   entry.pollTask=this.poll(entry);
  }catch(error){if(this.current===id)this.message(error.message,true);}
  finally{if(this.starting===id)this.starting=null;button.disabled=false;}
 }
 flushInput(entry){const data=entry.input;entry.input='';if(!data)return;entry.inputChain=entry.inputChain.catch(()=>{}).then(async()=>{for(let i=0;i<data.length;i+=8000)await this.post('input',entry,{data:data.slice(i,i+8000)});}).catch(error=>{if(this.current===entry.node_id)this.message(error.message,true);});}
 async poll(entry){
  if(entry.polling)return;entry.polling=true;entry.controller=new AbortController();let failures=0;
  try{while(entry.running){
   try{
    const result=await this.post('poll',entry,{cursor:entry.cursor},entry.controller.signal);failures=0;
    if(result.reset)entry.terminal.reset();
    if(result.data){const bytes=Uint8Array.from(atob(result.data),c=>c.charCodeAt(0));await new Promise(resolve=>entry.terminal.write(bytes,resolve));}
    if(result.conversation_id){entry.conversation_id=result.conversation_id;this.conversationChoice.set(entry.node_id,result.conversation_id);}
    entry.cursor=result.cursor;if(!result.running&&!result.more){entry.running=false;if(this.current===entry.node_id)this.controls();break;}
   }catch(error){if(error.name==='AbortError')break;if(++failures>=4){entry.running=false;entry.disconnected=true;if(this.current===entry.node_id){this.controls();this.message(error.message,true);}break;}await new Promise(resolve=>setTimeout(resolve,1000*failures));}
  }}finally{entry.polling=false;}
 }
 async useConversation(conversation){
  const id=conversation.binding;
  this.scope=id==='project:root'?'project':'analysis';localStorage.setItem('codex-terminal-scope',this.scope);
  const node=state.records.get(id)||[...state.records.values()].find(item=>item.stable_node_id===conversation.node_id);
  const selected=node?getLocalNode(node.id):{record:{id,title:conversation.node_id,inspectable:true,storage:{folders:[]}}};
  this.select(id==='project:root'?this.selectedNode:selected,this.token,this.selectedGetMessages);
  this.current=id;this.conversationChoice.set(id,conversation.id);
  for(const [key,item] of this.entries)item.element.hidden=key!==id;
  const entry=this.entries.get(id);
  if(entry){entry.controller?.abort();if(entry.pollTask)await entry.pollTask;entry.running=false;entry.terminal_id=null;entry.cursor=0;entry.conversation_id=conversation.id;entry.terminal.reset();}
  this.show();await this.open();
 }
 async stop(){const entry=this.entries.get(this.current);if(!entry)return;try{await this.post('stop',entry);entry.running=false;entry.controller?.abort();this.controls();}catch(error){this.message(error.message,true);}}
}
window.codexTerminalPane=new CodexTerminalPane();
