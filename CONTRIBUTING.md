# Contributing

1. Fork and create a branch.
2. `uv sync`
3. Make your change and add or adjust a test. `tests/test_shared_memory.py` boots a real server, so please don't
   mock Hindsight.
4. `uv run ruff format . && uv run ruff check . && uv run pytest`
5. Open a PR. CI must be green.

## GitHub Actions policy

- Every action is pinned to a full commit SHA, with the version tag in a same-line comment:
  `uses: owner/action@<sha> # vX.Y.Z`
- Workflows default to `permissions: contents: read`, and checkout uses `persist-credentials: false`.
- `zizmor` audits the workflows in CI.
- Dependabot bumps the SHAs, the version comments, and the Python deps weekly, with a 7-day cooldown.
