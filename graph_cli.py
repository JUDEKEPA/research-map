#!/usr/bin/env python3
"""Edit Research Map graph visibility. Only app metadata is changed."""
import argparse
import json
from pathlib import Path
from graph_visibility import read_state, update_state

APP = Path(__file__).resolve().parent


def resolve(nodes, target):
    matches = [n for n in nodes if target in (n['id'], n.get('folder_path'), n.get('title'))]
    if not matches:
        matches = [n for n in nodes if n.get('folder_path') and target.endswith('/' + n['folder_path'])]
    if len(matches) != 1:
        options = '\n'.join(n['id'] + '  ' + n.get('folder_path', n['title']) for n in matches[:15])
        raise ValueError(('Ambiguous node; use its ID or full folder path:\n' + options) if matches else 'Node not found; use list --query TEXT to find its ID or path')
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['list', 'status', 'hide', 'unhide', 'show-hidden', 'hide-hidden'])
    parser.add_argument('target', nargs='?')
    parser.add_argument('--query', default='')
    args = parser.parse_args()
    try:
        model = json.loads((APP/'project-model.json').read_text())
        nodes = model['nodes']
        path = APP/'graph-visibility.json'
        state = read_state(path)
        if args.action == 'status':
            print(json.dumps(state, indent=2))
            return
        if args.action == 'list':
            query = args.query.lower()
            for n in nodes:
                if query not in (n['title'] + ' ' + n.get('folder_path', '') + ' ' + n['id']).lower():
                    continue
                label = 'faint' if n['id'] in state['revealed'] else 'hidden' if n['id'] in state['hidden'] else 'normal'
                print(n['id'] + '\t' + label + '\t' + n.get('folder_path', n['title']))
            return
        if not args.target:
            parser.error('This operation requires a node ID, unique title, or folder path')
        node = resolve(nodes, args.target)
        if args.action in ('hide', 'unhide'):
            patch = {args.action: [node['id']]}
            if args.action == 'hide':
                patch['conceal'] = [node['id']]
        else:
            children = [n['id'] for n in nodes if n.get('parent_id') == node['id'] and n['id'] in state['hidden']]
            patch = {'reveal' if args.action == 'show-hidden' else 'conceal': children}
        result = update_state(path, patch, nodes, model.get('root_id'))
        print(json.dumps(dict(action=args.action, node=node['id'], **result), indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
