"""Bounded, redacted audit events. No transcripts, cookies, raw DOMs, or trace archives."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any


class Redactor:
    def __init__(self, private_values: list[str] = ()):
        self.private_values = sorted(
            {str(v) for v in private_values if str(v)}, key=len, reverse=True
        )

    def add_private(self, value: Any) -> None:
        if str(value) and str(value) not in self.private_values:
            self.private_values.append(str(value))
            self.private_values.sort(key=len, reverse=True)

    def text(self, text: str) -> str:
        for value in self.private_values:
            text = text.replace(value, "[REDACTED]")
        text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[EMAIL]", text)
        text = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[SSN]", text)
        text = re.sub(r"\b(?:sk-|xpl_|Bearer\s+)[A-Za-z0-9_\-]{8,}", "[SECRET]", text)
        return text

    def clean(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {
                str(k): (
                    "[SECRET]"
                    if re.search(
                        r"password|secret|api_key|cookie|authorization|(?:^|_)token$|(?:access|refresh|session)_token",
                        str(k),
                        re.I,
                    )
                    else self.clean(v)
                )
                for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self.clean(v) for v in value]
        if isinstance(value, (int, float)) and str(value) in self.private_values:
            return "[REDACTED]"
        return value


class Journal:
    def __init__(self, root: Path, redactor: Redactor, *, mode: str, run_id: str | None = None):
        self.run_id = run_id or f"{mode}-{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"
        self.directory = root / self.run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.redactor = redactor
        self.events: list[dict] = []
        self.started = time.monotonic()
        self.path = self.directory / "events.jsonl"
        self.emit("run_started", mode=mode, evidence_policy="redacted; no raw model transcript")

    def emit(self, event: str, **data: Any) -> dict:
        # Result duration excludes browser startup; journal time must not be overwritten.
        if "elapsed_ms" in data:
            data["workflow_elapsed_ms"] = data.pop("elapsed_ms")
        entry = {
            **self.redactor.clean(data),
            "seq": len(self.events),
            "elapsed_ms": round((time.monotonic() - self.started) * 1000),
            "event": event,
        }
        self.events.append(entry)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def save_json(self, name: str, data: Any) -> None:
        if Path(name).name != name:
            raise ValueError("evidence name must be a basename")
        (self.directory / name).write_text(json.dumps(self.redactor.clean(data), indent=2) + "\n")

    def digest(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()
