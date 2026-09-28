"""Entry-point handling without starting browsers or making network requests."""

from urllib.parse import parse_qsl, urlsplit

import pytest

from relay.example import example_capability
from relay.runtime import RunManager


@pytest.mark.parametrize(
    "entry",
    [
        "http://127.0.0.1:8765",
        "http://127.0.0.1:8765/?tenant=alpha&tag=a&tag=b&empty=",
        "http://127.0.0.1:8765/workspace?tenant=alpha%20beta#review",
        "http://127.0.0.1:8765/?scenario=slow&variant=old&tenant=alpha",
    ],
)
async def test_target_preserves_path_query_and_fragment(tmp_path, entry):
    class CaptureEntry(RunManager):
        async def _execute(self, current, url, inputs, goal, model):
            return url

    manager = CaptureEntry(
        target_url=entry, evidence_root=tmp_path, capability=example_capability()
    )
    actual = await manager.start(
        dict(member_id="12345", account_type="savings", nickname="Test only"),
        scenario="permission_denied",
        variant="other",
    )
    supplied, resolved = urlsplit(entry), urlsplit(actual)
    assert (resolved.scheme, resolved.netloc) == (supplied.scheme, supplied.netloc)
    assert resolved.path == (supplied.path or "/")
    assert resolved.fragment == supplied.fragment
    original = [
        (key, value)
        for key, value in parse_qsl(supplied.query, keep_blank_values=True)
        if key not in {"scenario", "variant"}
    ]
    assert parse_qsl(resolved.query, keep_blank_values=True) == original + [
        ("scenario", "permission_denied"),
        ("variant", "other"),
    ]


def test_cli_ctrl_c_shuts_down_without_nested_server_tracebacks(unused_port):
    import os
    import select
    import signal
    import subprocess
    import sys

    process = subprocess.Popen(
        [sys.executable, "-m", "relay.cli", "bank", "--bank-port", str(unused_port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    try:
        assert select.select([process.stdout], [], [], 10)[0], "Server did not start"
        assert "Northstar demo:" in process.stdout.readline()
        process.send_signal(signal.SIGINT)
        _, stderr = process.communicate(timeout=10)
        assert process.returncode == 130
        assert "Traceback" not in stderr
        assert "ERROR" not in stderr
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
