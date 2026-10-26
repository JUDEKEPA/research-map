'use strict';
class ResearchManagerPane {
 constructor(){
  this.panel=document.querySelector('#research-window');this.data=null;this.request=0;this.setupWindow();
  document.querySelector('#research-manager-launch').onclick=()=>this.panel.hidden?this.show():this.close();
  document.querySelector('#research-close').onclick=()=>{this.close();};
  this.menu=document.querySelector('#conversation-menu');this.titleTooltip=document.querySelector('#conversation-title-tooltip');
  document.querySelector('#conversation-continue').onclick=()=>{const cid=this.menuConversation;this.closeMenu();this.continueConversation(cid);};
  document.querySelector('#conversation-recover').onclick=()=>{const cid=this.menuConversation;this.closeMenu();this.recover(cid);};
  document.querySelector('#conversation-delete').onclick=async()=>{
   const cid=this.menuConversation;this.hideTitle();this.closeMenu();
   try{await this.post({action:'delete_conversation',conversation_id:cid});localStorage.setItem('conversation-last-deleted',cid);document.querySelector('#conversation-undo').hidden=false;await this.refresh();}catch(error){toast(error.message);}
  };
  document.querySelector('#conversation-undo').hidden=!localStorage.getItem('conversation-last-deleted');
  document.querySelector('#conversation-restore').onclick=async()=>{
   const cid=localStorage.getItem('conversation-last-deleted');if(!cid)return;
   try{await this.post({action:'restore_conversation',conversation_id:cid});localStorage.removeItem('conversation-last-deleted');document.querySelector('#conversation-undo').hidden=true;await this.refresh();}catch(error){toast(error.message);}
  };
  document.addEventListener('pointerdown',event=>{if(!this.menu.contains(event.target))this.closeMenu();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!this.menu.hidden){event.preventDefault();this.closeMenu(true);}});
  this.menu.onkeydown=event=>{
   if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
    event.preventDefault();const items=[...this.menu.querySelectorAll('button')],current=items.indexOf(document.activeElement);
    const index=event.key==='Home'?0:event.key==='End'?items.length-1:(current+(event.key==='ArrowDown'?1:-1)+items.length)%items.length;items[index].focus();
   }
  };
  window.addEventListener('resize',()=>{this.closeMenu();this.hideTitle();});
  document.querySelector('#research-content').addEventListener('scroll',()=>{this.closeMenu();this.hideTitle();});
  document.querySelector('#research-refresh').onclick=()=>this.refresh();
  document.querySelector('#research-import').onclick=async()=>{try{const result=await this.post({action:'import'});toast('Imported '+result.count+' previous app sessions');this.refresh();}catch(e){toast(e.message);}};
  document.querySelector('#research-new').onclick=()=>this.newConversation();
  document.querySelector('#research-ask').onclick=()=>{this.questionJob=null;document.querySelector('#research-answer').hidden=true;document.querySelector('#research-question').value='';document.querySelector('#research-question-dialog').showModal();};
  document.querySelector('#research-question-form').onsubmit=async e=>{
   e.preventDefault();e.submitter.disabled=true;
   try{
    let cid=this.recoveryMode||(this.nodeScope?this.nodeRows?.[0]?.id:window.codexTerminalPane.entries.get(window.codexTerminalPane.current)?.conversation_id||this.data?.conversations[0]?.id);
    if(!cid){const conversation=await this.post({action:'register',node_id:this.nodeScope?.id||'project:root',objective:'Project coordination and research history'});cid=conversation.id;}
    this.questionJob=await this.post({action:'ask',conversation_id:cid,question:document.querySelector('#research-question').value});
    this.renderAnswer();await this.refresh();
   }catch(error){toast(error.message);}finally{e.submitter.disabled=false;}
  };

  document.querySelector('#research-search').oninput=()=>{clearTimeout(this.searchTimer);this.searchTimer=setTimeout(()=>this.refresh(),250);};
  document.querySelector('#research-new-node').onchange=()=>this.newContext();
  document.querySelector('#research-new-form').onsubmit=async e=>{
   e.preventDefault();const button=e.submitter;button.disabled=true;
   try{
    const selected=document.querySelector('#research-new-node').value==='selected';
    const conv=await this.post({action:'register',node_id:selected?(this.nodeScope?.id||state.analysisFocus):'project:root',objective:document.querySelector('#research-objective').value});
    document.querySelector('#research-new-dialog').close();await this.refresh();await window.codexTerminalPane.useConversation(conv);this.close();
   }catch(error){toast(error.message);}finally{button.disabled=false;}
  };
  document.querySelector('#research-override-form').onsubmit=async e=>{e.preventDefault();try{await this.post({action:'override',...this.overrideTarget,reason:document.querySelector('#research-override-reason').value});document.querySelector('#research-override-dialog').close();this.refresh();}catch(error){toast(error.message);}};
  setInterval(()=>{if(!document.hidden&&(!this.panel.hidden||document.querySelector('#research-question-dialog').open))this.refresh();},5000);
 }
 setupWindow(){
  try{this.windowRect=JSON.parse(localStorage.getItem('research-conversation-window')||'null');}catch{}
  this.windowRect=this.windowRect||{x:window.innerWidth-536,y:100,width:520,height:390};
  this.applyWindowRect();
  const bind=(handle,resizing)=>{
   handle.onpointerdown=event=>{
    if(event.button!==0||event.target.closest('#research-close'))return;
    event.preventDefault();this.hideTitle();this.closeMenu();
    const origin={...this.windowRect},x=event.clientX,y=event.clientY;
    handle.setPointerCapture(event.pointerId);
    handle.onpointermove=move=>{
     const dx=move.clientX-x,dy=move.clientY-y;
     this.windowRect=resizing?{...origin,width:origin.width+dx,height:origin.height+dy}:{...origin,x:origin.x+dx,y:origin.y+dy};
     this.applyWindowRect();
    };
    const finish=()=>{handle.onpointermove=null;handle.onpointerup=null;handle.onpointercancel=null;this.saveWindowRect();};
    handle.onpointerup=finish;handle.onpointercancel=finish;
   };
  };
  bind(document.querySelector('#research-drag'),false);
  const resize=document.querySelector('#research-resize');bind(resize,true);
  resize.onkeydown=event=>{
   const directions={ArrowLeft:[-16,0],ArrowRight:[16,0],ArrowUp:[0,-16],ArrowDown:[0,16]},delta=directions[event.key];
   if(!delta)return;event.preventDefault();this.windowRect.width+=delta[0];this.windowRect.height+=delta[1];this.applyWindowRect();this.saveWindowRect();
  };
  window.addEventListener('resize',()=>this.applyWindowRect());
 }
 applyWindowRect(){
  const r=this.windowRect,vw=window.innerWidth,vh=window.innerHeight;
  r.width=Math.min(Math.max(320,r.width),vw-16);r.height=Math.min(Math.max(220,r.height),vh-16);
  r.x=Math.max(8,Math.min(r.x,vw-r.width-8));r.y=Math.max(8,Math.min(r.y,vh-r.height-8));
  Object.assign(this.panel.style,{left:r.x+'px',top:r.y+'px',width:r.width+'px',height:r.height+'px',right:'auto'});
  window.dispatchEvent(new Event('manager-layout'));
 }
 saveWindowRect(){localStorage.setItem('research-conversation-window',JSON.stringify(this.windowRect));}
 close(){
  this.hideTitle();this.closeMenu();this.panel.hidden=true;
  if(typeof folderForceGraph!=='undefined'){
   const prior=folderForceGraph?.managerSnapshot;
   if(prior){state.analysisFocus=prior.selected;state.query=prior.query;document.querySelector('#search').value=prior.query;}
   folderForceGraph?.endManagerView();
  }
 }
 syncGraph(){if(!this.nodeScope&&!this.panel.hidden&&this.data&&typeof folderForceGraph!=='undefined')folderForceGraph?.setManagerView(this.data.conversation_node_ids||[]);}
 post(body){return api('/api/research',{method:'POST',body:JSON.stringify(body)});}
 show(){this.panel.setAttribute('aria-label','Conversations');this.nodeScope=null;this.recoveryMode=null;this.panel.hidden=false;this.syncGraph();this.refresh();}
 async showNode(id){
  this.close();
  this.nodeScope={id,title:state.records.get(id)?.title||id};this.recoveryMode=null;
  document.querySelector('#research-search').value='';this.panel.setAttribute('aria-label','Conversations · '+this.nodeScope.title);
  this.panel.hidden=false;this.syncGraph();
  const rows=await this.refresh();
  if(!rows||this.nodeScope?.id!==id)return;
  document.querySelector('#node-tooltip').hidden=true;
  document.querySelector('#research-search').focus();
 }
 async openConversation(cid){
  try{const recovery=await api('/api/research/recovery?id='+encodeURIComponent(cid));await window.codexTerminalPane.useConversation(recovery.conversation);this.close();}
  catch(error){toast(error.message);}
 }
 newContext(){document.querySelector('#research-new-context').textContent=document.querySelector('#research-new-node').value==='selected'?(this.nodeScope?.title||state.records.get(state.analysisFocus)?.title||'No selected node'):(state.projectName||'Project')+' · Project';}
 newConversation(){document.querySelector('#research-new-node').value=this.nodeScope||window.codexTerminalPane.scope==='analysis'?'selected':'project';this.newContext();document.querySelector('#research-objective').value='';document.querySelector('#research-new-dialog').showModal();}
 override(cid,pid){this.overrideTarget={conversation_id:cid,plan_id:pid};document.querySelector('#research-override-reason').value='';document.querySelector('#research-override-dialog').showModal();}
 renderAnswer(){
  if(!this.questionJob)return;
  this.questionJob=this.data?.jobs.find(job=>job.id===this.questionJob.id)||this.questionJob;
  const box=document.querySelector('#research-answer');box.hidden=false;
  if(this.questionJob.result){box.textContent=JSON.parse(this.questionJob.result).summary;}
  else box.textContent=this.questionJob.state==='failed'?'The manager could not answer. Your question is saved in the conversation history; you can try again.':'The manager is checking the project records…';
 }
 async refresh(){
  if(!state.token)return;
  const request=++this.request;
  try{const query=document.querySelector('#research-search').value.trim(),scope=this.nodeScope;
   const [data,search,related]=await Promise.all([api('/api/research'),query&&!scope?api('/api/research/search?q='+encodeURIComponent(query)):null,scope?api('/api/research/node-conversations?node='+encodeURIComponent(scope.id)):null]);
   if(request!==this.request)return;this.data=data;this.search=search;this.related=related;this.syncGraph();
   if(scope){const q=query.toLowerCase();this.nodeRows=related.conversations.filter(c=>!q||JSON.stringify(c).toLowerCase().includes(q));}
   this.render();return this.nodeScope?this.nodeRows:data.conversations;}
  catch(error){const status=document.querySelector('#research-health');status.textContent=error.message;status.hidden=false;}
 }
 render(){
  if(!this.data)return;
  const box=document.querySelector('#research-content'),data=this.data;
  this.renderAnswer();
  document.querySelector('#research-health').hidden=true;
  if(this.recoveryMode)return;
  const rows=this.nodeScope?(this.nodeRows||[]):this.search?this.search.conversations:data.conversations;
  box.innerHTML=rows.map(c=>{
   const title=c.title||c.objective||'Untitled conversation';
   return `<button class="conversation-button" data-research-resume="${esc(c.id)}" aria-label="${esc(title)}"><span>${esc(title)}</span><span class="conversation-arrow" aria-hidden="true">↗</span></button>`;
  }).join('')||'<p class="conversation-empty">No conversations yet.</p>';
  box.querySelectorAll('[data-research-resume]').forEach(button=>{
   button.setAttribute('aria-haspopup','menu');
   button.onpointerenter=()=>this.showTitle(button);button.onpointerleave=()=>this.hideTitle();
   button.onfocus=()=>this.showTitle(button);button.onblur=()=>this.hideTitle();
   button.onclick=async()=>{
    this.hideTitle();this.closeMenu();button.disabled=true;
    await this.openConversation(button.dataset.researchResume);
    button.disabled=false;
   };
   button.oncontextmenu=event=>{event.preventDefault();event.stopPropagation();this.showMenu(button,event.clientX,event.clientY);};
   button.onkeydown=event=>{
    if(event.key==='ContextMenu'||(event.shiftKey&&event.key==='F10')){
     event.preventDefault();const rect=button.getBoundingClientRect();this.showMenu(button,rect.left+12,rect.bottom);
    }
   };
  });
 }
 showTitle(button){
  const tip=this.titleTooltip;tip.textContent=button.getAttribute('aria-label');tip.hidden=false;
  button.setAttribute('aria-describedby',tip.id);
  const anchor=button.getBoundingClientRect(),rect=tip.getBoundingClientRect();
  tip.style.left=Math.max(8,Math.min(anchor.left,window.innerWidth-rect.width-8))+'px';
  tip.style.top=Math.max(8,anchor.bottom+6+rect.height>window.innerHeight-8?anchor.top-rect.height-6:anchor.bottom+6)+'px';
 }
 hideTitle(){if(this.titleTooltip)this.titleTooltip.hidden=true;}
 showMenu(button,x,y){
  this.hideTitle();
  this.menuConversation=button.dataset.researchResume;this.menu.hidden=false;
  if(!x&&!y){const rect=button.getBoundingClientRect();x=rect.left+12;y=rect.bottom;}
  const rect=this.menu.getBoundingClientRect();
  this.menu.style.left=Math.max(8,Math.min(x,window.innerWidth-rect.width-8))+'px';
  this.menu.style.top=Math.max(8,Math.min(y,window.innerHeight-rect.height-8))+'px';
  this.menu.querySelector('button').focus();
 }
 closeMenu(restoreFocus=false){
  if(!this.menu||this.menu.hidden)return;
  this.menu.hidden=true;
  if(restoreFocus){const button=[...this.panel.querySelectorAll('[data-research-resume]')].find(b=>b.dataset.researchResume===this.menuConversation);button?.focus();}
 }
 async continueConversation(cid){
  if(this.continuing)return;
  this.continuing=true;
  try{
   const recovery=await api('/api/research/recovery?id='+encodeURIComponent(cid)),old=recovery.conversation;
   const next=await this.post({action:'register',node_id:old.binding,predecessor:old.id,objective:'Continue from '+old.id+'. Read the predecessor recovery context before acting. Previous objective: '+old.objective});
   await this.refresh();await window.codexTerminalPane.useConversation(next);this.close();
  }catch(error){toast(error.message);}finally{this.continuing=false;}
 }

 async recover(cid){
  this.recoveryMode=cid;
  try{
   const r=await api('/api/research/recovery?id='+encodeURIComponent(cid)),box=document.querySelector('#research-content');
   box.replaceChildren();const back=document.createElement('button');back.textContent='← Conversations';back.onclick=()=>{this.recoveryMode=null;this.render();};box.append(back);
   const history=document.createElement('button');history.textContent='Full event history';let cursor=0;
   const historyBox=document.createElement('pre');historyBox.hidden=true;
   history.onclick=async()=>{try{const data=await api('/api/research/history?id='+encodeURIComponent(cid)+'&after='+cursor);historyBox.hidden=false;historyBox.textContent+='\n'+JSON.stringify(data.events,null,2);cursor=data.next_cursor;history.textContent=data.events.length===100?'More history':'History loaded';history.disabled=data.events.length<100;}catch(e){toast(e.message);}};
   box.append(history,historyBox);
   const heading=document.createElement('h3');heading.textContent=r.conversation.objective;box.append(heading);
   const note=document.createElement('p');note.textContent=r.next_step;box.append(note);
   for(const [title,value] of [['Node',r.node],['Manager briefing',r.conversation.briefing?JSON.parse(r.conversation.briefing):{status:r.conversation.review}],['Latest checkpoint',r.checkpoint],['Predecessor context',r.predecessor_context],['Executions',r.executions],['Events since checkpoint',r.events_since_checkpoint]]){
    const section=document.createElement('details');section.open=['Manager briefing','Latest checkpoint'].includes(title);const summary=document.createElement('summary');summary.textContent=title;const pre=document.createElement('pre');pre.textContent=JSON.stringify(value,null,2);section.append(summary,pre);box.append(section);
   }
  }catch(error){toast(error.message);}
 }
}
window.researchManager=new ResearchManagerPane();
