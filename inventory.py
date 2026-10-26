"""Exhaustive metadata inventory. No source file contents are loaded or modified."""
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from catalog import SOURCE, BASE


def identity(path):
    return 'fs-'+hashlib.sha256(path.encode()).hexdigest()[:24]


def parameters(path):
    # Folder names alone cannot establish scientific parameters. Read explicit
    # report/metadata fields instead of applying project-specific heuristics.
    return {}


def scan(root=SOURCE, base=BASE):
    scope = root/base
    entries, errors = [], []
    started = datetime.now(timezone.utc).isoformat()
    if not scope.is_dir():
        return dict(version=2, scope=base, source=str(root), scanned_at=started,
                    entries=[], errors=['Source folder unavailable: '+str(scope)], complete=False, counts={})

    def record(path, directory, link=False):
        rel = path.relative_to(root).as_posix()
        if rel=='.':rel=''
        try:
            st = path.lstat()
            size, modified = st.st_size, st.st_mtime
        except OSError as exc:
            size, modified = None, None
            errors.append({'path':rel,'error':str(exc)})
        parent_rel=path.parent.relative_to(root).as_posix() if path!=scope else None
        if parent_rel=='.':parent_rel=''
        entries.append(dict(id=identity(rel), path=rel, name=path.name,
                            parent=None if path==scope else identity(parent_rel),
                            directory=directory, symlink=link, size=size, modified=modified,
                            extension='' if directory else path.suffix.lower(),
                            system_metadata=path.name.startswith('._') or path.name=='.DS_Store',
                            parameters=parameters(rel[len(base):].lstrip('/'))))

    record(scope, True)
    for directory, dirs, files in os.walk(scope, followlinks=False, onerror=lambda exc:errors.append(str(exc))):
        # App metadata is not research content and must never index itself.
        dirs[:]=sorted(name for name in dirs if name!='.research-map')
        for name in dirs:
            p = Path(directory)/name
            record(p, True, p.is_symlink())
        for name in sorted(files):
            p = Path(directory)/name
            record(p, False, p.is_symlink())
    by_id = {e['id']:e for e in entries}
    for e in entries:
        e['file_count'] = 0 if e['directory'] else 1
        e['figure_count'] = int(not e['directory'] and e['extension']=='.png')
        e['folder_count'] = 0
        e['child_count'] = 0
    for e in sorted(entries,key=lambda e:e['path'].count('/'),reverse=True):
        p = by_id.get(e['parent'])
        if p:
            p['child_count'] += 1
            p['file_count'] += e['file_count']
            p['figure_count'] += e['figure_count']
            p['folder_count'] += e['folder_count']+int(e['directory'])
    extensions = Counter(e['extension'] for e in entries if not e['directory'])
    counts = dict(files=sum(not e['directory'] for e in entries), folders=sum(e['directory'] for e in entries),
                  png=extensions['.png'], pdf=extensions['.pdf'], csv=extensions['.csv'], json=extensions['.json'],
                  system_metadata=sum(e['system_metadata'] for e in entries), symlinks=sum(e['symlink'] for e in entries),
                  
                  extensions=dict(extensions))
    return dict(version=2, source=str(root), scope=base, root_id=identity(base), scanned_at=started,
                entries=entries, counts=counts, errors=errors, complete=not errors,
                scope_note='All research files and folders, including empty folders, backups, hidden files and OS metadata. The .research-map app-state directory is excluded. Symlink targets are not traversed. No scientific execution has been verified.')


def write_snapshot(app, data):
    destination=Path(app)/'inventory.json'
    temp=destination.with_suffix('.json.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')))
    temp.replace(destination)


if __name__=='__main__':
    data=scan()
    write_snapshot(Path(__file__).parent,data)
    print(json.dumps({'counts':data['counts'],'errors':data['errors'],'complete':data['complete']},indent=2))
