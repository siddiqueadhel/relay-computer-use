"""Exclusive automation/operator ownership of one live session."""

from __future__ import annotations

import asyncio
import uuid
from typing import Literal

from relay.evidence import Journal


class OwnershipError(Exception):
    pass


class SessionControl:
    def __init__(self, journal: Journal):
        self.session_id = uuid.uuid4().hex
        self.owner: Literal["automation", "paused", "human", "finished"] = "automation"
        self.generation = 0
        self.lock = asyncio.Lock()
        self.resumed = asyncio.Event()
        self.abort_requested = asyncio.Event()
        self.journal = journal
        self.request: dict | None = None
        self.handoffs = 0
        self.aborted = False

    def require(self, actor: str) -> None:
        if self.owner != actor:
            raise OwnershipError(f"session is owned by {self.owner}")

    async def pause(
        self, *, reason: str, step_id: str, expected: str, evidence: str | None
    ) -> None:
        async with self.lock:
            self.require("automation")
            self.owner = "paused"
            self.generation += 1
            self.resumed.clear()
            self.request = dict(
                reason=reason, step_id=step_id, expected=expected, evidence=evidence
            )
            self.journal.emit(
                "intervention_requested",
                session_id=self.session_id,
                generation=self.generation,
                **self.request,
            )

    async def claim(self, generation: int) -> None:
        async with self.lock:
            self.require("paused")
            if generation != self.generation:
                raise OwnershipError("stale intervention generation")
            self.owner = "human"
            self.handoffs += 1
            self.journal.emit(
                "control_transferred",
                owner="human",
                session_id=self.session_id,
                generation=self.generation,
            )

    async def resume(self, generation: int) -> None:
        # The engine validates the interrupted step's before/after checkpoint before acting.
        async with self.lock:
            self.require("human")
            if generation != self.generation:
                raise OwnershipError("stale intervention generation")
            self.owner = "automation"
            self.journal.emit(
                "control_transferred",
                owner="automation",
                session_id=self.session_id,
                generation=self.generation,
            )
            self.resumed.set()

    async def abort(self, generation: int | None = None) -> None:
        async with self.lock:
            if self.owner == "finished":
                raise OwnershipError("session already finished")
            if generation is not None and generation != self.generation:
                raise OwnershipError("stale abort generation")
            self.aborted = True
            self.abort_requested.set()
            self.owner = "finished"
            self.journal.emit("operator_aborted", session_id=self.session_id)
            self.resumed.set()

    def status(self) -> dict:
        return dict(
            session_id=self.session_id,
            owner=self.owner,
            generation=self.generation,
            intervention=self.request,
            handoffs=self.handoffs,
        )
