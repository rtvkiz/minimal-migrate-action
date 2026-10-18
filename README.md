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
3. Rewrites any base image with a known minimal equivalent (exact-name
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
| `pull-request-url` | URL of the opened pull request, if any |

## Matching

This version only rewrites a `FROM` line when the base image's bare
repository name (registry/namespace/tag stripped) is an exact match for a
minimal catalog image name, or for one of a small set of known aliases
where the upstream Docker Hub name differs from minimal's (e.g. `redis` →
`redis-slim`, `node` → `node-slim`, `postgres` → `postgres-slim`).

It will not attempt to preserve the original image's version — the
replacement is always pinned to `:latest`, and the opened PR calls this out
explicitly so you can verify and re-pin before merging.

Multi-stage builds are handled correctly: a `FROM <stage-name>` referencing
a previous build stage is never mistaken for a real image.

## Development

```bash
# run the matcher against the bundled test fixture, offline
python3 scripts/migrate.py --root test/fixtures --catalog-file test/fixtures/catalog.json --dry-run
```

## License

MIT
