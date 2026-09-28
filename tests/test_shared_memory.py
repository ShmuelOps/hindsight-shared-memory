"""End-to-end: boot the real server, then check that separate MCP sessions share one memory bank.

Runs with LLM provider `none` so CI needs no credentials. Retain then stores chunks
instead of extracting facts, but storage, recall and sharing are the same code path.
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from hindsight_shared_memory import cli

EXPECTED_TOOLS = set(cli.DEFAULTS["HINDSIGHT_API_MCP_ENABLED_TOOLS"].split(","))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    port, pg_port = _free_port(), _free_port()
    instance = f"hss-test-{uuid.uuid4().hex[:8]}"
    env = {
        **os.environ,
        "HINDSIGHT_API_PORT": str(port),
        "HINDSIGHT_API_LLM_PROVIDER": "none",
        "HINDSIGHT_API_DATABASE_URL": f"pg0://{instance}:{pg_port}",
    }
    log = (tmp_path_factory.mktemp("server") / "server.log").open("w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "hindsight_shared_memory", "serve"],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 600  # first run downloads the embedding + reranker models
    while True:
        try:
            urllib.request.urlopen(f"{base}/health", timeout=2)
            break
        except OSError:
            if proc.poll() is not None or time.time() > deadline:
                proc.kill()
                pytest.fail(f"server did not start, see {log.name}")
            time.sleep(1)
    yield base, port
    proc.terminate()
    proc.wait(timeout=60)
    import pg0

    pg0.drop(instance)


async def _session_call(url: str, tool: str | None = None, args: dict | None = None):
    """Open a fresh MCP session (= one independent agent), optionally call a tool."""
    async with streamable_http_client(url) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        if tool is None:
            return {t.name for t in (await s.list_tools()).tools}
        res = await s.call_tool(tool, args or {})
        assert not res.is_error, res.content
        return res.content[0].text


def test_binds_to_localhost_only(server):
    _, port = server
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.connect(("10.255.255.255", 1))  # picks the outbound interface; sends nothing
        lan_ip = udp.getsockname()[0]
    if lan_ip.startswith("127."):
        pytest.skip("no non-loopback address to probe")
    with socket.socket() as s, pytest.raises(OSError):
        s.settimeout(2)
        s.connect((lan_ip, port))


def test_only_safe_tools_exposed(server):
    base, _ = server
    assert asyncio.run(_session_call(f"{base}/mcp/any-bank/")) == EXPECTED_TOOLS


def test_agents_share_a_bank_and_banks_are_isolated(server):
    base, _ = server
    bank = f"{base}/mcp/team-{uuid.uuid4().hex[:6]}/"
    other_bank = f"{base}/mcp/other-{uuid.uuid4().hex[:6]}/"

    async def scenario():
        # Two agents write at the same time, each through its own session.
        facts = [
            "Agent A: staging DB is Aurora staging-db-1.",
            "Agent B: staging deploys freeze Fridays.",
        ]
        await asyncio.gather(*(_session_call(bank, "retain", {"content": f}) for f in facts))
        # A third agent sees both. retain is async, so poll until indexed.
        for _ in range(60):
            text = await _session_call(bank, "recall", {"query": "staging database and deploys"})
            found = " ".join(r["text"] for r in json.loads(text)["results"])
            if "Aurora" in found and "Friday" in found:
                break
            await asyncio.sleep(2)
        else:
            pytest.fail(f"third agent never saw both memories: {found!r}")
        # A different bank sees nothing.
        text = await _session_call(other_bank, "recall", {"query": "staging database and deploys"})
        assert json.loads(text)["results"] == []

    asyncio.run(scenario())
