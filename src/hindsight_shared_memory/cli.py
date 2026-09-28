"""One local Hindsight server, shared by all your agents. No API key, localhost only."""

import argparse
import os
import platform
import plistlib
import subprocess
import sys
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
    # Embedded Postgres on a non-default port so it can't clash with a local Postgres on 5432.
    "HINDSIGHT_API_DATABASE_URL": "pg0://hindsight-shared:5488",
    # Just the memory tools; hides destructive ones like delete_bank / clear_memories.
    "HINDSIGHT_API_MCP_ENABLED_TOOLS": "retain,recall,reflect,list_memories,invalidate_memory",
    "HINDSIGHT_API_LOG_LEVEL": "warning",
}

LABEL = "io.github.shmuelops.hindsight-shared-memory"
PLIST_PATH = Path.home() / "Library/LaunchAgents" / f"{LABEL}.plist"
LOG_PATH = Path.home() / "Library/Logs/hindsight-shared-memory.log"
UNIT_PATH = Path.home() / ".config/systemd/user/hindsight-shared-memory.service"


def apply_defaults(env: dict) -> dict:
    for key, value in DEFAULTS.items():
        env.setdefault(key, value)
    return env


def service_env(env: dict) -> dict:
    """Env baked into the service: PATH (to find the `claude` CLI) + HINDSIGHT_* overrides."""
    keep = {k: v for k, v in env.items() if k.startswith("HINDSIGHT_")}
    keep["PATH"] = env.get("PATH", "/usr/bin:/bin")
    return keep


def program_args() -> list[str]:
    return [sys.executable, "-m", "hindsight_shared_memory", "serve"]


def render_plist(env: dict) -> bytes:
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": program_args(),
            "EnvironmentVariables": service_env(env),
            "RunAtLoad": True,
            "KeepAlive": True,
            "StandardOutPath": str(LOG_PATH),
            "StandardErrorPath": str(LOG_PATH),
        }
    )


def render_systemd(env: dict) -> str:
    envs = "\n".join(f'Environment="{k}={v}"' for k, v in sorted(service_env(env).items()))
    return (
        "[Unit]\nDescription=Hindsight shared agent memory\n\n"
        f"[Service]\nExecStart={' '.join(program_args())}\n{envs}\n"
        "Restart=on-failure\n\n[Install]\nWantedBy=default.target\n"
    )


def serve() -> None:
    apply_defaults(os.environ)
    from hindsight_api.main import main as api_main

    sys.argv = [sys.argv[0]]  # hindsight-api parses argv itself; config comes from env
    api_main()


def _run(*cmd: str, check: bool = True) -> None:
    subprocess.run(cmd, check=check)


def install_service() -> None:
    system = platform.system()
    if system == "Darwin":
        uninstall_service(quiet=True)
        PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        PLIST_PATH.write_bytes(render_plist(dict(os.environ)))
        _run("launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST_PATH))
        print(f"Installed {PLIST_PATH}\nLogs: {LOG_PATH}")
    elif system == "Linux":
        UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        UNIT_PATH.write_text(render_systemd(dict(os.environ)))
        _run("systemctl", "--user", "daemon-reload")
        _run("systemctl", "--user", "enable", "--now", UNIT_PATH.name)
        print(f"Installed {UNIT_PATH}\nLogs: journalctl --user -u {UNIT_PATH.stem} -f")
    else:
        sys.exit(f"Unsupported OS {system}: run `hindsight-shared-memory serve` yourself.")
    port = os.environ.get("HINDSIGHT_API_PORT", DEFAULTS["HINDSIGHT_API_PORT"])
    print(f"Server: http://127.0.0.1:{port} (first start downloads models, give it a minute)")


def uninstall_service(quiet: bool = False) -> None:
    system = platform.system()
    if system == "Darwin":
        if PLIST_PATH.exists():
            _run("launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}", check=False)
            PLIST_PATH.unlink()
    elif system == "Linux" and UNIT_PATH.exists():
        _run("systemctl", "--user", "disable", "--now", UNIT_PATH.name, check=False)
        UNIT_PATH.unlink()
        _run("systemctl", "--user", "daemon-reload")
    if not quiet:
        print("Service removed. Memories are kept in ~/.pg0/instances/hindsight-shared.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="hindsight-shared-memory", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run the server in the foreground")
    sub.add_parser("install-service", help="run it in the background at login (launchd/systemd)")
    sub.add_parser("uninstall-service", help="remove the background service")
    command = parser.parse_args().command
    {"serve": serve, "install-service": install_service, "uninstall-service": uninstall_service}[
        command
    ]()
