# Node conversation workflow

Research Map registers native conversations by stable research node ID. `context.json` in each terminal workspace contains the conversation ID, node ID, helper path, recovery file and manager briefing file.

## Start or resume

Use **Manager → New conversation** to state an objective and select the project or current node. The manager review is queued automatically. **Open / resume** selects that conversation's native session; it does not reuse a different node's session. If a native session is locked by another app or unavailable, **Continue in new session** creates a linked conversation with the predecessor's checkpoint and later events; it does not unlock or modify the original session. **Recovery & history** provides the checkpoint, evidence and paginated event history.

The app uses the newer desktop-bundled CLI when available, falling back to Homebrew otherwise. It retains your configured model and authentication. Portable sessions use workspace-write for their private terminal folder and the project metadata folder, with on-request approval. Research folders do not receive blanket write access. No sandbox-bypass flags are used.

Codex asks you to trust a new private terminal workspace and review its lifecycle hooks. Review the hook definitions normally; the app does not auto-trust them. Until trusted, native transcript tracking still records known messages and turn boundaries, but hook-based tool denials are not active. The helpers enforce their own placement and ownership checks regardless. Hooks are a guardrail, not a complete security boundary.

## Inspect, coordinate and recover

Commands below run from the application directory. Use absolute helper paths from a private terminal workspace.

```bash
python3 research_cli.py search 'growth rate parameter comparison'
python3 research_cli.py conversations --node NODE_ID
python3 research_cli.py recover CONVERSATION_ID
python3 research_cli.py history CONVERSATION_ID --after 0
python3 research_cli.py ask CONVERSATION_ID 'Has a related comparison already been performed?'
python3 research_cli.py status
```

`ask` queues a review by the shared main manager. Results are saved in the event history. Questions asked through **Ask manager** show their answer in that question dialog. Placement reviews and activity remain background logs/metadata rather than tabs in the conversation window. Search results and manager answers cover registered application sessions and explicitly imported sessions, not every conversation on the computer.

Search, status, conversation/history, recovery and plan-status queries open the registry read-only, without schema initialization. Recovery reads the most recently captured snapshot; the background worker and trusted hooks continue to capture native events. Mutating helpers still require the normal CLI permission flow.

The native-session adapters are version-sensitive. Unknown transcript structures are not treated as verified completion. A missed callback does not authorize rerunning an execution.

## Propose placement before creating or running analysis

A plan specification is a JSON object:

```json
{
  "kind": "variant",
  "anchor": "EXISTING_ANALYSIS_NODE_ID",
  "inputs": ["INPUT_NODE_ID"],
  "name": "descriptive_new_variant",
  "purpose": "State the scientific question and how this differs from previous work",
  "parameters": {"example_parameter": 0.2},
  "code_sources": ["/absolute/path/inside/the/research/project/existing_script.py"],
  "command": ["python3", "code/existing_script.py"]
}
```

Placement kinds:

- `variant`: sibling of the anchor.
- `child`: narrower investigation within the anchor.
- `synthesis`: requires at least two input nodes and selects their nearest shared organizational collection.
- `method`: reusable work under a project or collection anchor.
- `collection`: a new physical organizational package; logical grouping of existing folders uses the separate collection command below.

```bash
python3 research_cli.py plan CONVERSATION_ID --spec /absolute/path/to/spec.json
python3 research_cli.py plan-status PLAN_ID
python3 research_cli.py create PLAN_ID
```

`--spec-json` accepts an inline JSON object when creating a temporary specification file would itself require approval. A pending or rejected plan cannot create an analysis. The manager can flag duplication or scientific uncertainty. Resolve the issue or record your own explicit override in the UI; never infer an override from elapsed time.

When review identifies the wrong parent or an overlapping proposal, preserve that history and retire the unused proposal. Request reconsideration of a proposal needing attention after recording the resolution:

```bash
python3 research_cli.py retire-plan OLD_PLAN --reason 'Replaced by a narrower child of the actual source analysis; no package created'
python3 research_cli.py review-plan PLAN --reason 'Exact input lineage supplied and the unused competing proposal retired'
```

Retirement releases an unused proposal; it never deletes a created or partially created package. Reconsideration queues both placement and conversation review and does not imply approval. Use simple absolute helper commands without shell pipes or compound commands; the hook rejects those even if part of the command is read-only.

Creation reserves the destination, rejects collisions, copies declared code and records SHA-256 fingerprints. New packages contain `metadata.json`, `description.md`, `code/`, `data/` and `figures/`. Large source datasets remain referenced in place. New packages and their later outputs are discovered automatically and appear in the physical graph without a manual refresh.

## Write code and execute

For small code edits, the helper takes a JSON-encoded string:

```bash
python3 research_cli.py write CONVERSATION_ID GENERATED_NODE_ID \
  --path code/example.py --content-json '"print(1)\n"'
python3 research_cli.py run CONVERSATION_ID GENERATED_NODE_ID -- python3 code/example.py
```

The run arguments must exactly match the reviewed plan's `command`. The run uses the generated analysis as its working directory, records code fingerprints before execution, captures a log and records the exit code. A running or unresolved execution blocks another run on that analysis. Execution completion does not establish scientific validation.

The helper operates within existing OS/CLI permissions. A reviewed placement does not grant write access to the research disk. Follow the CLI's normal approval flow when an authorized action needs it.

## Checkpoint meaningful milestones

```bash
python3 research_cli.py checkpoint CONVERSATION_ID \
  --summary 'Calculation finished; numerical validation remains pending' \
  --details '{"pending":["validate outputs"],"decisions":["record the accepted assumptions"]}' \
  --status idle
```

Supported statuses: `active`, `idle`, `interrupted`, `completed`, `superseded`, `needs_attention`. Do not mark an analysis scientifically validated just because a process exited successfully. Native completion, interruption and transcript capture also generate events/checkpoints and manager summary jobs.

If creation was interrupted after writing a complete package, `recover-create PLAN_ID` checks identity and copied-code fingerprints and finalizes its registry record. An incomplete folder is never overwritten automatically.

## Group existing nodes without moving folders

```bash
python3 research_cli.py collection --title 'Meaningful shared collection' \
  --parent PARENT_NODE_ID --children CHILD_A CHILD_B
python3 research_cli.py link OUTPUT_NODE INPUT_NODE \
  --relation depends_on --evidence 'Recorded input to this analysis'
```

Grouping requires existing siblings and preserves IDs, storage paths and conversation bindings. The collection is logical metadata; the graph continues to show physical folder structure. Dependencies are separate from containment and are checked for cycles.

## Storage, reliability and recovery limits

- `research.sqlite3`: stable node aliases, conversations, append-only events, checkpoints, placement reservations, executions and manager jobs.
- `workspace.sqlite3`: earlier application notes/messages and existing terminal bindings, preserved.
- `.research/manager/`: manager CLI workspace and structured-output schema.
- `.research/backups/`: backups made before introducing the manager.
- `.research/revisions/`: previous versions of helper-edited generated code.
- `.codex-terminals/`: private CLI workspaces and node-specific context.

The registry is bound to one research root; do not reuse it for an unrelated project. Native transcripts are read only for exact app-owned registered workspaces. The app never scans unrelated conversation content for the manager. The SQLite and JSONL native adapters must be checked when upgrading the CLI.

Manager jobs use durable registration, leases, serialized execution, retry/backoff and explicit failure states. Summary checkpoints record exactly which event sequence they cover. A failed manager call does not erase or falsely complete a conversation. First inspect execution identity, input/code versions, logs and outputs during recovery; never automatically rerun from an interrupted status.


## Automatic graph updates and node conversations

The running server checks registered analysis packages every 3 seconds for new or changed files, and existing folder modification times every 30 seconds to discover other new folders. A change starts a serialized read-only inventory/model rebuild; the browser checks for a new complete snapshot every 3 seconds. Larger projects can take several more seconds to rebuild. Existing search, selection, expanded branches, pins, camera and active terminal are retained. A previously enlarged leaf stays expanded if a newly created child makes it a parent. Closed branches remain closed. A disconnected disk or failed scan retains the previous snapshot; discovery resumes when the disk reconnects. Refresh remains available for an immediate full scan.

Right-click a graph node:

- **Codex conversations…** lists conversations bound to the node, plus conversations recorded as creating or executing that analysis.

Within that interface, **Open / resume** opens the selected conversation and **Recovery & history** displays its checkpoints, manager briefing, execution records and history. Viewing recovery does not execute or rerun analysis.

Creation/execution associations come from durable registry records, so a child can find the conversation that started on its parent. Opening preserves the original conversation/node binding and native session identity; it does not create a replacement conversation. An empty list offers the normal New conversation action. Native lock, trust and permission requirements still apply. Internal native approval-review sessions excluded from research tracking do not appear in these lists.
