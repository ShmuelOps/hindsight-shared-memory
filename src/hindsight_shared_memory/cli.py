"""One local Hindsight server, shared by all your agents. No API key, localhost only."""

import argparse
import importlib.metadata
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Every default can be overridden by setting the same variable in the environment.
DEFAULTS = {
    "HINDSIGHT_API_HOST": "127.0.0.1",  # upstream default is 0.0.0.0
    "HINDSIGHT_API_PORT": "8888",
    # Uses your Claude Code login (Pro/Max subscription); no API key.
    "HINDSIGHT_API_LLM_PROVIDER": "claude-code",
    "HINDSIGHT_API_LLM_MODEL": "claude-haiku-4-5",
    # ONNX embeddings + FlashRank reranker: no PyTorch.
    "HINDSIGHT_API_EMBEDDINGS_PROVIDER": "onnx",
    "HINDSIGHT_API_RERANKER_PROVIDER": "flashrank",
    # FlashRank caches in /tmp by default, which macOS wipes on reboot -> re-download every login.
    "HINDSIGHT_API_RERANKER_FLASHRANK_CACHE_DIR": str(
        Path.home() / ".cache/hindsight-shared-memory/flashrank"
    ),
    # Embedded Postgres on a non-default port so it can't clash with a local Postgres on 5432.
    "HINDSIGHT_API_DATABASE_URL": "pg0://hindsight-shared:5488",
    # Just the memory tools; hides destructive ones like delete_bank / clear_memories.
    "HINDSIGHT_API_MCP_ENABLED_TOOLS": "retain,recall,reflect,list_memories,invalidate_memory",
    "HINDSIGHT_API_LOG_LEVEL": "warning",
}

SERVER, UI = "hindsight-shared-memory", "hindsight-ui"
UI_PORT_DEFAULT = "9999"
# Always on the service PATH (Homebrew on Apple Silicon/Intel, then system dirs).
STANDARD_PATH = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin"]
_TEMP_PREFIXES = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")


def label(name: str) -> str:
    return f"io.github.shmuelops.{name}"


def plist_path(name: str) -> Path:
    return Path.home() / "Library/LaunchAgents" / f"{label(name)}.plist"


def log_path(name: str) -> Path:
    return Path.home() / "Library/Logs" / f"{name}.log"


def unit_path(name: str) -> Path:
    return Path.home() / ".config/systemd/user" / f"{name}.service"


def apply_defaults(env: dict) -> dict:
    for key, value in DEFAULTS.items():
        env.setdefault(key, value)
    return env


def _is_temp(directory: str) -> bool:
    prefixes = (*_TEMP_PREFIXES, tempfile.gettempdir().rstrip("/") + "/")
    candidates = (directory, os.path.realpath(directory))
    return any((d.rstrip("/") + "/").startswith(p) for d in candidates for p in prefixes)


def stable_path(path: str) -> str:
    """PATH for a login service: drop temp dirs, add standard dirs, dedupe.

    Terminals and agent sessions (e.g. Claude Code) often prepend per-session shim dirs under
    the temp dir. Baked into a service they vanish or hang, so the `claude` CLI must come from
    a stable location.
    """
    dirs = [d for d in path.split(os.pathsep) if d and not _is_temp(d)] + STANDARD_PATH
    return os.pathsep.join(dict.fromkeys(dirs))


def service_env(env: dict) -> dict:
    """Env baked into the service: a stable PATH (to find `claude`/`npx`) + HINDSIGHT_* vars."""
    keep = {k: v for k, v in env.items() if k.startswith("HINDSIGHT_")}
    keep["PATH"] = stable_path(env.get("PATH", ""))
    return keep


def server_args() -> list[str]:
    return [sys.executable, "-m", "hindsight_shared_memory", "serve"]


def ui_args(env: dict) -> list[str]:
    """Hindsight Control Plane via npx, pinned to the installed server version, localhost only."""
    npx = shutil.which("npx", path=stable_path(env.get("PATH", "")))
    if not npx:
        sys.exit("npx not found. Install Node.js first: brew install node")
    version = importlib.metadata.version("hindsight-api-slim")
    api_port = env.get("HINDSIGHT_API_PORT", DEFAULTS["HINDSIGHT_API_PORT"])
    return [
        npx,
        "-y",
        f"@vectorize-io/hindsight-control-plane@{version}",
        "--port",
        env.get("HINDSIGHT_UI_PORT", UI_PORT_DEFAULT),
        "--hostname",
        "127.0.0.1",  # the UI has no login; upstream default is 0.0.0.0
        "--api-url",
        f"http://127.0.0.1:{api_port}",
    ]


def render_plist(name: str, args: list[str], env: dict) -> bytes:
    return plistlib.dumps(
        {
            "Label": label(name),
            "ProgramArguments": args,
            "EnvironmentVariables": service_env(env),
            "RunAtLoad": True,
            "KeepAlive": True,
            "StandardOutPath": str(log_path(name)),
            "StandardErrorPath": str(log_path(name)),
        }
    )


def render_systemd(name: str, args: list[str], env: dict) -> str:
    envs = "\n".join(f'Environment="{k}={v}"' for k, v in sorted(service_env(env).items()))
    return (
        f"[Unit]\nDescription={name}\n\n"
        f"[Service]\nExecStart={' '.join(args)}\n{envs}\n"
        "Restart=on-failure\n\n[Install]\nWantedBy=default.target\n"
    )


def hf_cached(repo: str, filename: str, env: dict) -> bool:
    """True if `filename` of model `repo` is in the Hugging Face cache (default layout)."""
    home = env.get("HF_HOME", str(Path.home() / ".cache/huggingface"))
    hub = Path(env.get("HF_HUB_CACHE", Path(home) / "hub"))
    return any((hub / f"models--{repo.replace('/', '--')}" / "snapshots").glob(f"*/{filename}"))


def use_cached_models_offline(env: dict) -> None:
    """Skip Hugging Face update checks once the embedding model is cached.

    Without this every start calls huggingface.co first: the daemon can't come up offline, and
    on networks with broken IPv6 it stalls for minutes trying each IPv6 address in turn.
    """
    if "HF_HUB_OFFLINE" in env or env.get("HINDSIGHT_API_EMBEDDINGS_PROVIDER") != "onnx":
        return
    from hindsight_api.config import (
        DEFAULT_EMBEDDINGS_ONNX_FILE,
        DEFAULT_EMBEDDINGS_ONNX_MODEL_ID,
        ENV_EMBEDDINGS_ONNX_FILE,
        ENV_EMBEDDINGS_ONNX_MODEL_ID,
    )

    repo = env.get(ENV_EMBEDDINGS_ONNX_MODEL_ID, DEFAULT_EMBEDDINGS_ONNX_MODEL_ID)
    filename = env.get(ENV_EMBEDDINGS_ONNX_FILE, DEFAULT_EMBEDDINGS_ONNX_FILE)
    # Look on disk rather than importing huggingface_hub: it reads HF_HUB_OFFLINE at import time.
    if hf_cached(repo, filename, env):
        env["HF_HUB_OFFLINE"] = "1"


def serve() -> None:
    apply_defaults(os.environ)
    use_cached_models_offline(os.environ)
    from hindsight_api.main import main as api_main

    sys.argv = [sys.argv[0]]  # hindsight-api parses argv itself; config comes from env
    api_main()


def _run(*cmd: str, check: bool = True) -> None:
    # Best-effort calls (check=False) are cleanup, e.g. unloading a service that isn't loaded.
    subprocess.run(cmd, check=check, stderr=None if check else subprocess.DEVNULL)


def install(name: str, args: list[str]) -> None:
    env = dict(os.environ)
    system = platform.system()
    uninstall(name, quiet=True)
    if system == "Darwin":
        plist_path(name).parent.mkdir(parents=True, exist_ok=True)
        log_path(name).parent.mkdir(parents=True, exist_ok=True)
        plist_path(name).write_bytes(render_plist(name, args, env))
        _run("launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path(name)))
        print(f"Installed {plist_path(name)}\nLogs: {log_path(name)}")
    elif system == "Linux":
        unit_path(name).parent.mkdir(parents=True, exist_ok=True)
        unit_path(name).write_text(render_systemd(name, args, env))
        _run("systemctl", "--user", "daemon-reload")
        _run("systemctl", "--user", "enable", "--now", unit_path(name).name)
        print(f"Installed {unit_path(name)}\nLogs: journalctl --user -u {name} -f")
    else:
        sys.exit(f"Unsupported OS {system}: run the command in a terminal instead.")


def _launchd_loaded(name: str) -> bool:
    target = f"gui/{os.getuid()}/{label(name)}"
    return subprocess.run(["launchctl", "print", target], capture_output=True).returncode == 0


def uninstall(name: str, quiet: bool = False) -> None:
    system = platform.system()
    if system == "Darwin" and plist_path(name).exists():
        _run("launchctl", "bootout", f"gui/{os.getuid()}/{label(name)}", check=False)
        # bootout returns before the job is gone; bootstrapping again too soon fails with
        # "Bootstrap failed: 5: Input/output error" (e.g. re-running install-service to update).
        deadline = time.monotonic() + 30
        while _launchd_loaded(name) and time.monotonic() < deadline:
            time.sleep(0.5)
        plist_path(name).unlink()
    elif system == "Linux" and unit_path(name).exists():
        _run("systemctl", "--user", "disable", "--now", unit_path(name).name, check=False)
        unit_path(name).unlink()
        _run("systemctl", "--user", "daemon-reload")
    if not quiet:
        print(f"Removed the {name} service.")


def install_service() -> None:
    env = apply_defaults(dict(os.environ))
    if env["HINDSIGHT_API_LLM_PROVIDER"] == "claude-code" and not shutil.which(
        "claude", path=stable_path(env.get("PATH", ""))
    ):
        sys.exit("`claude` CLI not found on a stable PATH. Install Claude Code and log in first.")
    install(SERVER, server_args())
    print(f"Server: http://127.0.0.1:{env['HINDSIGHT_API_PORT']} (first start takes ~1 minute)")


def install_ui() -> None:
    args = ui_args(dict(os.environ))
    install(UI, args)
    print(f"UI: http://127.0.0.1:{args[args.index('--port') + 1]}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="hindsight-shared-memory", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    commands = {
        "serve": ("run the server in the foreground", serve),
        "install-service": ("run the server in the background at login", install_service),
        "uninstall-service": (
            "remove the server service (memories are kept)",
            lambda: uninstall(SERVER),
        ),
        "install-ui": ("run the web UI in the background at login (needs Node.js)", install_ui),
        "uninstall-ui": ("remove the web UI service", lambda: uninstall(UI)),
    }
    for command, (help_text, _) in commands.items():
        sub.add_parser(command, help=help_text)
    commands[parser.parse_args().command][1]()
