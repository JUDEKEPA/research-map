# Research Map

A local research workspace with folder graphs, file and figure previews, and node-bound Codex conversations.

This source copy contains only application code and a fictional **Orchard Study** demo. It includes no research inventories, saved chats, account configuration, or original research files.

## Run locally

Requirements: Python 3.10+, Node.js/npm to install the terminal frontend. macOS supports the native desktop wrapper. The browser workspace runs through a local Python server.

```sh
npm ci
python3 launcher.py --port 8767
```

Open `http://127.0.0.1:8767` and select **Explore fictional demo**, or choose your own project folder. Graph browsing and file previews work without Codex. The demo opener does not send an AI validation request.

To build the macOS wrapper (requires Xcode command line tools):

```sh
python3 build_desktop.py
open "dist/Research Map Community.app"
```

The local build uses the Python installation that built it. It is not a signed, self-contained release installer.

## Demo

`demo/Orchard Study` contains deterministic synthetic growth data. Baseline and faster-growth analyses are peers; a sibling comparison references both. Each analysis contains `code/`, `data/`, `figures/`, a report, and metadata. There are no simulated conversation histories presented as real chats.

Regenerate demo files with `python3 generate_demo.py` (standard library only). Right-click an analysis node and choose **Inspect** to browse its code, data, and figures. Folder navigation also opens text and image previews. Manual zoom and graph controls remain available.

## Conversations and project state

Install and sign in to Codex CLI separately to use AI features. The app uses the CLI's existing account/model settings. Opening a non-demo project may run a short AI readiness request through your configured provider. Starting a conversation sends its project context and your prompts to that provider. Review hook trust prompts yourself; the app does not change global trust records.

Each project stores its inventory, node IDs, summaries, conversations and UI state in `.research-map/`. This generated folder contains local paths and potentially sensitive research/chat content. It is excluded from version control. Keep it with your private project for relocation and recovery; do not publish it as part of the application source.

Node IDs and project identity survive ordinary project-folder moves. Native resume also depends on the local Codex session still existing. **Continue in new session** uses saved recovery evidence when native resume is unavailable.

Portable terminals have write access to their terminal workspace and project metadata, with approval requested for additional access. Placement checks and hooks help coordinate analysis work; they are not a security boundary. Read [RESEARCH_WORKFLOW.md](RESEARCH_WORKFLOW.md) for package placement and manager/recovery behavior.

## Tests

```sh
python3 -m unittest discover -p 'test_*.py'
node test_force_graph.cjs
node test_preview_layout.cjs
python3 audit_public.py
```

Tests use temporary synthetic projects. Some tests need permission to bind a loopback port and start local subprocesses. They do not require access to any original research project.

## Publishing

Run the audit after edits. Share source only; exclude generated app state, dependencies, native bundles, logs and local build configuration. No repository or release has been published by preparing this copy.

MIT license. xterm.js dependencies retain their upstream licenses; install them using the lockfile rather than checking in `node_modules`.
