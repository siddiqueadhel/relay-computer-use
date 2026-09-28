"""Trusted app policy; capability and model-provided risk labels have no authority."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

from pydantic import Field

from relay.schema import StrictModel


class PolicyViolation(Exception):
    def __init__(self, code: str = "policy_denied"):
        self.code = code
        super().__init__(code)


class Policy(StrictModel):
    paths: set[str] = Field(
        default_factory=lambda: {
            "/",
            "/workspace",
            "/search",
            "/member",
            "/subaccount",
            "/review",
            "/restore",
            "/bank.css",
            "/favicon.ico",
        }
    )
    actions: set[str] = Field(default_factory=lambda: {"navigate", "click", "fill", "select"})
    clicks: set[str] = Field(
        default_factory=lambda: {
            "Search",
            "Open member",
            "Add sub-account",
            "Review request",
            "Back to member",
            "Edit request",
            "Return to search",
            "Acknowledge message",
        }
    )
    human_clicks: set[str] = Field(
        default_factory=lambda: {
            "Resume staff session",
            "Dismiss supervisor notice",
        }
    )
    fields: set[str] = Field(
        default_factory=lambda: {"Member number", "Account type", "Account name"}
    )
    private_selectors: list[str] = Field(
        default_factory=lambda: [
            "[data-private]",
            "[data-sensitive]",
            "input",
            "textarea",
            "[contenteditable=true]",
        ]
    )

    def check_url(self, url: str, origin: str) -> None:
        parsed, base = urlsplit(url), urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise PolicyViolation("invalid_destination")
        if (parsed.scheme, parsed.hostname, parsed.port) != (base.scheme, base.hostname, base.port):
            raise PolicyViolation("origin_denied")
        path = parsed.path or "/"
        for _ in range(3):
            decoded = unquote(path)
            if decoded == path:
                break
            path = decoded
        if "\\" in path or any(p in {".", ".."} for p in path.split("/")) or "%" in path:
            raise PolicyViolation("ambiguous_destination")
        if path not in self.paths:
            raise PolicyViolation("route_denied")

    def check_control(self, action: str, info: dict, *, human: bool = False) -> None:
        if action not in self.actions:
            raise PolicyViolation("action_denied")
        if info.get("type") in {"password", "file", "hidden"}:
            raise PolicyViolation("sensitive_control_denied")
        name = info.get("name", "")
        if action == "click":
            allowed = self.clicks | (self.human_clicks if human else set())
            if name not in allowed:
                raise PolicyViolation("control_denied")
            if info.get("tag") not in {"a", "button", "input"}:
                raise PolicyViolation("noninteractive_control_denied")
        elif action in {"fill", "select"} and name not in self.fields:
            raise PolicyViolation("field_denied")
