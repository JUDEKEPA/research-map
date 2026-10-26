"""Read-only capability report. Never changes trust, login or global configuration."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

def codex_path():
    candidates=[os.environ.get('CODEX_CLI_PATH',''),'/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex',shutil.which('codex') or '', '/opt/homebrew/bin/codex','/usr/local/bin/codex']
    return next((p for p in candidates if p and Path(p).is_file() and os.access(p,os.X_OK)),None)

def run(args):
    try:
        p=subprocess.run(args,capture_output=True,text=True,timeout=12)
        return p.returncode==0,(p.stdout+p.stderr).strip()[:1500]
    except (OSError,subprocess.TimeoutExpired) as e:return False,str(e)

def callback_check(state):
    # Exercise the installed callback against an isolated registry, never the user's history.
    code="""import json,sys,tempfile
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from research_registry import Registry
from research_hook import handle
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp);source=p/'source';source.mkdir();r=Registry(p,source)
 r.sync_nodes({'root_id':'root','nodes':[{'id':'root','title':'Test','storage':{'folders':[str(source)]}}]})
 c=r.register('root','Callback self-check')
 start=handle(r,c['id'],{'hook_event_name':'SessionStart'})
 deny=handle(r,c['id'],{'hook_event_name':'PreToolUse','tool_name':'exec_command','tool_input':{'cmd':'touch example'}})
 assert start['hookSpecificOutput']['hookEventName']=='SessionStart'
 assert deny['hookSpecificOutput']['permissionDecision']=='deny'
 print('Callback and placement guard passed in isolated temporary registry')
"""
    return run([sys.executable,'-c',code,str(state)])

def verify_ai(state,executable):
    work=Path(state)/'.research/doctor';work.mkdir(parents=True,exist_ok=True)
    nonce='READY-'+str(int(time.time()))
    command=[executable,'--sandbox','read-only','--ask-for-approval','never','--cd',str(work),'exec','--ephemeral','--skip-git-repo-check','--json','-']
    try:
        result=subprocess.run(command,input='Capability check only. Do not call tools or read files. Reply with exactly '+nonce+'.',capture_output=True,text=True,timeout=60)
        texts=[]
        for line in result.stdout.splitlines():
            try:
                event=json.loads(line);item=event.get('item',{})
                if item.get('type')=='agent_message':texts.append(item.get('text',''))
            except ValueError:pass
        ok=result.returncode==0 and any(nonce in text for text in texts)
        return {'name':'AI response','ok':ok,'detail':'A read-only ephemeral CLI response was verified.' if ok else 'The provider response could not be verified; finish setup in the CLI.','checked_at':time.time()}
    except (OSError,subprocess.TimeoutExpired):return {'name':'AI response','ok':False,'detail':'The CLI response check timed out or could not start. Finish setup in the CLI.'}

def report(state):
    state=Path(state);exe=codex_path();skills=list((state/'.agents'/'skills').glob('*/SKILL.md'))
    checks=[{'name':'Project identity','ok':(state/'project.json').is_file()},{'name':'Workflow skills','ok':{'project-scan','analysis-node','conversation-manager','project-validate'}.issubset({p.parent.name for p in skills})},{'name':'Hook callback installed','ok':(state/'research_hook.py').is_file()},{'name':'Codex CLI','ok':bool(exe)}]
    if exe:
        ok,detail=run([exe,'--version']);checks.append({'name':'CLI version','ok':ok,'detail':detail})
        ok,detail=run([exe,'login','status']);checks.append({'name':'Codex authentication','ok':ok,'detail':detail})
    ok,detail=callback_check(state);checks.append({'name':'Hook callback self-check','ok':ok,'detail':detail})
    native=[]
    if (state/'research.sqlite3').exists():
        with sqlite3.connect('file:'+str(state/'research.sqlite3')+'?mode=ro',uri=True) as db:
            native=[r[0] for r in db.execute("SELECT DISTINCT kind FROM research_events WHERE source='native_hook'")]
    return {'checks':checks,'local_ready':all(c['ok'] for c in checks),'native_events':native,'hook_validation':'Live validation is required in a Codex conversation; installed callbacks alone are not proof of trust or execution.'}

if __name__=='__main__':print(json.dumps(report(sys.argv[1]),indent=2))
