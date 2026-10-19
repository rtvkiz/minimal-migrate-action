#!/usr/bin/env python3
"""Print a markdown bullet list of skipped FROM lines from a migrate.py
--output JSON file, for appending to $GITHUB_STEP_SUMMARY."""
import json
import sys

data = json.load(open(sys.argv[1]))
for s in data["skipped"]:
    print(f"- `{s['file']}:{s['line']}` — `{s['image']}`: {s['reason']}")
