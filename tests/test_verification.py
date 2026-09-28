import json
import subprocess
import sys

import pytest

from relay.example import example_capability
from relay.verification import cases, verify


def test_replay_guard_blocks_model_imports_and_external_connections():
    code = """
import json, os, socket
from relay.verification import install_replay_guard
os.environ['OPENAI_API_KEY'] = 'synthetic-not-a-credential'
os.environ['EXPLABS_API_KEY'] = 'synthetic-not-a-credential'
counts = install_replay_guard()
assert 'OPENAI_API_KEY' not in os.environ
assert 'EXPLABS_API_KEY' not in os.environ
try:
    import openai
except ImportError:
    pass
else:
    raise AssertionError('model import allowed')
with socket.socket() as sock:
    try:
        sock.connect(('203.0.113.1', 443))
    except PermissionError:
        pass
    else:
        raise AssertionError('external connection allowed')
print(json.dumps(counts))
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "blocked_model_imports": 1,
        "blocked_nonlocal_connections": 1,
    }


def test_verification_matrix_has_fresh_input_variation_and_labeled_handoffs():
    matrix = cases(20)
    assert len(matrix) == 31
    assert len({c["inputs"]["member_id"] for c in matrix[:20]}) == 3
    assert {c["inputs"]["account_type"] for c in matrix[:20]} == {"savings", "money_market"}
    assert sum(c["simulated_operator"] for c in matrix) == 2
    assert matrix[-1]["variant"] == "harbor"


async def test_verification_rejects_authored_provenance_by_default():
    from types import SimpleNamespace

    with pytest.raises(ValueError, match="discovered capability"):
        await verify(
            SimpleNamespace(capability=example_capability()),
            None,
            repeat=1,
            allow_authored=False,
            simulate_operator=None,
        )
