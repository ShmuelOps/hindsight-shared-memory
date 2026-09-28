# Install guide

Five minutes, no API key. Works on macOS and Linux.

## 1. Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Claude Code](https://docs.claude.com/en/docs/claude-code), logged in with a Pro/Max plan (`claude` works in your
  terminal). The server borrows this login to extract facts, so it needs no API key.

## 2. Install

```bash
uv tool install git+https://github.com/ShmuelOps/hindsight-shared-memory
```

This puts `hindsight-shared-memory` on your PATH (usually `~/.local/bin`).

## 3. Start the server (always on)

```bash
hindsight-shared-memory install-service
```

This registers a login service (launchd on macOS, `systemd --user` on Linux) that starts at login and restarts
if it crashes.

The first start downloads a small embedding model and a reranker, which takes about a minute. Check it's up:

```bash
curl http://127.0.0.1:8888/health    # {"status":"healthy",...}
```

<details>
<summary>Prefer not to install a service?</summary>

Run it in a terminal instead and leave that terminal open:

```bash
hindsight-shared-memory serve
```

</details>

## 4. Connect Claude Code

```bash
claude mcp add --transport http -s user hindsight http://127.0.0.1:8888/mcp/shared/
claude mcp list    # hindsight: ... ✔ Connected
```

`shared` is the **bank**: every agent that uses the same URL shares one memory. To give a project its own
memory, point it at a different bank, e.g. `.../mcp/my-project/` with `-s project`.

## 5. Tell Claude when to use it

Add to `~/.claude/CLAUDE.md`:

```markdown
## Long-term memory (Hindsight MCP, shared by all agents)
- At the start of a non-trivial task, call `recall` with the task topic.
- When you learn a durable fact (user preference, project decision, gotcha), `retain` it as one
  specific, self-contained statement. Hindsight extracts and consolidates facts itself.
- Use `reflect` for questions that need reasoning across many memories.
- `invalidate_memory` entries that turn out wrong or stale.
```

Restart Claude Code. You're done.

---

## Optional: the web UI

Hindsight's **Control Plane** lets you browse banks and memories, explore entities, and test recall queries.
It needs [Node.js](https://nodejs.org/) (for `npx`).

### Run it once

```bash
npx -y @vectorize-io/hindsight-control-plane@0.10.1 \
  --port 9999 --hostname 127.0.0.1 --api-url http://127.0.0.1:8888
```

Open <http://127.0.0.1:9999>.

> Always pass `--hostname 127.0.0.1`. The UI has no login and binds to `0.0.0.0` (your whole network) by
> default. Keep its version in line with the server's `hindsight-api` version.

### Keep the UI always on: macOS (launchd)

```bash
NPX="$(command -v npx)"
cat > ~/Library/LaunchAgents/io.github.shmuelops.hindsight-ui.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>io.github.shmuelops.hindsight-ui</string>
  <key>ProgramArguments</key>
  <array>
    <string>$NPX</string><string>-y</string>
    <string>@vectorize-io/hindsight-control-plane@0.10.1</string>
    <string>--port</string><string>9999</string>
    <string>--hostname</string><string>127.0.0.1</string>
    <string>--api-url</string><string>http://127.0.0.1:8888</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$PATH</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/hindsight-ui.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/hindsight-ui.log</string>
</dict>
</plist>
EOF
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/io.github.shmuelops.hindsight-ui.plist
```

To remove it:

```bash
launchctl bootout "gui/$(id -u)/io.github.shmuelops.hindsight-ui"
rm ~/Library/LaunchAgents/io.github.shmuelops.hindsight-ui.plist
```

### Keep the UI always on: Linux (systemd --user)

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/hindsight-ui.service <<EOF
[Unit]
Description=Hindsight Control Plane UI
After=hindsight-shared-memory.service

[Service]
ExecStart=$(command -v npx) -y @vectorize-io/hindsight-control-plane@0.10.1 --port 9999 --hostname 127.0.0.1 --api-url http://127.0.0.1:8888
Environment="PATH=$PATH"
Restart=on-failure

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload && systemctl --user enable --now hindsight-ui
```

To remove it: `systemctl --user disable --now hindsight-ui && rm ~/.config/systemd/user/hindsight-ui.service`.

To keep both services running after you log out, run `loginctl enable-linger "$USER"`.

---

## Update

```bash
uv tool upgrade hindsight-shared-memory
hindsight-shared-memory install-service   # reinstalls the service on the new version
```

## Uninstall

```bash
hindsight-shared-memory uninstall-service
claude mcp remove hindsight -s user
uv tool uninstall hindsight-shared-memory
```

Memories stay in `~/.pg0/instances/hindsight-shared/`. Delete that folder to wipe them.
