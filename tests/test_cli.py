"""Unit tests for defaults, PATH handling and service rendering (no server needed)."""

import os
import plistlib
import stat
import subprocess
import sys

import pytest

from hindsight_shared_memory import cli

SHIM = "/var/folders/gw/abc/T//cmux-cli-shims/8B66DA8B/claude-dir"


def test_defaults_are_local_and_keyless():
    env = cli.apply_defaults({})
    assert env["HINDSIGHT_API_HOST"] == "127.0.0.1"
    assert env["HINDSIGHT_API_LLM_PROVIDER"] == "claude-code"
    assert "HINDSIGHT_API_LLM_API_KEY" not in env
    tools = env["HINDSIGHT_API_MCP_ENABLED_TOOLS"].split(",")
    assert "delete_bank" not in tools and "clear_memories" not in tools


def test_user_overrides_win():
    env = cli.apply_defaults({"HINDSIGHT_API_PORT": "9000", "HINDSIGHT_API_LLM_PROVIDER": "ollama"})
    assert env["HINDSIGHT_API_PORT"] == "9000"
    assert env["HINDSIGHT_API_LLM_PROVIDER"] == "ollama"


def test_stable_path_drops_session_shims_and_adds_standard_dirs():
    # Regression: a PATH captured inside a Claude Code session starts with a temp shim dir that
    # disappears when the session ends, leaving the daemon without a working `claude`.
    path = cli.stable_path(f"{SHIM}:/tmp/x:/Users/me/.local/bin:/opt/homebrew/bin")
    dirs = path.split(":")
    assert not any(d.startswith(("/var/folders", "/tmp")) for d in dirs)
    assert dirs[0] == "/Users/me/.local/bin"
    assert dirs.count("/opt/homebrew/bin") == 1
    assert "/usr/bin" in dirs and "/bin" in dirs


def test_service_env_keeps_only_stable_path_and_hindsight_vars():
    env = cli.service_env({"PATH": f"{SHIM}:/x", "HINDSIGHT_API_PORT": "9000", "SECRET": "no"})
    assert set(env) == {"PATH", "HINDSIGHT_API_PORT"}
    assert env["PATH"].startswith("/x:") and "cmux" not in env["PATH"]


def test_server_plist_is_valid_and_runs_serve():
    plist = plistlib.loads(cli.render_plist(cli.SERVER, cli.server_args(), {"PATH": "/x"}))
    assert plist["Label"] == "io.github.shmuelops.hindsight-shared-memory"
    assert plist["ProgramArguments"][-3:] == ["-m", "hindsight_shared_memory", "serve"]
    assert plist["KeepAlive"] is True
    assert plist["StandardOutPath"].endswith("Library/Logs/hindsight-shared-memory.log")


def test_systemd_unit_runs_serve():
    unit = cli.render_systemd(cli.SERVER, cli.server_args(), {"HINDSIGHT_API_PORT": "9000"})
    assert unit.split("ExecStart=")[1].split("\n")[0].endswith(" serve")
    assert 'Environment="HINDSIGHT_API_PORT=9000"' in unit
    assert "WantedBy=default.target" in unit


@pytest.fixture
def fake_npx(tmp_path):
    npx = tmp_path / "npx"
    npx.write_text("#!/bin/sh\n")
    npx.chmod(npx.stat().st_mode | stat.S_IEXEC)
    return npx


def test_ui_args_pin_version_and_bind_localhost(fake_npx, monkeypatch):
    import importlib.metadata

    # tmp_path is a temp dir, which stable_path rightly drops, so inject it as a standard dir.
    monkeypatch.setattr(cli, "STANDARD_PATH", [str(fake_npx.parent)])
    args = cli.ui_args({"PATH": "", "HINDSIGHT_API_PORT": "9000"})
    assert args[0] == str(fake_npx)
    version = importlib.metadata.version("hindsight-api-slim")
    assert f"@vectorize-io/hindsight-control-plane@{version}" in args
    assert args[args.index("--hostname") + 1] == "127.0.0.1"
    assert args[args.index("--port") + 1] == "9999"
    assert args[args.index("--api-url") + 1] == "http://127.0.0.1:9000"


def test_ui_args_explain_missing_node(monkeypatch):
    monkeypatch.setattr(cli, "STANDARD_PATH", [])
    with pytest.raises(SystemExit, match="brew install node"):
        cli.ui_args({"PATH": os.devnull})


def test_flashrank_cache_survives_reboot():
    cache = cli.apply_defaults({})["HINDSIGHT_API_RERANKER_FLASHRANK_CACHE_DIR"]
    assert not cli._is_temp(cache)


def _fake_hf_cache(tmp_path, repo="intfloat/multilingual-e5-small", filename="onnx/model.onnx"):
    model = tmp_path / "hub" / f"models--{repo.replace('/', '--')}" / "snapshots" / "abc123"
    (model / filename).parent.mkdir(parents=True)
    (model / filename).write_bytes(b"onnx")
    return {"HF_HUB_CACHE": str(tmp_path / "hub")}


def test_offline_once_embedding_model_is_cached(tmp_path):
    env = cli.apply_defaults(_fake_hf_cache(tmp_path))
    cli.use_cached_models_offline(env)
    assert env["HF_HUB_OFFLINE"] == "1"


def test_online_when_model_not_cached_yet(tmp_path):
    env = cli.apply_defaults({"HF_HUB_CACHE": str(tmp_path / "empty")})
    cli.use_cached_models_offline(env)
    assert "HF_HUB_OFFLINE" not in env


def test_explicit_hf_offline_setting_is_respected(tmp_path):
    env = cli.apply_defaults({**_fake_hf_cache(tmp_path), "HF_HUB_OFFLINE": "0"})
    cli.use_cached_models_offline(env)
    assert env["HF_HUB_OFFLINE"] == "0"


def test_offline_setting_reaches_huggingface_hub(tmp_path):
    # Regression: huggingface_hub reads HF_HUB_OFFLINE once at import, so serve() must set it
    # before anything imports huggingface_hub. Check in a fresh interpreter.
    code = (
        "import os, sys; from hindsight_shared_memory import cli;"
        "cli.apply_defaults(os.environ); cli.use_cached_models_offline(os.environ);"
        "assert 'huggingface_hub' not in sys.modules;"
        "from huggingface_hub import constants; assert constants.HF_HUB_OFFLINE"
    )
    env = {**os.environ, **_fake_hf_cache(tmp_path)}
    env.pop("HF_HUB_OFFLINE", None)
    subprocess.run([sys.executable, "-c", code], env=env, check=True)


def test_reinstall_waits_for_launchd_to_drop_the_old_job(tmp_path, monkeypatch):
    # Regression: re-running install-service (the update path) bootstrapped while the old job
    # was still shutting down, and launchctl failed with "Bootstrap failed: 5".
    plist = tmp_path / "svc.plist"
    plist.write_text("old")
    loaded = iter([True, True, False])
    calls = []
    monkeypatch.setattr(cli.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(cli, "plist_path", lambda name: plist)
    monkeypatch.setattr(cli, "log_path", lambda name: tmp_path / "svc.log")
    monkeypatch.setattr(cli, "_launchd_loaded", lambda name: next(loaded))
    monkeypatch.setattr(cli.time, "sleep", lambda s: calls.append(("sleep",)))
    monkeypatch.setattr(cli, "_run", lambda *cmd, check=True: calls.append(cmd[:2]))

    cli.install(cli.SERVER, ["/bin/true"])

    assert calls == [("launchctl", "bootout"), ("sleep",), ("sleep",), ("launchctl", "bootstrap")]
    assert plistlib.loads(plist.read_bytes())["ProgramArguments"] == ["/bin/true"]
