'use strict';
(()=>{
 document.body.classList.add('portable-workspace');
 const config=JSON.parse(document.getElementById('portable-settings').textContent);
 const keys=['analysis-focus','inventory-scope','inventory-selected','workspace-view','project-navigation-version','folder-navigation-v1','folder-force-map-v1','folder-tree-window-v1','inspect-window-size','codex-terminal-scope','codex-terminal-window-v2','research-conversation-window','conversation-last-deleted','engine'];
 // Different backends can reuse a port. Restore only this project's own UI state.
 for(const key of keys){localStorage.removeItem(key);if(typeof config.settings[key]==='string')localStorage.setItem(key,config.settings[key]);}
 let saved=JSON.stringify(config.settings);
 setInterval(()=>{const settings={};for(const key of keys){const value=localStorage.getItem(key);if(value!==null)settings[key]=value;}const next=JSON.stringify(settings);if(next===saved)return;fetch('/api/ui-state',{method:'POST',headers:{'Content-Type':'application/json','X-Workspace-Token':config.token},body:JSON.stringify({settings})}).then(r=>{if(r.ok)saved=next;}).catch(()=>{});},1500);
 window.addEventListener('DOMContentLoaded',()=>{
  const toolbar=document.querySelector('.workspace-toolbar'),open=document.createElement('button');open.textContent='Open project';open.className='project-open';open.onclick=()=>location.assign(config.launcher_url);if(config.launcher_url)toolbar.prepend(open);
  const setup=document.createElement('button');setup.id='project-setup';setup.textContent='Check Codex setup';setup.title='Validate skills, authentication and live hooks';toolbar.append(setup);
  setup.onclick=async()=>{setup.disabled=true;try{const conv=await api('/api/setup/validate',{method:'POST',body:'{}'});await window.codexTerminalPane.useConversation(conv);}catch(error){toast(error.message);}finally{setup.disabled=false;}};
  const check=async()=>{try{const data=await(await fetch('/api/setup/status')).json();setup.textContent=data.live_validated?'Codex ready':'Finish Codex setup';setup.title=data.live_validated?'Live lifecycle hooks verified for this project':'Open a small read-only validation conversation; review hooks in the CLI if requested.';setup.classList.toggle('setup-ready',!!data.live_validated);}catch{}};check();setInterval(check,5000);
 });
})();
