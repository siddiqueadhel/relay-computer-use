"""Portable data contracts. No browser or model dependencies belong here."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class FieldSpec(StrictModel):
    type: Literal["string", "integer", "number", "boolean"] = "string"
    description: str
    sensitive: bool = False
    enum: list[str] = Field(default_factory=list)
    pattern: str | None = None
    max_length: int = Field(default=200, ge=1, le=2000)

    def accepts(self, value: Any) -> bool:
        if self.type == "string":
            return (
                isinstance(value, str)
                and 0 < len(value) <= self.max_length
                and (not self.enum or value in self.enum)
                and (not self.pattern or re.fullmatch(self.pattern, value) is not None)
            )
        if self.type == "integer":
            return type(value) is int
        if self.type == "number":
            return type(value) in (int, float) and math.isfinite(value)
        return type(value) is bool


class Value(StrictModel):
    source: Literal["input", "literal"]
    value: str

    def resolve(self, inputs: dict[str, Any]) -> str:
        return str(inputs[self.value]) if self.source == "input" else self.value


class Locator(StrictModel):
    by: Literal["role", "label", "text", "row"]
    name: str = Field(min_length=1, max_length=150)
    role: str | None = None
    control: Literal["input", "select", "button", "value"] | None = None

    @model_validator(mode="after")
    def well_formed(self) -> Self:
        if self.by == "role" and not self.role:
            raise ValueError("role locators require a role")
        if self.by == "row" and not self.control:
            raise ValueError("row locators require a control kind")
        return self


class Target(StrictModel):
    frame_path: list[str] = Field(default_factory=list, max_length=4)
    candidates: list[Locator] = Field(min_length=1, max_length=3)


class Condition(StrictModel):
    kind: Literal["visible", "absent", "text_equals", "value_equals"]
    target: Target
    expected: Value | None = None

    @model_validator(mode="after")
    def comparison_has_value(self) -> Self:
        if self.kind not in {"visible", "absent"} and self.expected is None:
            raise ValueError("comparison requires expected value")
        return self


class Action(StrictModel):
    kind: Literal["navigate", "click", "fill", "select", "human"]
    target: Target | None = None
    value: Value | None = None
    path: str | None = None

    @model_validator(mode="after")
    def valid_shape(self) -> Self:
        if self.kind == "human":
            if self.target or self.value or self.path:
                raise ValueError("human gates cannot contain UI actions")
            return self
        if self.kind == "navigate":
            if not self.path or not self.path.startswith("/") or self.path.startswith("//"):
                raise ValueError("navigation must use an app-relative path")
            if self.target or self.value:
                raise ValueError("navigation cannot contain a target or value")
        elif not self.target or self.path:
            raise ValueError("UI actions require a target and no path")
        if self.kind in ("fill", "select") and self.value is None:
            raise ValueError("fill/select requires a value")
        if self.kind == "click" and self.value:
            raise ValueError("click cannot contain a value")
        return self


class Step(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9_-]+$")
    action: Action
    before: list[Condition] = Field(default_factory=list)
    after: list[Condition] = Field(min_length=1)
    rationale: str = Field(max_length=400)
    timeout_ms: int = Field(default=5000, ge=100, le=30000)


class Output(StrictModel):
    spec: FieldSpec
    target: Target
    equals_input: str | None = None


class OutcomeRule(StrictModel):
    code: str = Field(pattern=r"^[a-z_]+$")
    when: Condition
    disposition: Literal["business", "recover", "intervene", "fail"]
    recovery: Action | None = None
    max_attempts: int = Field(default=1, ge=0, le=3)

    @model_validator(mode="after")
    def recovery_is_bounded(self) -> Self:
        if self.disposition == "recover" and (not self.recovery or not self.max_attempts):
            raise ValueError("recovery requires an action and a positive attempt limit")
        if self.disposition != "recover" and self.recovery:
            raise ValueError("only recovery rules can include an action")
        return self


class Contract(StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    description: str
    inputs: dict[str, FieldSpec]
    outputs: dict[str, Output]
    success: list[Condition] = Field(min_length=1)

    def validate_inputs(self, values: dict[str, Any]) -> None:
        if set(values) != set(self.inputs):
            raise ValueError("input keys must exactly match the capability contract")
        bad = [name for name, spec in self.inputs.items() if not spec.accepts(values[name])]
        if bad:
            raise ValueError("invalid input fields: " + ", ".join(bad))


class Provenance(StrictModel):
    kind: Literal["llm_discovery", "authored_example", "test_fixture"]
    provider: str
    model: str | None = None
    run_id: str | None = None
    model_calls: int = Field(default=0, ge=0)
    evidence_sha256: str | None = Field(
        default=None,
        description="SHA-256 of the first evidence_event_count newline-terminated JSONL events.",
    )
    evidence_event_count: int = Field(default=0, ge=0)


class Capability(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    vendor: str
    app_version: str
    contract: Contract
    steps: list[Step] = Field(min_length=1, max_length=60)
    outcomes: list[OutcomeRule] = Field(default_factory=list)
    provenance: Provenance

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique")
        codes = [r.code for r in self.outcomes]
        if len(codes) != len(set(codes)):
            raise ValueError("outcome codes must be unique")

        def visit(obj: Any) -> None:
            if isinstance(obj, dict):
                if obj.get("source") == "input" and obj.get("value") not in self.contract.inputs:
                    raise ValueError("unknown input reference")
                for child in obj.values():
                    visit(child)
            elif isinstance(obj, list):
                for child in obj:
                    visit(child)

        visit(self.model_dump())
        for output in self.contract.outputs.values():
            if output.equals_input and output.equals_input not in self.contract.inputs:
                raise ValueError("output references an unknown input")
        return self

    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class RunResult(StrictModel):
    run_id: str
    status: Literal["success", "business_outcome", "failure", "aborted"]
    code: str
    outputs: dict[str, Any] = Field(default_factory=dict)
    step_id: str | None = None
    expected: str | None = None
    observed: str | None = None
    evidence: str | None = None
    model_calls: int = 0
    recoveries: int = 0
    handoffs: int = 0
    elapsed_ms: int = 0


def target(name: str, role: str = "heading", frame: str = "workspace") -> Target:
    return Target(
        frame_path=[frame] if frame else [], candidates=[Locator(by="role", role=role, name=name)]
    )


def visible(name: str, role: str = "heading") -> Condition:
    return Condition(kind="visible", target=target(name, role))
