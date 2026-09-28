#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --locked --python 3.12 --extra dev
uv run playwright install chromium
mkdir -p evidence/verification
uv run ruff check src tests
uv run pytest -q --junitxml=evidence/verification/pytest.xml
