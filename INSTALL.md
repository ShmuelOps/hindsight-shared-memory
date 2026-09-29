# Install guide (macOS)

This guide sets up a fresh Mac, in about 10 minutes, so that:

- the **Hindsight memory server** runs in the background all the time (a launchd daemon, started at login),
- the **Hindsight web UI** runs in the background all the time,
- **Claude Code** uses it through the official **Hindsight Coding Agents plugin**. Memory is recalled and saved
  automatically, and one memory is shared per repository across every session and agent.

You don't need an API key. The server uses your Claude Code login (Pro, Max, Team or Enterprise) for fact
extraction, on Haiku.

## 1. Prerequisites

```bash
# Homebrew (skip if `brew --version` already works)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

brew install uv node                  # uv runs the server; Node runs the plugin and the UI
brew install --cask claude-code       # skip if you already have Claude Code
claude                                # log in once, then exit (/exit)
```

## 2. Install the server tool

```bash
uv tool install git+https://github.com/ShmuelOps/hindsight-shared-memory
uv tool update-shell                  # adds ~/.local/bin to your PATH; then open a new terminal
hindsight-shared-memory --help
```

## 3. Run the memory server as a daemon

```bash
hindsight-shared-memory install-service
```

The first start downloads two small models (embeddings and reranker), which takes about a minute. Check that
it's up:

```bash
curl http://127.0.0.1:8888/health     # {"status":"healthy","database":"connected",...}
```

The daemon starts at every login and restarts if it crashes. Its log is
`~/Library/Logs/hindsight-shared-memory.log`.

## 4. Run the web UI as a daemon

```bash
hindsight-shared-memory install-ui
open http://127.0.0.1:9999
```

The UI (Hindsight's Control Plane) lets you browse banks, memories, entities and knowledge pages, and test
recall. It's pinned to the same version as the server, is only reachable from your Mac, and also starts at
login. Its log is `~/Library/Logs/hindsight-ui.log`.

## 5. Add the Hindsight plugin to Claude Code

```bash
npx -y @vectorize-io/hindsight-coding-agents@0.8.0 install claude-code \
  --server self-hosted --api-url http://127.0.0.1:8888

# Inject memories by fast retrieval (no LLM call per session) instead of reflect,
# which is too slow with a subscription-backed local model and times out.
plutil -replace autoInject -string recall ~/.hindsight/coding-agent.json
```

The installer adds three hooks to `~/.claude/settings.json`, a `hindsight` MCP server, and a
`hindsight-coding-agent` skill. It backs up any file it changes as `<file>.hindsight-backup`.

## 6. Check it works

Open Claude Code in any git repository:

```bash
cd ~/some/repo && claude
```

- `claude mcp list` shows `hindsight: … ✔ Connected`.
- The first session in a new repo seeds its memory in the background: git history plus a short read-only survey
  of the code by Haiku, capped at $2. It shows up in the UI as the bank `coding-agent::<repo>`.
- Tell Claude a project decision, end the session, then ask about it in a new session: it already knows.

That's it. Every session in that repo, and any other agent that uses the plugin (Codex, Cursor, …), now shares
this memory.

---

## Optional: one memory for all repositories

By default each repo gets its own bank. To share a single bank across every repo:

```bash
plutil -replace bankId -string shared ~/.hindsight/coding-agent.json
```

## What it costs

All of it runs on Haiku, on your Claude subscription:

| When | What runs |
|------|-----------|
| First session in a repo, then every 20 commits | Codebase survey: `claude -p --model haiku`, capped at $2 |
| End of each turn | The server extracts facts from the new part of the session |
| Start of each session | Nothing: `autoInject: recall` is a plain search |

## Update

```bash
uv tool upgrade hindsight-shared-memory
hindsight-shared-memory install-service      # restart the server on the new version
hindsight-shared-memory install-ui           # re-pin the UI to the new version
npx -y @vectorize-io/hindsight-coding-agents@latest update
```

## Uninstall

```bash
npx -y @vectorize-io/hindsight-coding-agents@0.8.0 uninstall claude-code
hindsight-shared-memory uninstall-ui
hindsight-shared-memory uninstall-service
uv tool uninstall hindsight-shared-memory
```

Your memories stay in `~/.pg0/instances/hindsight-shared/`. Delete that folder to wipe them.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `curl …/health` never answers | `tail -50 ~/Library/Logs/hindsight-shared-memory.log`. The first start needs internet to download the models; after that the daemon starts offline |
| Stuck on the first start on some networks | Broken IPv6 can stall model downloads. Turn Wi-Fi IPv6 off (System Settings → Wi-Fi → Details → TCP/IP → Configure IPv6: Link-local only), or run `hindsight-shared-memory serve` once on another network |
| Claude doesn't remember | Plugin log: `~/.hindsight/coding-agents-logs/plugin.log`. Check that `autoInject` is `recall` (step 5) |
| UI shows no banks | Is the server healthy? Restart the UI with `hindsight-shared-memory install-ui` |
| Port 8888, 9999 or 5488 already in use | `HINDSIGHT_API_PORT=… hindsight-shared-memory install-service` and/or `HINDSIGHT_UI_PORT=… hindsight-shared-memory install-ui`, then pass the new `--api-url` to the plugin |
