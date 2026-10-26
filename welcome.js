'use strict';
let token='',opening=false;
const $=id=>document.getElementById(id);
async function openProject(path){
 if(opening||!path)return;opening=true;$('setup').hidden=false;$('setup-error').textContent='';$('setup-message').textContent='Opening project';
 document.querySelectorAll('button').forEach(b=>b.disabled=true);
 try{
  const response=await fetch('/api/open-project',{method:'POST',headers:{'Content-Type':'application/json','X-Workspace-Token':token},body:JSON.stringify({path})}),job=await response.json();
  if(!response.ok)throw Error(job.error);
  const poll=async()=>{
   try{const result=await(await fetch('/api/open-status?id='+encodeURIComponent(job.id))).json();$('setup-message').textContent=result.message;$('setup-progress').value=result.progress||0;$('setup-percent').textContent=(result.progress||0)+'%';
    if(result.state==='ready'){location.assign(result.url);return;}
    if(result.state==='error')throw Error(result.message);setTimeout(poll,500);
   }catch(error){failed(error);}
  };poll();
 }catch(error){failed(error);}
}
function failed(error){opening=false;$('setup-error').textContent=error.message;document.querySelectorAll('button').forEach(b=>b.disabled=false);}
$('open-form').onsubmit=e=>{e.preventDefault();openProject($('project-path').value.trim());};
window.researchFolderSelected=path=>{if(path){$('project-path').value=path;openProject(path);}};
$('choose').onclick=()=>{if(window.webkit?.messageHandlers?.chooseProject)window.webkit.messageHandlers.chooseProject.postMessage({});else $('project-path').focus();};
fetch('/api/projects').then(r=>r.json()).then(data=>{token=data.token;$('open-demo').onclick=()=>openProject(data.demo);$('recent-section').hidden=!data.recent.length;for(const project of data.recent){const button=document.createElement('button');button.className='recent';const name=document.createElement('strong'),path=document.createElement('small');name.textContent=project.name;path.textContent=project.path;button.append(name,path);button.onclick=()=>openProject(project.path);$('recent').append(button);}}).catch(failed);
