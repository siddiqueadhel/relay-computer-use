"""Optional local development host when a shell sandbox cannot launch Chromium.

Run this in an ordinary terminal. Only a fresh, synthetic-test browser is exposed;
it never attaches to a personal browser profile. Stop with Ctrl-C after testing.
"""

import asyncio
import json
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from playwright.async_api import async_playwright


def endpoint_ready() -> bool:
    """Check the actual local CDP listener, without using proxy settings."""
    try:
        with build_opener(ProxyHandler({})).open(
            "http://127.0.0.1:9223/json/version", timeout=1
        ) as response:
            return bool(json.load(response).get("webSocketDebuggerUrl"))
    except (OSError, URLError, ValueError):
        return False


async def main():
    async with async_playwright() as playwright:
        print("Starting an isolated test browser; no personal profile is used...", flush=True)
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--remote-debugging-address=127.0.0.1", "--remote-debugging-port=9223"],
        )
        try:
            for _ in range(10):
                if await asyncio.to_thread(endpoint_ready):
                    break
                await asyncio.sleep(0.2)
            else:
                raise RuntimeError(
                    "The browser launched but its test connection on port 9223 is unavailable. "
                    "Share this error, not any credentials."
                )
            print("Dedicated Relay test browser ready on http://127.0.0.1:9223", flush=True)
            print(
                "Port 9223 is for automation, not the app; a blank page there is normal.",
                flush=True,
            )
            print(
                "Keep this terminal open while testing. Ctrl-C closes the isolated browser.",
                flush=True,
            )
            await asyncio.Event().wait()
        finally:
            await browser.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
