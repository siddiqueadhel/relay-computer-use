"""Browser implementation of the portable observe/act/check/read surface boundary."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

from playwright.async_api import Error as BrowserError
from playwright.async_api import Frame, async_playwright
from playwright.async_api import Locator as PWLocator
from playwright.async_api import TimeoutError as BrowserTimeout

from relay.control import OwnershipError, SessionControl
from relay.evidence import Journal
from relay.policy import Policy, PolicyViolation
from relay.schema import Action, Condition, Target


class SurfaceError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def navigation_interrupted(exc: BrowserError) -> bool:
    return any(
        text in str(exc).lower()
        for text in (
            "execution context was destroyed",
            "cannot find context",
            "frame was detached",
        )
    )


class Surface(Protocol):
    journal: Journal
    default_timeout_ms: int
    blocked: str | None

    async def observe(self) -> dict: ...
    async def act(
        self,
        action: Action,
        inputs: dict[str, Any],
        *,
        actor: str = "automation",
        expected_generation: int | None = None,
    ) -> None: ...
    async def check(self, conditions: list[Condition], inputs: dict[str, Any]) -> bool: ...
    async def read(self, target: Target) -> str: ...

    async def wait(
        self, conditions: list[Condition], inputs: dict[str, Any], timeout_ms: int
    ) -> bool: ...

    async def evidence(self, name: str) -> str: ...


# Inspect visible browser state only. No source files, app stores, or network response bodies.
CONTROL_INFO = r"""el => {
  const tag = el.tagName.toLowerCase();
  const label = el.labels && el.labels.length ? el.labels[0].innerText.trim() : '';
  const row = el.closest('tr');
  const rowLabel = row?.querySelector('th')?.innerText.trim() || '';
  const named = el.getAttribute('aria-label');
  const text = (el.innerText || '').trim().replace(/\s+/g, ' ');
  const name = named || label || (['button','a'].includes(tag) ? text : rowLabel || el.getAttribute('placeholder') || '');
  return {tag, name, label, rowLabel, type: el.getAttribute('type') || '',
    href: tag === 'a' ? el.href : '',
    form_action: el.form && (tag === 'button' || tag === 'input') && el.type === 'submit' ? (el.hasAttribute('formaction') ? el.formAction : el.form.action) : ''};
}"""

OBSERVE_JS = r"""privateSelectors => {
  if (!document.body || document.readyState === 'loading') return null;
  const info = CONTROL_INFO;
  const isVisible = e => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
  const isPrivate = e => privateSelectors.some(s => e.closest(s));
  const headings = [...document.querySelectorAll('h1,h2')].filter(isVisible).filter(e=>!isPrivate(e)).map(e=>({level:Number(e.tagName[1]),text:e.innerText.trim()}));
  const controls = [...document.querySelectorAll('button,a,input:not([type=hidden]),select,textarea')].filter(isVisible).map(el => {
    const x = info(el); const role = {a:'link',button:'button',select:'combobox',input:'textbox',textarea:'textbox'}[x.tag];
    let candidate;
    if (x.label) candidate={by:'label',name:x.label};
    else if (x.rowLabel && ['input','select','textarea'].includes(x.tag)) candidate={by:'row',name:x.rowLabel,control:x.tag==='textarea'?'input':x.tag};
    else candidate={by:'role',role,name:x.name};
    return {name:x.name, role, candidate, options:x.tag==='select'?[...el.options].map(o=>({label:o.label,value:o.value})):undefined};
  }).filter(c=>c.name);
  const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  let text=[],n; while(n=walker.nextNode()) {
    const p=n.parentElement;
    if(!p || ['SCRIPT','STYLE','NOSCRIPT'].includes(p.tagName) || isPrivate(p) || !isVisible(p)) continue;
    const s=n.textContent.trim(); if(s) text.push(s);
  }
  return {headings,controls,text:text.join('\n').slice(0,12000)};
}""".replace("CONTROL_INFO", CONTROL_INFO)

HUMAN_EVENTS_JS = r"""(() => {
  const info = CONTROL_INFO;
  for (const kind of ['click','change']) document.addEventListener(kind, event => {
    if (!event.isTrusted) return;
    const el=event.target.closest('button,a,input,select,textarea');
    if(!el) return;
    const x=info(el);
    window.__relayAudit({kind,tag:x.tag,name:x.type==='password'?'[SECRET FIELD]':x.name}).catch(()=>{});
  }, true);
})()""".replace("CONTROL_INFO", CONTROL_INFO)


class BrowserSurface:
    def __init__(
        self,
        entry: str,
        policy: Policy,
        control: SessionControl,
        journal: Journal,
        *,
        headless: bool = True,
    ):
        parsed = urlsplit(entry)
        self.origin = f"{parsed.scheme}://{parsed.netloc}"
        self.entry = entry
        self.policy = policy
        self.control = control
        self.journal = journal
        self.headless = headless
        self.page = None
        self.blocked: str | None = None
        self.default_timeout_ms = 5000

    async def __aenter__(self):
        self.policy.check_url(self.entry, self.origin)
        self.playwright = await async_playwright().start()
        self.remote = bool(os.getenv("RELAY_CDP_ENDPOINT"))
        try:
            if self.remote:
                endpoint = os.environ["RELAY_CDP_ENDPOINT"]
                if urlsplit(endpoint).hostname not in {"127.0.0.1", "localhost"}:
                    raise ValueError("the development browser host must be loopback-only")
                self.browser = await self.playwright.chromium.connect_over_cdp(endpoint)
            else:
                self.browser = await self.playwright.chromium.launch(
                    headless=self.headless,
                    executable_path=os.getenv("RELAY_BROWSER_PATH"),
                )
            self.context = await self.browser.new_context(
                viewport={"width": 1360, "height": 960},
                service_workers="block",
                accept_downloads=False,
            )
            self.context.set_default_timeout(self.default_timeout_ms)
            await self.context.route("**/*", self._route)
            await self.context.route_web_socket("**/*", lambda ws: ws.close())
            await self.context.expose_binding("__relayAudit", self._human_event)
            await self.context.add_init_script(HUMAN_EVENTS_JS)
            self.page = await self.context.new_page()
            self.context.on("page", lambda p: asyncio.create_task(self._unexpected_page(p)))
            self.page.on("dialog", lambda d: asyncio.create_task(self._native_dialog(d)))
            self.page.on("download", lambda d: asyncio.create_task(d.cancel()))
            self.journal.emit(
                "session_started",
                session_id=self.control.session_id,
                surface="playwright_chromium",
                viewport="1360x960",
            )
            return self
        except BaseException:
            await self.playwright.stop()
            raise

    async def __aexit__(self, *_):
        await self.context.close()
        if not self.remote:
            await self.browser.close()
        await self.playwright.stop()

    async def _route(self, route) -> None:
        try:
            self.policy.check_url(route.request.url, self.origin)
            if route.request.method not in {"GET", "POST"}:
                raise PolicyViolation("request_method_denied")
        except PolicyViolation as exc:
            self.blocked = exc.code
            self.journal.emit("network_blocked", code=exc.code)
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    async def _unexpected_page(self, page) -> None:
        self.blocked = "popup_denied"
        self.journal.emit("popup_blocked")
        await page.close()

    async def _native_dialog(self, dialog) -> None:
        # Unexpected native dialogs are never accepted automatically.
        self.blocked = "unexpected_native_dialog"
        self.journal.emit("native_dialog_dismissed", type=dialog.type)
        await dialog.dismiss()

    async def _human_event(self, source, event) -> None:
        if self.control.owner != "human" or source["page"] != self.page:
            return
        if not isinstance(event, dict) or event.get("kind") not in {"click", "change"}:
            return
        self.journal.emit(
            "human_action",
            session_id=self.control.session_id,
            generation=self.control.generation,
            kind=event.get("kind"),
            origin="browser_event",
            control=str(event.get("name", ""))[:150],
            values="not recorded",
        )

    def _check_destinations(self) -> None:
        if self.blocked:
            raise PolicyViolation(self.blocked)
        for frame in self.page.frames:
            # Newly attached frames have no committed URL yet. Network routing
            # still checks their destination before any request is allowed.
            if frame.url not in {"", "about:blank"}:
                self.policy.check_url(frame.url, self.origin)

    def _frame(self, path: list[str]) -> Frame:
        current = self.page.main_frame
        for name in path:
            matches = [f for f in current.child_frames if f.name == name]
            if len(matches) != 1:
                raise SurfaceError("frame_missing" if not matches else "ambiguous_frame")
            current = matches[0]
        return current

    async def resolve(self, target: Target) -> PWLocator:
        self._check_destinations()
        frame = self._frame(target.frame_path)
        for candidate in target.candidates:
            if candidate.by == "role":
                locator = frame.get_by_role(candidate.role, name=candidate.name, exact=True)
            elif candidate.by == "label":
                locator = frame.get_by_label(candidate.name, exact=True)
            elif candidate.by == "text":
                locator = frame.get_by_text(candidate.name, exact=True)
            else:
                rows = frame.locator("tr").filter(has=frame.get_by_text(candidate.name, exact=True))
                locator = rows.locator("td" if candidate.control == "value" else candidate.control)
            try:
                count = await locator.count()
                if count > 20:
                    raise SurfaceError("ambiguous_target")
                matches = [
                    locator.nth(i) for i in range(count) if await locator.nth(i).is_visible()
                ]
            except BrowserError as exc:
                # Navigation can detach a frame between resolving its name and
                # querying a locator. Its checkpoint is missing, not satisfied.
                if frame.is_detached():
                    raise SurfaceError("frame_missing") from None
                if navigation_interrupted(exc):
                    raise SurfaceError("frame_not_ready") from None
                raise
            if len(matches) > 1:
                raise SurfaceError("ambiguous_target")
            if matches:
                return matches[0]
        raise SurfaceError("target_missing")

    async def observe(self) -> dict:
        deadline = time.monotonic() + self.default_timeout_ms / 1000
        retries = 0
        while True:
            try:
                result = await self._observe_once()
                if retries:
                    self.journal.emit(
                        "observation_retried", reason="navigation_transition", retries=retries
                    )
                return result
            except BrowserError as exc:
                # Read-only observation may race a frame navigation. Never retry an action here.
                if not navigation_interrupted(exc):
                    raise SurfaceError("observation_failed") from None
            except SurfaceError as exc:
                if exc.code != "observation_not_ready":
                    raise
            if time.monotonic() >= deadline:
                raise SurfaceError("observation_timeout")
            retries += 1
            await asyncio.sleep(0.05)

    async def _observe_once(self) -> dict:
        self._check_destinations()
        frames = []
        initial_frames = [(frame, frame.url) for frame in self.page.frames]
        for frame, url in initial_frames:
            if frame.url in {"", "about:blank"}:
                continue
            path, ancestor = [], frame
            while ancestor.parent_frame:
                path.insert(0, ancestor.name)
                ancestor = ancestor.parent_frame
            state = await frame.evaluate(OBSERVE_JS, self.policy.private_selectors)
            if state is None or frame.url != url:
                raise SurfaceError("observation_not_ready")
            state["frame_path"] = path
            state["path"] = urlsplit(frame.url).path
            for control in state["controls"]:
                control["target"] = {"frame_path": path, "candidates": [control.pop("candidate")]}
            frames.append(state)
        self._check_destinations()
        if [(frame, frame.url) for frame in self.page.frames] != initial_frames:
            raise SurfaceError("observation_not_ready")
        return self.journal.redactor.clean({"frames": frames})

    async def act(
        self,
        action: Action,
        inputs: dict[str, Any],
        *,
        actor: str = "automation",
        expected_generation: int | None = None,
    ) -> None:
        async with self.control.lock:
            self.control.require(actor)
            if expected_generation is not None and expected_generation != self.control.generation:
                raise OwnershipError("stale action generation")
            self._check_destinations()
            if action.kind not in self.policy.actions:
                raise PolicyViolation("action_denied")
            if action.kind == "navigate":
                destination = (
                    self.entry if action.path == "/" else urljoin(self.origin, action.path)
                )
                self.policy.check_url(destination, self.origin)
                await self.page.goto(destination, wait_until="domcontentloaded")
            else:
                locator = await self.resolve(action.target)
                info = await locator.evaluate(CONTROL_INFO)
                self.policy.check_control(action.kind, info, human=actor == "human")
                for destination in (info["href"], info["form_action"]):
                    if destination:
                        self.policy.check_url(destination, self.origin)
                if action.kind == "click":
                    if info["href"] or info["form_action"]:
                        await self._click_navigation(locator, self._frame(action.target.frame_path))
                    else:
                        await locator.click(timeout=self.default_timeout_ms)
                elif action.kind == "fill":
                    await locator.fill(
                        action.value.resolve(inputs), timeout=self.default_timeout_ms
                    )
                else:
                    await locator.select_option(
                        value=action.value.resolve(inputs), timeout=self.default_timeout_ms
                    )
            self._check_destinations()

            if actor == "human":
                self.journal.emit(
                    "human_action",
                    session_id=self.control.session_id,
                    generation=self.control.generation,
                    kind=action.kind,
                    control="navigation" if action.kind == "navigate" else info["name"],
                    origin="operator_command",
                    values="not recorded",
                )

    async def _click_navigation(self, locator: PWLocator, frame: Frame) -> None:
        # Register before clicking: a URL check alone misses same-URL POST/redirect
        # navigations. This profile's links and submit controls navigate their own frame.
        committed = asyncio.Event()

        def navigated(changed):
            if changed == frame:
                committed.set()

        self.page.on("framenavigated", navigated)
        try:
            async with asyncio.timeout(self.default_timeout_ms / 1000):
                await locator.click(timeout=self.default_timeout_ms)
                await committed.wait()
                self._check_destinations()
                await frame.wait_for_load_state("domcontentloaded", timeout=self.default_timeout_ms)
        except TimeoutError:
            self._check_destinations()
            # Let replay inspect the postcondition, never automatically repeat the click.
            raise BrowserTimeout("Navigation did not settle within the action budget") from None
        finally:
            self.page.remove_listener("framenavigated", navigated)

    async def check(self, conditions: list[Condition], inputs: dict[str, Any]) -> bool:
        for condition in conditions:
            try:
                locator = await self.resolve(condition.target)
            except SurfaceError as exc:
                if condition.kind == "absent" and exc.code == "target_missing":
                    continue
                if exc.code in {"target_missing", "frame_missing", "frame_not_ready"}:
                    return False
                raise
            if condition.kind == "visible":
                continue
            if condition.kind == "absent":
                return False
            expected = condition.expected.resolve(inputs)
            actual = (
                await locator.input_value()
                if condition.kind == "value_equals"
                else (await locator.inner_text()).strip()
            )
            if actual != expected:
                return False
        return True

    async def wait(
        self, conditions: list[Condition], inputs: dict[str, Any], timeout_ms: int
    ) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            if await self.check(conditions, inputs):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(0.05)

    async def read(self, target: Target) -> str:
        locator = await self.resolve(target)
        value = (await locator.inner_text()).strip()
        private = await locator.evaluate(
            "(e, selectors) => selectors.some(s => e.closest(s) || e.querySelector(s))",
            self.policy.private_selectors,
        )
        if private:
            self.journal.redactor.add_private(value)
        return value

    async def evidence(self, name: str) -> str:
        """Persist only redacted observations and masked screenshots; fail closed on masking errors."""
        try:
            snapshot = await self.observe()
            self.journal.save_json(f"{name}.json", snapshot)
            masks = []
            for frame in self.page.frames:
                for selector in self.policy.private_selectors:
                    masks.append(frame.locator(selector))
                for value in self.journal.redactor.private_values:
                    masks.append(frame.get_by_text(value, exact=False))
            await self.page.screenshot(
                path=str(self.journal.directory / f"{name}.png"),
                mask=masks,
                mask_color="#16362e",
                animations="disabled",
            )
            self.journal.emit("evidence_saved", snapshot=f"{name}.json", screenshot=f"{name}.png")
            return f"{name}.png"
        except Exception as exc:
            self.journal.emit("evidence_restricted", reason=type(exc).__name__)
            self.journal.save_json(
                f"{name}.json", {"observation": "unavailable under evidence policy"}
            )
            return f"{name}.json"
