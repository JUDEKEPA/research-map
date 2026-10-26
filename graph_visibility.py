"""Shared graph visibility metadata; research files are never modified."""
import fcntl
import json
import os
import tempfile
from pathlib import Path


def read_state(path):
    path = Path(path)
    if not path.exists():
        return dict(version=1, revision=0, hidden=[], revealed=[], initialized=False)
    state = json.loads(path.read_text())
    if not isinstance(state, dict) or state.get('version') != 1:
        raise ValueError('Invalid graph visibility state')
    for key in ('hidden', 'revealed'):
        if not isinstance(state.get(key), list) or not all(isinstance(i, str) for i in state[key]):
            raise ValueError('Invalid graph visibility IDs')
    return dict(state, initialized=True)


def update_state(path, patch, nodes, root_id=None):
    path = Path(path)
    records = {n['id']: n for n in nodes}
    if root_id is None:
        root_id = next((n['id'] for n in nodes if not n.get('parent_id')), None)
    operations = ('hide', 'unhide', 'reveal', 'conceal')
    if set(patch) - set(operations) - {'initialize'}:
        raise ValueError('Unknown visibility operation')
    for operation in operations:
        ids = patch.get(operation, [])
        if not isinstance(ids, list) or not all(isinstance(i, str) and i in records for i in ids):
            raise ValueError('Choose existing node IDs')
    if root_id in patch.get('hide', []):
        raise ValueError('The project root cannot be hidden')
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_state(path)
        if patch.get('initialize') and state['initialized']:
            return state
        hidden, revealed = set(state['hidden']), set(state['revealed'])
        hidden.update(patch.get('hide', []))
        hidden.difference_update(patch.get('unhide', []))
        revealed.update(patch.get('reveal', []))
        revealed.difference_update(patch.get('conceal', []))
        revealed.intersection_update(hidden)
        result = dict(version=1, revision=state['revision'] + 1, hidden=sorted(hidden), revealed=sorted(revealed))
        fd, temporary = tempfile.mkstemp(prefix='.graph-visibility-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(result, stream, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return dict(result, initialized=True)
