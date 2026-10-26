#!/usr/bin/env python3
"""Scoped native CLI hooks. Never bypass Codex hook trust or sandbox approval."""
import argparse
import json
import shlex
import sys
import tempfile
from pathlib import Path
from research_registry import Registry

READ_TOOLS={'read_file','list_dir','list_directory','search_files','update_plan'}
READ_COMMANDS={'pwd','ls','cat','head','tail','rg','wc','stat','file','which'}

def read_only_call(event,app):
    app=Path(app).resolve()
    name=event.get('tool_name','');args=event.get('tool_input',{})
    if name in READ_TOOLS:return True
    if name not in ('Bash','exec_command','shell_command','shell'):return False
    command=args.get('command') or args.get('cmd') or ''
    if isinstance(command,list):return False
    # Deliberately conservative: no compound shell, substitutions, redirects or find -exec.
    if any(c in command for c in ('\n','`','$')):return False
    try:
        lexer=shlex.shlex(command,posix=True,punctuation_chars=';&|<>')
        lexer.whitespace_split=True
        parts=list(lexer)
    except ValueError:return False
    if any(p and all(c in ';&|<>' for c in p) for p in parts):return False
    if not parts:return True
    if Path(parts[0]).name in READ_COMMANDS and not any(p.startswith(('--pre','--pre-glob')) for p in parts):return True
    # The helper validates placement, reservations and ownership itself.
    if len(parts)>1 and Path(parts[1]).resolve()==app/'project_doctor.py':
        return len(parts)==3 and Path(parts[0]).name in ('python','python3','python3.12') and Path(parts[2]).resolve()==app
    return len(parts)>1 and Path(parts[0]).name in ('python','python3','python3.12') and Path(parts[1]).resolve() in (Path(app)/'research_cli.py',Path(app)/'graph_cli.py')

def handle(reg,cid,event):
    conv=reg.conversation(cid)
    native=event.get('session_id')
    if native and conv['native_id'] and conv['native_id']!=native:
        # /clear or /fork creates a continuation record, preserving the previous binding.
        with reg.connect() as db:row=db.execute('SELECT id FROM research_conversations WHERE native_id=?',(native,)).fetchone()
        if row and reg.conversation(row['id'])['node_id']!=conv['node_id']:raise ValueError('Native session belongs to a different node')
        conv=reg.conversation(row['id']) if row else reg.register(conv['binding'],objective=conv['objective'],new=True,predecessor=cid)
        cid=conv['id']
    reg.hook_event(cid,event)
    if conv.get('workspace'):
        work=Path(conv['workspace']);marker=work/'active-conversation.json'
        if work.resolve().is_relative_to(reg.app/'.codex-terminals'):
            # Concurrent lifecycle/tool callbacks must not share one temporary filename.
            with tempfile.NamedTemporaryFile(mode='w',dir=work,prefix='.active-',delete=False) as stream:
                json.dump({'conversation_id':cid},stream);tmp=Path(stream.name)
            tmp.replace(marker)
    kind=event.get('hook_event_name')
    if kind=='PreToolUse' and not read_only_call(event,reg.app):
        conv=reg.conversation(cid)
        reason=('This command is outside the allowed simple read-only or managed helper commands. Use the absolute research_cli.py path without shell pipes, compound commands or substitutions. '
                'Create through plan -> manager review -> create, and execute through helper run. Current conversation review: '+conv['review']+'.')
        return {'hookSpecificOutput':{'hookEventName':'PreToolUse','permissionDecision':'deny','permissionDecisionReason':reason}}
    if kind in ('SessionStart','UserPromptSubmit'):
        return {'hookSpecificOutput':{'hookEventName':kind,'additionalContext':'This conversation is '+cid+'. Read context.json and recovery.json. Manager status and related work are available through research_cli.py. Before scientific execution use plan -> manager review -> create -> run. '+(reg.conversation(cid)['briefing'] or 'Initial manager briefing is pending.')}}
    return {}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--app',required=True);p.add_argument('--source',required=True);p.add_argument('--conversation',required=True);a=p.parse_args()
    try:print(json.dumps(handle(Registry(a.app,a.source),a.conversation,json.load(sys.stdin))))
    except Exception as error:
        print('Research lifecycle hook failed: '+str(error),file=sys.stderr);sys.exit(2)
