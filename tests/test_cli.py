"""Unit tests for defaults and service rendering (no server needed)."""

import plistlib

from hindsight_shared_memory import cli


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


def test_service_env_keeps_only_path_and_hindsight_vars():
    env = cli.service_env({"PATH": "/x", "HINDSIGHT_API_PORT": "9000", "SECRET_TOKEN": "nope"})
    assert env == {"PATH": "/x", "HINDSIGHT_API_PORT": "9000"}


def test_plist_is_valid_and_runs_serve():
    plist = plistlib.loads(cli.render_plist({"PATH": "/x"}))
    assert plist["Label"] == cli.LABEL
    assert plist["ProgramArguments"][-3:] == ["-m", "hindsight_shared_memory", "serve"]
    assert plist["KeepAlive"] is True
    assert plist["EnvironmentVariables"] == {"PATH": "/x"}


def test_systemd_unit_runs_serve():
    unit = cli.render_systemd({"PATH": "/x", "HINDSIGHT_API_PORT": "9000"})
    assert "ExecStart=" in unit and unit.split("ExecStart=")[1].split("\n")[0].endswith(" serve")
    assert 'Environment="HINDSIGHT_API_PORT=9000"' in unit
    assert "WantedBy=default.target" in unit
