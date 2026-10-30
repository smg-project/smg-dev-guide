#!/usr/bin/env python3
"""Print one value from data/rules.json for shell consumers: rules.py <repo> <key>  (repo: smg | guide).
Lists are printed space-separated."""
import json
import sys
from pathlib import Path

d = json.loads((Path(__file__).resolve().parents[1] / "data" / "rules.json").read_text())
try:
    v = d[sys.argv[1]][sys.argv[2]]
except (IndexError, KeyError):
    sys.exit(f"usage: rules.py <smg|guide> <key>; keys: {', '.join(k for k in d['smg'] if not k.startswith('_'))}")
print(" ".join(v) if isinstance(v, list) else v)
