#!/usr/bin/env python3
"""Check the distributable file set for local paths and accidental private state."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
EXCLUDED_DIRS = {'node_modules', 'dist', '__pycache__', '.git', '.research-map', '.codex-terminals'}
FORBIDDEN_NAMES = {'inventory.json', 'catalog.json', 'analyses.json', 'project-model.json', 'runtime.json', 'ui-state.json', 'setup-status.json', 'app-origin.json', 'python-path.txt', '.DS_Store'}
PATTERNS = [re.compile(rb'/(?:Users|home)/[A-Za-z0-9][^\s"\'<>]*'), re.compile(rb'/Volumes/[A-Za-z0-9][^\s"\'<>]*'), re.compile(rb'/media/[A-Za-z0-9][^\s"\'<>]*'), re.compile(rb'\bsk-[A-Za-z0-9_-]{24,}')]

def source_files():
    return sorted(p for p in ROOT.rglob('*') if p.is_file() and not (set(p.relative_to(ROOT).parts) & EXCLUDED_DIRS))

def audit():
    issues = []
    for path in source_files():
        rel = path.relative_to(ROOT).as_posix()
        if path.is_symlink(): issues.append(rel+': symbolic link is not publishable')
        if path.name in FORBIDDEN_NAMES or path.name.startswith(('._','preview-')) or any(t in path.name for t in ('.sqlite3','.log')):
            issues.append(rel+': generated/private artifact')
        for pattern in PATTERNS:
            if pattern.search(path.read_bytes()): issues.append(rel+': possible local path or secret')
    return issues

if __name__ == '__main__':
    issues = audit()
    for issue in issues: print(issue)
    print('FAIL' if issues else 'PASS: source file set contains no detected machine paths, secrets or private runtime artifacts.')
    print('Review new content before publishing; pattern checks cannot prove absence of every kind of personal information.')
    sys.exit(bool(issues))
