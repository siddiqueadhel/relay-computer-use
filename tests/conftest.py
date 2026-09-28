import socket

import pytest

from relay.bank import create_bank
from relay.example import example_capability
from relay.runtime import RunManager, serve


@pytest.fixture
def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def bank(unused_port):
    app = create_bank()
    async with serve(app, unused_port):
        yield app, f"http://127.0.0.1:{unused_port}"


@pytest.fixture
async def manager(bank, tmp_path):
    _, url = bank
    instance = RunManager(
        target_url=url,
        evidence_root=tmp_path,
        capability=example_capability(),
        intervention_timeout=1,
        total_timeout=30,
    )
    yield instance
    await instance.close()
