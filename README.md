# hindsight-shared-memory

[![CI](https://github.com/ShmuelOps/hindsight-shared-memory/actions/workflows/ci.yml/badge.svg)](https://github.com/ShmuelOps/hindsight-shared-memory/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**One local memory server that all your agents share.** Built on
[Hindsight](https://github.com/vectorize-io/hindsight). Every Claude Code session, subagent, and MCP client on your
machine reads and writes the same long-term memory, over MCP, on `localhost`.

- **No API key.** Fact extraction runs through your existing Claude Code login (Pro/Max) via Hindsight's
  `claude-code` provider.
- **Shared by design.** A single HTTP server replaces a separate memory process per session. Agent A retains a
  fact and agent B recalls it seconds later, even while both are running.
- **Local and private.** The server binds to `127.0.0.1` only (upstream defaults to `0.0.0.0`), with an embedded
  Postgres and local ONNX embeddings and reranking.
- **Light.** Uses Hindsight's slim build, with no PyTorch (about 0.8 GB instead of 1.8 GB).
- **Safe tool set.** Agents get only the memory tools: no `delete_bank` or `clear_memories`.
- **Always on.** One command installs a launchd or systemd login service.

👉 **[Install guide](INSTALL.md)** (5 minutes), including the optional always-on web UI.

## How it works

```
 Claude Code session 1 ─┐
 Claude Code session 2 ─┼─ MCP over HTTP ─▶ hindsight-shared-memory (127.0.0.1:8888)
 subagents / other MCP ─┘   /mcp/<bank>/        │  Hindsight API
                                                ├─ LLM: claude-code (your Claude login) → fact extraction
                                                ├─ ONNX embeddings + FlashRank reranker (local)
                                                └─ embedded Postgres (pg0, 127.0.0.1:5488)
 Web UI (optional) ─────── 127.0.0.1:9999 ──────┘
```

Hindsight doesn't only store text. On `retain` it extracts atomic facts, entities, and time information, then
consolidates them into observations. `recall` combines semantic, keyword, graph, and temporal search with
reranking. `reflect` answers questions by reasoning across memories.

## Tools exposed to agents

| Tool | What it does |
|------|--------------|
| `retain` | Stores content. Returns immediately; facts are extracted in the background (usually within seconds) |
| `recall` | Multi-strategy search that returns ranked facts |
| `reflect` | Reasons over the bank to answer a question |
| `list_memories` | Browses stored memories |
| `invalidate_memory` | Retires a wrong or stale memory |

Want more of Hindsight's ~35 MCP tools? Set `HINDSIGHT_API_MCP_ENABLED_TOOLS` (see below).

## Banks: sharing vs. isolation

The bank is the last part of the MCP URL. Agents on the same bank share memory; different banks are fully
isolated.

```bash
# everyone shares one memory (default in the install guide)
claude mcp add --transport http -s user    hindsight http://127.0.0.1:8888/mcp/shared/
# a project with its own memory (stored in the repo's .mcp.json)
claude mcp add --transport http -s project hindsight http://127.0.0.1:8888/mcp/my-project/
```

## Configuration

Every setting is a Hindsight environment variable. Set it before `serve`, or before `install-service`, which
bakes your `HINDSIGHT_*` variables into the service.

| Variable | Default here | Notes |
|----------|--------------|-------|
| `HINDSIGHT_API_HOST` | `127.0.0.1` | Upstream default is `0.0.0.0` |
| `HINDSIGHT_API_PORT` | `8888` | |
| `HINDSIGHT_API_LLM_PROVIDER` | `claude-code` | Or `ollama`, `openai`, `anthropic`, … or `none` (storage and search only, no LLM) |
| `HINDSIGHT_API_LLM_MODEL` | `claude-haiku-4-5` | Fast extraction. Sonnet is more thorough but slower (~30 s per retain) |
| `HINDSIGHT_API_EMBEDDINGS_PROVIDER` | `onnx` | Model `BAAI/bge-small-en-v1.5` |
| `HINDSIGHT_API_RERANKER_PROVIDER` | `flashrank` | |
| `HINDSIGHT_API_DATABASE_URL` | `pg0://hindsight-shared:5488` | Embedded Postgres, data in `~/.pg0/instances/hindsight-shared/`. Or a `postgresql://` URL |
| `HINDSIGHT_API_MCP_ENABLED_TOOLS` | `retain,recall,reflect,list_memories,invalidate_memory` | Comma-separated allowlist |
| `HINDSIGHT_API_LOG_LEVEL` | `warning` | |

Example: run on another port with Ollama:

```bash
HINDSIGHT_API_PORT=9888 HINDSIGHT_API_LLM_PROVIDER=ollama HINDSIGHT_API_LLM_MODEL=llama3.1 \
  hindsight-shared-memory install-service
```

## Compared with the official Claude Code plugin

Hindsight ships an official [`hindsight-memory` plugin](https://hindsight.vectorize.io/sdks/integrations/claude-code)
that uses hooks to auto-recall on every prompt and auto-retain after every response. Use that if you want fully
automatic memory. This project is the **explicit, MCP-only** alternative: agents decide what to retain, so
background LLM calls on your subscription stay low. It adds a hardened always-on server that any MCP client can
share.

## Security

- The API and the optional UI have **no authentication**. They bind to `127.0.0.1` and must stay there. Anything
  that can reach the port can read and write memories. For auth, see Hindsight's
  [tenant API key extension](https://hindsight.vectorize.io/developer/mcp-server).
- Memories are stored in plaintext in Postgres. Don't retain secrets.
- The service keeps only `PATH` and `HINDSIGHT_*` variables from your environment.

See [SECURITY.md](SECURITY.md).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `claude mcp list` shows the server as failed | Check `curl http://127.0.0.1:8888/health`, then the logs: `~/Library/Logs/hindsight-shared-memory.log` or `journalctl --user -u hindsight-shared-memory` |
| Retained memory doesn't show up in `recall` | Extraction is asynchronous. Wait a few seconds, or check `http://127.0.0.1:8888/v1/default/banks/<bank>/operations` |
| `claude-code` provider errors | Run `claude` once in a terminal to make sure you're logged in |
| Port 8888 or 5488 already in use | Set `HINDSIGHT_API_PORT`, or `HINDSIGHT_API_DATABASE_URL=pg0://hindsight-shared:<port>` |

## Development

```bash
git clone https://github.com/ShmuelOps/hindsight-shared-memory && cd hindsight-shared-memory
uv sync
uv run pytest     # boots a real server (LLM provider "none") and checks sharing and isolation over MCP
uv run ruff check . && uv run ruff format --check .
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE). Hindsight is MIT-licensed by Vectorize.
