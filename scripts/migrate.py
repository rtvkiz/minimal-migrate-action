#!/usr/bin/env python3
"""Scan Dockerfiles for base images that have a minimal hardened equivalent
and rewrite matching FROM lines in place.

Exact-name matching only (MVP): a FROM image is rewritten only when its
bare repository name (registry and tag stripped) matches an alias in
ALIASES, or matches a minimal catalog image name directly.
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

CATALOG_URL = "https://raw.githubusercontent.com/rtvkiz/minimal/main/catalog.json"

# Upstream Docker Hub repo name -> minimal catalog image name, for the cases
# where they differ. Everything else is assumed identical (e.g. "redis-slim"
# only matches "redis-slim" itself unless listed here as "redis").
ALIASES = {
    "redis": "redis-slim",
    "node": "node-slim",
    "postgres": "postgres-slim",
    "openjdk": "java",
    "eclipse-temurin": "java",
    "amazoncorretto": "java",
    "httpd": "httpd",
    "nginx": "nginx",
}

FROM_RE = re.compile(
    r"^(?P<indent>\s*)FROM\s+(?P<image>[^\s]+)(?P<rest>\s+AS\s+\S+)?\s*$",
    re.IGNORECASE,
)


def fetch_catalog_names() -> set[str]:
    with urllib.request.urlopen(CATALOG_URL, timeout=15) as resp:
        catalog = json.load(resp)
    return {img["name"] for img in catalog["images"]}


def bare_repo_name(image_ref: str) -> str | None:
    """Strip registry/namespace/tag/digest, return the bare repo name, or
    None if this FROM references a build stage (no slashes, no registry-like
    dots, and not a known public registry host) rather than a real image."""
    ref = image_ref.split("@")[0]
    ref = ref.split(":")[0]
    parts = ref.split("/")
    name = parts[-1]
    return name or None


def find_dockerfiles(root: Path, glob_pattern: str) -> list[Path]:
    return sorted(p for p in root.glob(glob_pattern) if p.is_file())


def migrate_file(path: Path, alias_to_minimal: dict[str, str]) -> list[dict]:
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    changes = []
    stage_names: set[str] = set()

    for i, line in enumerate(lines):
        m = FROM_RE.match(line)
        if not m:
            continue
        image_ref = m.group("image")
        bare = bare_repo_name(image_ref)
        if bare is None or bare in stage_names:
            continue
        if m.group("rest"):
            stage_names.add(m.group("rest").split()[-1])
        if bare == "minimal" or bare.startswith("minimal-"):
            continue  # already migrated
        target = alias_to_minimal.get(bare)
        if not target:
            continue
        new_ref = f"ghcr.io/rtvkiz/minimal-{target}:latest"
        rest = m.group("rest") or ""
        new_line = f"{m.group('indent')}FROM {new_ref}{rest}\n"
        changes.append({"file": str(path), "line": i + 1, "old": image_ref, "new": new_ref})
        lines[i] = new_line

    if changes:
        path.write_text("".join(lines))
    return changes


def build_alias_map(catalog_names: set[str]) -> dict[str, str]:
    alias_map = dict(ALIASES)
    for name in catalog_names:
        alias_map.setdefault(name, name)
    return alias_map


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--glob", default="**/Dockerfile*")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--catalog-file", help="Local catalog.json path, for offline/test use")
    parser.add_argument("--output", help="Write JSON summary of changes to this path")
    args = parser.parse_args()

    if args.catalog_file:
        catalog_names = {img["name"] for img in json.loads(Path(args.catalog_file).read_text())["images"]}
    else:
        catalog_names = fetch_catalog_names()

    alias_map = build_alias_map(catalog_names)
    root = Path(args.root)
    dockerfiles = find_dockerfiles(root, args.glob)

    all_changes = []
    for df in dockerfiles:
        if args.dry_run:
            before = df.read_text()
        changes = migrate_file(df, alias_map)
        if args.dry_run and changes:
            df.write_text(before)  # revert; dry-run reports only
        all_changes.extend(changes)

    for c in all_changes:
        print(f"{c['file']}:{c['line']}: {c['old']} -> {c['new']}")

    if args.output:
        Path(args.output).write_text(json.dumps(all_changes, indent=2))

    print(f"\n{len(all_changes)} base image(s) matched across {len(dockerfiles)} Dockerfile(s) scanned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
