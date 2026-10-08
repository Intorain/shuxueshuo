"""Validate files with --check, or publish to an explicitly selected instance."""

import argparse
import json

from shuxueshuo_server.learning.content import load_content, publish
from shuxueshuo_server.product.config import Settings
from shuxueshuo_server.product.db import engine

p = argparse.ArgumentParser()
p.add_argument("--check", action="store_true")
p.add_argument("--mode", choices=["local", "server"], default="local")
p.add_argument("--data-dir")
p.add_argument("--instance")
a = p.parse_args()
rows = load_content()
if a.check:
    print(json.dumps({k: len(v) for k, v in rows.items()}))
else:
    if not a.data_dir or not a.instance:
        p.error("--data-dir and --instance are required")
    settings = Settings.load(a.mode, a.data_dir, a.instance)
    db = engine(settings.url("migration"))
    try:
        print(json.dumps(publish(db, rows)))
    finally:
        db.dispose()
