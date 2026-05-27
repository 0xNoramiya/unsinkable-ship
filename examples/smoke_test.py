"""Verifies the TrueFoundry gateway is wired correctly.
Exits 0 on full success, 1 if any check fails."""

from __future__ import annotations

import sys
import time

import httpx

from unsinkable import OpenAI
from unsinkable.chaos import ChaosState, activate
from unsinkable.config import get_settings


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def ok(msg: str) -> None:
    print(f"  \033[32mOK\033[0m  {msg}")


def fail(msg: str, hint: str = "") -> None:
    print(f"  \033[31mFAIL\033[0m  {msg}")
    if hint:
        print(f"        \033[33mhint:\033[0m {hint}")


def call(client: OpenAI, model: str, prompt: str = "ping") -> tuple[bool, str, str | None]:
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=10,
        )
        return True, resp.model or "?", resp.choices[0].message.content
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}", None


def main() -> int:
    s = get_settings()
    failures = 0

    section("1. Gateway reachable")
    r = httpx.get(
        f"{s.openai_base_url}/models",
        headers={"Authorization": f"Bearer {s.tfy_api_key}"},
        timeout=10,
    )
    if r.status_code != 200:
        fail(f"GET /models returned {r.status_code}", "check TFY_HOST and TFY_API_KEY in .env")
        return 1
    models = [m["id"] for m in r.json().get("data", [])]
    ok(f"gateway returned {len(models)} model(s)")
    if not models:
        fail("no models", "TF console → AI Gateway → Model Integrations → add OpenAI/Anthropic")
        return 1

    client = OpenAI()

    section("2. Direct provider call")
    direct_candidates = [m for m in models if "/" in m and not m.startswith("unsinkable/")]
    if not direct_candidates:
        fail("no direct provider models found", "expected names like openai-main/gpt-4o-mini")
        failures += 1
    else:
        target = direct_candidates[0]
        ok_call, resolved, body = call(client, target)
        if ok_call:
            ok(f"called {target}, gateway resolved to {resolved}, got: {body!r}")
        else:
            fail(f"{target} call failed: {resolved}",
                 "the provider integration may be missing a valid API key")
            failures += 1

    section("3. Virtual Model (resilient-chat/resilient-chat)")
    vm = "resilient-chat/resilient-chat"
    if vm not in models:
        fail(f"{vm} not configured",
             "Run: tfy apply -f gateway-config/resilient_chat.yaml")
        failures += 1
    else:
        ok_call, resolved, body = call(client, vm)
        if ok_call:
            ok(f"happy path → resolved to {resolved}, got: {body!r}")
        else:
            fail(f"virtual model call failed: {resolved}")
            failures += 1

    section("4. Chaos: break openai → real fallback")
    chaos_vm = "chaos-openai-down/chaos-openai-down"
    if chaos_vm not in models:
        fail(f"{chaos_vm} not configured",
             "Run: tfy apply -f gateway-config/chaos_openai_down.yaml")
        failures += 1
    elif vm in models:
        activate("openai")
        time.sleep(0.2)
        ok_call, resolved, body = call(client, vm)
        ChaosState.clear()
        if ok_call:
            if "openai" in (resolved or "").lower() and "broken" not in (resolved or "").lower():
                fail(f"chaos didn't bite — got {resolved}; expected a non-openai fallback target")
                failures += 1
            else:
                ok(f"chaos rewrote to {chaos_vm}, gateway fell back to {resolved}, got: {body!r}")
        else:
            fail(f"chaos call failed: {resolved}",
                 "expected fallback to succeed — check anthropic/google integrations are live")
            failures += 1

    print()
    if failures:
        print(f"\033[31m{failures} check(s) failed\033[0m")
        return 1
    print("\033[32mall checks passed — you're ready to demo\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
