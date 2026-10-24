"""Single-instance search expiry and operator disable commands."""

import argparse
import json
import os

from ..product.config import Settings
from ..product.db import engine
from .repository import SearchRepository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['local', 'server'], default=os.environ.get('PRODUCT_MODE', 'local'))
    parser.add_argument('--data-dir')
    parser.add_argument('--instance', default=os.environ.get('PRODUCT_INSTANCE'))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('cleanup')
    disabled = commands.add_parser('disable')
    disabled.add_argument('problem_id')
    args = parser.parse_args()
    settings = Settings.load(args.mode, args.data_dir, args.instance)
    db = engine(settings.url())
    try:
        repository = SearchRepository(db, settings.root / 'work/search/private-v1')
        if args.command == 'cleanup':
            print(json.dumps(repository.cleanup()))
        else:
            repository.disable(args.problem_id)
            print(json.dumps({'problem_id': args.problem_id, 'status': 'disabled'}))
    finally:
        db.dispose()


if __name__ == '__main__':
    main()
