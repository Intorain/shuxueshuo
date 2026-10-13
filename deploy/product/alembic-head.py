"""Read the migration head from packaged source without importing application code."""
import ast
from pathlib import Path
import sys


def migration_head(directory):
    parents = {}
    for path in sorted(Path(directory).glob('*.py')):
        values = {}
        for statement in ast.parse(path.read_text(), filename=str(path)).body:
            if isinstance(statement, ast.Assign):
                for target in statement.targets:
                    if isinstance(target, ast.Name) and target.id in ('revision', 'down_revision'):
                        values[target.id] = ast.literal_eval(statement.value)
        if 'revision' not in values:
            continue
        revision = values['revision']
        if not isinstance(revision, str) or revision in parents or 'down_revision' not in values:
            raise ValueError(f'Invalid migration identity: {path.name}')
        parent = values['down_revision']
        parents[revision] = () if parent is None else (parent,) if isinstance(parent, str) else tuple(parent)
    referenced = {parent for group in parents.values() for parent in group}
    if referenced - parents.keys():
        raise ValueError('Migration ancestry is incomplete')
    heads = parents.keys() - referenced
    if len(heads) != 1:
        raise ValueError('Packaged source must have exactly one migration head')
    return heads.pop()


if __name__ == '__main__':
    print(migration_head(sys.argv[1]))
