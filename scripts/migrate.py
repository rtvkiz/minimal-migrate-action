#!/usr/bin/env python3
"""Scan Dockerfiles for base images that have a minimal hardened equivalent
and rewrite matching FROM lines in place.

Exact-name matching only (MVP): a FROM image is rewritten only when its
bare repository name (registry and tag stripped) matches an alias in
ALIASES, or matches a minimal catalog image name directly.

Version handling: minimal publishes one rolling current version per image
(plus retained historical build tags), not parallel version tracks the way
Chainguard does. A FROM line is only rewritten if the requested version is
actually available among minimal's published tags for that image — e.g.
`node:20` is left untouched if minimal has never published a 20.x tag for
node-slim, rather than silently jumping to whatever major minimal currently
ships. A FROM line with no parseable version (bare `FROM node`, or a
non-numeric tag like `node:alpine`) is treated as unconstrained and rewritten
to `:latest`.
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

# Matches minimal's published version tags, e.g. "8.6.1-r0". Deliberately
# excludes arch-suffixed variants ("8.6.0-r0-amd64"), "latest", and the
# date-only rebuild tags ("20260130") by requiring the string to end right
# after the -rN revision suffix.
VERSION_TAG_RE = re.compile(r"^(\d+(?:\.\d+)*)-r\d+$")


def fetch_catalog_names() -> set[str]:
    with urllib.request.urlopen(CATALOG_URL, timeout=15) as resp:
        catalog = json.load(resp)
    return {img["name"] for img in catalog["images"]}


def fetch_ghcr_tags(minimal_image_name: str) -> list[str]:
    """Anonymous-pull tag listing for a public ghcr.io/rtvkiz/minimal-<name>
    package. Returns [] on any failure (network, 404, auth) so callers treat
    an unreachable registry the same as "no matching version available"."""
    repo = f"rtvkiz/minimal-{minimal_image_name}"
    try:
        token_req = urllib.request.Request(f"https://ghcr.io/token?scope=repository:{repo}:pull")
        with urllib.request.urlopen(token_req, timeout=10) as resp:
            token = json.load(resp)["token"]
        tags_req = urllib.request.Request(
            f"https://ghcr.io/v2/{repo}/tags/list",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(tags_req, timeout=10) as resp:
            return json.load(resp).get("tags", [])
    except Exception as exc:  # noqa: BLE001 - registry lookup is best-effort
        print(f"warning: could not fetch tags for {repo}: {exc}", file=sys.stderr)
        return []


def parse_image_ref(image_ref: str) -> tuple[str | None, str | None]:
    """Split a FROM image reference into (bare repo name, tag-or-None),
    stripping any digest and registry/namespace prefix. Handles a
    registry-with-port host (e.g. "registry:5000/node:20") by only treating
    a colon in the LAST path segment as a tag separator."""
    ref = image_ref.split("@")[0]
    parts = ref.split("/")
    last = parts[-1]
    if ":" in last:
        repo_last, tag = last.rsplit(":", 1)
    else:
        repo_last, tag = last, None
    return (repo_last or None), tag


def requested_version_prefix(tag: str | None) -> list[int] | None:
    """Leading dotted-numeric prefix of a requested tag, e.g. "3.12-slim" ->
    [3, 12], "20" -> [20]. None if the tag has no parseable version (no tag
    at all, or something like "alpine"/"lts") — treated as unconstrained."""
    if not tag:
        return None
    m = re.match(r"^(\d+(?:\.\d+)*)", tag)
    if not m:
        return None
    return [int(p) for p in m.group(1).split(".")]


def best_matching_version_tag(requested: list[int], tags: list[str]) -> str | None:
    """Highest published minimal version tag whose leading components equal
    `requested`, or None if minimal has never published that version."""
    best_tag, best_version = None, None
    for t in tags:
        m = VERSION_TAG_RE.match(t)
        if not m:
            continue
        version = tuple(int(p) for p in m.group(1).split("."))
        if list(version[: len(requested)]) != requested:
            continue
        if best_version is None or version > best_version:
            best_version, best_tag = version, t
    return best_tag


def find_dockerfiles(root: Path, glob_pattern: str) -> list[Path]:
    return sorted(p for p in root.glob(glob_pattern) if p.is_file())


def resolve_target_tag(target: str, requested_tag: str | None, tag_cache: dict) -> str | None:
    """Returns the minimal tag to use, or None if the requested version has
    no compatible minimal release (caller should leave the FROM line alone)."""
    requested = requested_version_prefix(requested_tag)
    if requested is None:
        return "latest"
    if target not in tag_cache:
        tag_cache[target] = fetch_ghcr_tags(target)
    return best_matching_version_tag(requested, tag_cache[target])


def migrate_file(path: Path, alias_to_minimal: dict[str, str], tag_cache: dict) -> tuple[list[dict], list[dict]]:
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    changes: list[dict] = []
    skipped: list[dict] = []
    stage_names: set[str] = set()

    for i, line in enumerate(lines):
        m = FROM_RE.match(line)
        if not m:
            continue
        image_ref = m.group("image")
        bare, requested_tag = parse_image_ref(image_ref)
        if bare is None or bare in stage_names:
            continue
        if m.group("rest"):
            stage_names.add(m.group("rest").split()[-1])
        if bare == "minimal" or bare.startswith("minimal-"):
            continue  # already migrated
        target = alias_to_minimal.get(bare)
        if not target:
            continue

        minimal_tag = resolve_target_tag(target, requested_tag, tag_cache)
        if minimal_tag is None:
            skipped.append(
                {
                    "file": str(path),
                    "line": i + 1,
                    "image": image_ref,
                    "reason": f"minimal/{target} has no published version matching '{requested_tag}'",
                }
            )
            continue

        new_ref = f"ghcr.io/rtvkiz/minimal-{target}:{minimal_tag}"
        rest = m.group("rest") or ""
        new_line = f"{m.group('indent')}FROM {new_ref}{rest}\n"
        changes.append({"file": str(path), "line": i + 1, "old": image_ref, "new": new_ref})
        lines[i] = new_line

    if changes:
        path.write_text("".join(lines))
    return changes, skipped


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
    parser.add_argument(
        "--ghcr-tags-file",
        help="JSON file mapping minimal image name -> list of tags, for offline/test use instead of live GHCR lookups",
    )
    parser.add_argument("--output", help="Write JSON summary ({changes, skipped}) to this path")
    args = parser.parse_args()

    if args.catalog_file:
        catalog_names = {img["name"] for img in json.loads(Path(args.catalog_file).read_text())["images"]}
    else:
        catalog_names = fetch_catalog_names()

    tag_cache: dict = {}
    if args.ghcr_tags_file:
        tag_cache = json.loads(Path(args.ghcr_tags_file).read_text())

    alias_map = build_alias_map(catalog_names)
    root = Path(args.root)
    dockerfiles = find_dockerfiles(root, args.glob)

    all_changes: list[dict] = []
    all_skipped: list[dict] = []
    for df in dockerfiles:
        if args.dry_run:
            before = df.read_text()
        changes, skipped = migrate_file(df, alias_map, tag_cache)
        if args.dry_run and changes:
            df.write_text(before)  # revert; dry-run reports only
        all_changes.extend(changes)
        all_skipped.extend(skipped)

    for c in all_changes:
        print(f"{c['file']}:{c['line']}: {c['old']} -> {c['new']}")
    for s in all_skipped:
        print(f"{s['file']}:{s['line']}: SKIPPED {s['image']} ({s['reason']})")

    if args.output:
        Path(args.output).write_text(json.dumps({"changes": all_changes, "skipped": all_skipped}, indent=2))

    print(
        f"\n{len(all_changes)} base image(s) migrated, {len(all_skipped)} skipped "
        f"(no compatible minimal version), across {len(dockerfiles)} Dockerfile(s) scanned."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
