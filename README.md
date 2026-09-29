# hindsight-shared-memory

[![CI](https://github.com/ShmuelOps/hindsight-shared-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/ShmuelOps/hindsight-shared-memory/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Always-on, local [Hindsight](https://github.com/vectorize-io/hindsight) memory for Claude Code on your Mac.**

This repo runs the Hindsight server and its web UI as background daemons on `localhost`. Claude Code connects to
them through the official **[Hindsight Coding Agents plugin](https://hindsight.vectorize.io/sdks/integrations/coding-agents)**.
Every session remembers project decisions automatically, and every session and agent in a repo shares the same
memory.

- **No API key.** Fact extraction runs on your Claude Code login (Pro, Max, Team or Enterprise), using Haiku.
- **Automatic.** The plugin injects relevant memories when a session starts and saves each session when it
  ends. You don't need to prompt it or keep CLAUDE.md rules.
- **Always on.** launchd daemons for the server and the UI, started at login and restarted if they crash.
- **Local and private.** Everything binds to `127.0.0.1` (upstream defaults to `0.0.0.0`). It uses an embedded
  Postgres and local ONNX embeddings and reranking, and starts offline once the models are downloaded.
- **Light.** Uses Hindsight's slim build, with no PyTorch (about 0.8 GB instead of 1.8 GB).

👉 **[Install guide](INSTALL.md)**: from scratch on macOS in about 10 minutes.

## How it works

```
 Claude Code (any repo) ── hooks + MCP ──┐   Hindsight Coding Agents plugin (npx)
 Codex / Cursor / … (same plugin) ───────┤   recall on session start · retain on Stop
                                         ▼
               hindsight-shared-memory daemon  ── 127.0.0.1:8888  (launchd)
                 ├─ LLM: claude-code provider → Haiku on your Claude login
                 ├─ ONNX embeddings + FlashRank reranker (local, cached)
                 └─ embedded Postgres (pg0) ── 127.0.0.1:5488
               Hindsight Control Plane UI ── 127.0.0.1:9999  (launchd)
```

The plugin gives each git repo its own bank (`coding-agent::<repo>`). The first session seeds it from git history
and a short Haiku survey of the code. The bank then maintains knowledge pages such as the component map,
conventions, key decisions and initiatives. It also adds `hindsight_*` MCP tools and a `hindsight-coding-agent`
skill for explicit memory work.

## What this repo adds on top of Hindsight

| | Upstream default | Here |
|---|---|---|
| Bind address (API and UI) | `0.0.0.0`: your whole network, no auth | `127.0.0.1` |
| LLM | OpenAI (API key) | `claude-code` + `claude-haiku-4-5`, no key |
| Install size | 1.8 GB (PyTorch) | ~0.8 GB (ONNX + FlashRank) |
| Offline start | Checks Hugging Face on every start | Offline once the models are cached |
| Reranker cache | `/tmp`, wiped on reboot | `~/.cache/hindsight-shared-memory` |
| Embedded Postgres port | 5432 (clashes with a local Postgres) | 5488 |
| Running it | You run it yourself | `install-service` / `install-ui` launchd daemons |
| Daemon PATH | — | Stable dirs only, so a `claude` shim from a terminal session isn't baked in |
| Server MCP endpoint (`/mcp/<bank>/`) | ~35 tools, including `delete_bank` | 5 memory tools, for other MCP clients |

## CLI

```
hindsight-shared-memory serve               # run the server in the foreground
hindsight-shared-memory install-service     # server daemon (launchd; systemd --user on Linux)
hindsight-shared-memory uninstall-service   # remove it (memories are kept)
hindsight-shared-memory install-ui          # web UI daemon, pinned to the server version (needs Node.js)
hindsight-shared-memory uninstall-ui
```

## Configuration

Every setting is a Hindsight environment variable. Set it before `serve`, or before `install-service`, which bakes
your `HINDSIGHT_*` variables into the daemon.

| Variable | Default here | Notes |
|----------|--------------|-------|
| `HINDSIGHT_API_HOST` | `127.0.0.1` | |
| `HINDSIGHT_API_PORT` | `8888` | If you change it, pass the new `--api-url` to the plugin and the UI |
| `HINDSIGHT_UI_PORT` | `9999` | Used by `install-ui` |
| `HINDSIGHT_API_LLM_PROVIDER` | `claude-code` | Or `ollama`, `openai`, `anthropic`, … or `none` (storage and search only) |
| `HINDSIGHT_API_LLM_MODEL` | `claude-haiku-4-5` | Sonnet extracts more thoroughly but is much slower (~30 s per retain in testing) |
| `HINDSIGHT_API_EMBEDDINGS_PROVIDER` | `onnx` | Model `intfloat/multilingual-e5-small` |
| `HINDSIGHT_API_RERANKER_PROVIDER` | `flashrank` | Cached in `~/.cache/hindsight-shared-memory/flashrank` |
| `HINDSIGHT_API_DATABASE_URL` | `pg0://hindsight-shared:5488` | Data in `~/.pg0/instances/hindsight-shared/`. Or a `postgresql://` URL |
| `HINDSIGHT_API_MCP_ENABLED_TOOLS` | `retain,recall,reflect,list_memories,invalidate_memory` | Only for the server's own `/mcp` endpoint; the plugin uses the REST API |

The plugin's settings (bank routing, what to inject, survey options) are in `~/.hindsight/coding-agent.json`;
see the [plugin docs](https://hindsight.vectorize.io/sdks/integrations/coding-agents). This setup changes one of
them, `autoInject: "recall"`, and the install guide explains why.

## Security

- The API and the UI have **no authentication**. They bind to `127.0.0.1` and must stay there, since anything that
  can reach the ports can read and write memories. CI checks that the server can't be reached on a non-loopback
  address.
- Memories, and whole session transcripts sent by the plugin, are stored in plaintext in the local Postgres.
  Avoid pasting secrets into sessions.
- The daemons keep only a stable `PATH` and `HINDSIGHT_*` variables from your environment.

See [SECURITY.md](SECURITY.md).

## Development

```bash
git clone https://github.com/ShmuelOps/hindsight-shared-memory && cd hindsight-shared-memory
uv sync
uv run pytest     # unit tests, plus a real server (LLM "none") checked for sharing and isolation over MCP
uv run ruff check . && uv run ruff format --check .
```

CI runs on Ubuntu and macOS. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). Hindsight is MIT-licensed by Vectorize.
