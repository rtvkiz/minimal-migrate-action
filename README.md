# minimal-migrate-action

A GitHub Action that scans your repository's Dockerfiles for base images
that have a hardened, low-CVE equivalent in the
[minimal](https://minimalcontainers.com) catalog, and opens a pull request
swapping matching `FROM` lines over.

minimal images are free, MIT-licensed, cosign-signed, SBOM-attested, and
rebuilt daily to keep CVE counts near zero.

## What it does

1. Fetches the current [minimal catalog](https://github.com/rtvkiz/minimal/blob/main/catalog.json).
2. Scans Dockerfiles matching `dockerfile-glob` for `FROM` lines.
3. Rewrites any base image with a known minimal equivalent **and** an
   available minimal version matching the one you had pinned (exact-name
   matching only in this version — see [Matching](#matching) below).
4. Opens a pull request with the changes, unless `dry-run` is set.

## Usage

```yaml
name: Migrate to minimal images
on:
  workflow_dispatch:
  schedule:
    - cron: "0 9 * * 1" # weekly

permissions:
  contents: write
  pull-requests: write

jobs:
  migrate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: rtvkiz/minimal-migrate-action@v1
```

### Inputs

| Input | Default | Description |
|---|---|---|
| `dockerfile-glob` | `**/Dockerfile*` | Glob pattern for Dockerfiles to scan |
| `base-branch` | repo default branch | Branch to open the PR against |
| `pr-branch` | `minimal-migrate` | Branch name for the migration PR |
| `dry-run` | `false` | Report matches only; don't write changes or open a PR |
| `github-token` | `${{ github.token }}` | Token used to open the pull request |

### Outputs

| Output | Description |
|---|---|
| `changes-count` | Number of `FROM` lines rewritten |
| `skipped-count` | Number of `FROM` lines matched by name but left unchanged because minimal has no published version compatible with the requested tag |
| `pull-request-url` | URL of the opened pull request, if any |

## Matching

A `FROM` line is only rewritten when **both** of these hold:

1. The base image's bare repository name (registry/namespace/tag stripped)
   is an exact match for a minimal catalog image name, or for one of a
   small set of known aliases where the upstream Docker Hub name differs
   from minimal's (e.g. `redis` → `redis-slim`, `node` → `node-slim`,
   `postgres` → `postgres-slim`).
2. **minimal has actually published a version compatible with the one you
   had pinned.** minimal ships one rolling current version per image (plus
   retained historical build tags) rather than parallel version tracks the
   way Chainguard does — so `node:20` has no minimal equivalent at all if
   minimal has never built a 20.x tag, and the line is left untouched
   rather than silently jumped to whatever major minimal currently ships.
   A `FROM` line with no parseable version (bare `FROM node`, or a
   non-numeric tag like `node:alpine`) is treated as unconstrained and
   rewritten to `:latest`.

Skipped lines are reported in `skipped-count`, in the job's
`$GITHUB_STEP_SUMMARY`, and in the action's log output — they're not
silently dropped.

Multi-stage builds are handled correctly: a `FROM <stage-name>` referencing
a previous build stage is never mistaken for a real image.

## Development

```bash
# run the matcher against the bundled test fixture, offline (no network calls)
python3 scripts/migrate.py \
  --root test/fixtures \
  --catalog-file test/fixtures/catalog.json \
  --ghcr-tags-file test/fixtures/ghcr-tags.json \
  --dry-run
```

## License

MIT
