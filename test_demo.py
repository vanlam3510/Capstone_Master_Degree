#!/usr/bin/env python3
"""Regression tests for the corrected, simulation-only index.html.

Install: python -m pip install playwright && python -m playwright install chromium
Serve:   python -m http.server 8004 --bind 127.0.0.1
Run:     python test_demo.py

Optional environment variables:
  CAPSTONE_TEST_URL       Default: http://127.0.0.1:8004/index.html
  CAPSTONE_CHROMIUM_PATH  Explicit browser executable (otherwise prefer the
                         Playwright browser, falling back to system Chromium).
  CAPSTONE_RESULTS_PATH  Default: regression-results.json beside this script.

These are white-box browser tests of local policy and state transitions. They
invoke the same handlers as the UI, with controlled state injection for faults.
They do not test external styling, LLMs, wallets, EVM execution, or hardware.
Every check gets a new browser context and fresh page. No fixed animation sleeps
or presentation-badge assertions are used. Failures are recorded, never relabeled.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

URL = os.environ.get("CAPSTONE_TEST_URL", "http://127.0.0.1:8004/index.html")
OUTPUT = Path(os.environ.get(
    "CAPSTONE_RESULTS_PATH", str(Path(__file__).resolve().with_name("regression-results.json"))
))
TIMEOUT_MS = 15_000
TESTS = []


def test(name):
    def register(function):
        TESTS.append((name, function))
        return function
    return register


def require(condition, message):
    # Do not use Python assert: checks must remain active under python -O.
    if not condition:
        raise AssertionError(message)


class Demo:
    def __init__(self, page):
        self.page = page

    def evaluate(self, expression, arg=None):
        return self.page.evaluate(expression, arg)

    def scenario(self, name):
        self.evaluate("name => loadScenario(name)", name)

    def fill(self, field, value):
        self.page.locator("#" + field).fill(str(value))

    def decision(self):
        raw = self.page.locator("#pdrAttestationDisplay").text_content()
        require(bool(raw and raw.strip()), "No structured decision was produced")
        data = json.loads(raw)
        require(isinstance(data, dict), "Decision must be a JSON object")
        return data

    def expect_status(self, expected):
        actual = self.decision().get("status")
        require(actual == expected, f"Expected {expected}, received {actual}: {self.decision()}")

    def spent(self):
        return self.evaluate("state.epochSpentEth")

    def expect_spent(self, expected):
        require(math.isclose(self.spent(), expected, rel_tol=0, abs_tol=1e-12),
                f"Expected spend {expected}, received {self.spent()}")

    def no_pending(self):
        require(self.evaluate("state.pendingElevatedIntent === null"),
                "A pending authorization unexpectedly remains")

    def run(self):
        # Playwright awaits this handler's returned Promise, including finally.
        self.evaluate("async () => { await runPipelineSimulation(); }")
        require(not self.evaluate("state.isSimulating"), "Pipeline did not finish")
        require(self.page.locator("#runPipelineBtn").is_enabled(), "Run button stayed disabled")

    def elevate(self):
        self.scenario("elevated_rebalance")
        self.run()
        self.expect_status("ELEVATED")
        require(self.evaluate("state.pendingElevatedIntent !== null"),
                "Elevation failed to create a pending request")
        self.expect_spent(0.002)

    def confirm(self):
        self.evaluate("async () => { await confirmLedgerSignature(); }")

    def reject_input(self, field, value):
        before = self.spent()
        self.fill(field, value)
        self.run()
        self.expect_status("BLOCKED")
        self.expect_spent(before)
        self.no_pending()


@test("Routine preset approves and records exactly one spend")
def routine(d):
    d.run()
    d.expect_status("APPROVED")
    d.expect_spent(0.004)
    d.no_pending()


@test("Unauthorized-target preset blocks without spending")
def unauthorized_target(d):
    d.scenario("memory_injection")
    d.run()
    d.expect_status("BLOCKED")
    d.expect_spent(0.002)
    d.no_pending()


@test("Excessive-slippage preset blocks without spending")
def slippage(d):
    d.scenario("mev_slippage")
    d.run()
    d.expect_status("BLOCKED")
    d.expect_spent(0.002)


@test("Larger rebalance requests review without spending")
def elevated(d):
    d.elevate()


@test("Blank gas rejects at dispatch")
def blank_gas(d):
    d.reject_input("gasInput", "")


@test("Negative gas rejects at dispatch")
def negative_gas(d):
    d.reject_input("gasInput", "-1")


@test("Gas above 15 Gwei rejects at dispatch")
def high_gas(d):
    d.reject_input("gasInput", "30")


@test("Zero and negative amounts both reject")
def nonpositive_amount(d):
    for value in ("0", "-1"):
        d.reject_input("amountInput", value)


@test("Amount above 0.10 ETH rejects even with confirmation attempted")
def hard_ceiling(d):
    d.reject_input("amountInput", "0.20")
    d.confirm()
    d.expect_spent(0.002)
    d.no_pending()


@test("Zero estimated output rejects")
def zero_estimate(d):
    d.reject_input("estOutInput", "0")


@test("Zero minimum output rejects")
def zero_minimum(d):
    d.reject_input("minOutInput", "0")


@test("Blank gas rejects at confirmation")
def blank_confirmation(d):
    d.elevate()
    d.fill("gasInput", "")
    d.confirm()
    d.expect_status("BLOCKED")
    d.expect_spent(0.002)
    d.no_pending()


@test("Negative gas rejects at confirmation")
def negative_confirmation(d):
    d.elevate()
    d.fill("gasInput", "-1")
    d.confirm()
    d.expect_status("BLOCKED")
    d.expect_spent(0.002)
    d.no_pending()


@test("A live gas spike rejects at confirmation")
def spike_confirmation(d):
    d.elevate()
    d.fill("gasInput", "30")
    d.confirm()
    d.expect_status("BLOCKED")
    d.expect_spent(0.002)
    d.no_pending()


@test("Zero gas permits a valid simulated confirmation")
def zero_confirmation(d):
    d.elevate()
    d.fill("gasInput", "0")
    d.confirm()
    d.expect_status("SIMULATED_AUTHORIZED")
    d.expect_spent(0.042)
    d.no_pending()


@test("Rejected review cannot subsequently be confirmed")
def rejected_review(d):
    d.elevate()
    d.evaluate("() => { rejectLedgerSignature(); }")
    d.no_pending()
    d.confirm()
    d.expect_spent(0.002)
    require("SIMULATED HUMAN APPROVAL CONFIRMED" not in
            d.page.locator("#outcomeBanner").text_content(), "Rejected review was confirmed")


@test("Emergency halt prevents pending confirmation")
def halted_confirmation(d):
    d.elevate()
    d.evaluate("() => { toggleKillSwitch(); }")
    d.confirm()
    d.expect_status("BLOCKED")
    d.expect_spent(0.002)
    d.no_pending()


@test("Concurrent duplicate confirmations spend only once")
def duplicate_confirmation(d):
    d.elevate()
    nonce = d.evaluate("state.pendingElevatedIntent.intent.nonce")
    d.evaluate("async () => { await Promise.all([confirmLedgerSignature(), confirmLedgerSignature()]); }")
    d.expect_status("SIMULATED_AUTHORIZED")
    d.expect_spent(0.042)
    require(d.evaluate("nonce => state.consumedNonces.has(nonce)", nonce),
            "Successful confirmation did not consume the nonce")
    d.confirm()
    d.expect_spent(0.042)
    d.no_pending()


@test("Changed intent is rejected by digest verification")
def changed_intent(d):
    d.elevate()
    d.evaluate("""() => {
        state.pendingElevatedIntent = {...state.pendingElevatedIntent,
          intent: {...state.pendingElevatedIntent.intent, minReturn: 121.9}};
    }""")
    d.confirm()
    d.expect_status("BLOCKED")
    require("digest mismatch" in d.decision().get("reason", "").lower(),
            "Alteration did not reach the digest-mismatch guard")
    d.expect_spent(0.002)
    d.no_pending()


@test("Expired pending intent rejects")
def expired(d):
    d.elevate()
    d.evaluate("""() => {
        state.pendingElevatedIntent = {...state.pendingElevatedIntent,
          intent: {...state.pendingElevatedIntent.intent, deadline: 0}};
    }""")
    d.confirm()
    d.expect_status("BLOCKED")
    require("expired" in d.decision().get("reason", "").lower(), "Expiry rejection missing")
    d.expect_spent(0.002)
    d.no_pending()


@test("Hashing failure rejects and restores runnable UI")
def crypto_failure(d):
    d.evaluate("""() => {
        computeCompleteCanonicalDigest = async () => { throw new Error('test: crypto unavailable'); };
    }""")
    d.run()
    d.expect_status("BLOCKED")
    require("crypto unavailable" in d.decision().get("reason", ""), "Injected error not reported")
    d.expect_spent(0.002)
    d.no_pending()


@test("Rolling budget counts recent events and expires old events")
def rolling_budget(d):
    d.evaluate("""() => {
        state.spendEvents = [{time:Date.now()-3600001, amount:0.5},
                             {time:Date.now(), amount:0.019}];
        refreshBudget();
    }""")
    d.expect_spent(0.019)
    d.fill("amountInput", "0.003")
    d.run()
    d.expect_status("ELEVATED")
    d.expect_spent(0.019)
    d.evaluate("() => { state.spendEvents.forEach(e => e.time = Date.now()-3600001); refreshBudget(); }")
    d.expect_spent(0)


@test("HTML injected into the target is rejected without execution")
def xss(d):
    d.reject_input("targetInput", "<img src=x onerror=window.__test_xss=true>")
    require(not d.evaluate("window.__test_xss === true"), "HTML event handler executed")


@test("Displayed intent digest matches independent sorted-key JSON SHA-256")
def digest(d):
    d.run()
    d.expect_status("APPROVED")
    intent = json.loads(d.page.locator("#stage1Json").text_content())
    # This known fixture has ASCII strings and simple numbers whose JSON
    # encodings match JS JSON.stringify. This is not a general JCS implementation.
    serialized = json.dumps(intent, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    expected = "0x" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    require(d.decision().get("calldataHash") == expected,
            "The displayed decision digest differs from independently computed SHA-256")


@test("Halt after dispatch begins prevents execution")
def mid_pipeline_halt(d):
    d.evaluate("() => { window.__test_pipeline = runPipelineSimulation(); }")
    # Wait for observable execution state, not an arbitrary number of milliseconds.
    d.page.wait_for_function("state.isSimulating === true")
    d.evaluate("() => { toggleKillSwitch(); }")
    d.evaluate("async () => { await window.__test_pipeline; }")
    d.expect_spent(0.002)
    require(d.evaluate("state.masterKillSwitch && !state.isSimulating"), "Halt/lifecycle state is wrong")
    banner = d.page.locator("#outcomeBanner").text_content()
    require("BLOCKED" in banner or "ABORTED" in banner, "No blocked/aborted outcome was rendered")
    require(d.page.locator("#runPipelineBtn").is_enabled(), "Halt left Run button disabled")
    d.no_pending()


@test("Loading a new scenario invalidates a previous pending review")
def stale_review(d):
    d.elevate()
    d.scenario("memory_injection")
    d.no_pending()
    d.run()
    d.expect_status("BLOCKED")
    d.confirm()
    d.expect_spent(0.002)
    d.no_pending()


def main():
    started = datetime.now(timezone.utc).isoformat()
    results = []
    suite_error = None
    browser_info = {}
    source_hashes = set()
    target_origin = urlsplit(URL)[:2]

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            requested = os.environ.get("CAPSTONE_CHROMIUM_PATH")
            executable = requested
            if not executable and not Path(p.chromium.executable_path).exists():
                executable = shutil.which("chromium") or shutil.which("chromium-browser")
            options = {"headless": True}
            if executable:
                options["executable_path"] = executable
            browser = p.chromium.launch(**options)
            browser_info = {"version": browser.version,
                            "executable": executable or p.chromium.executable_path,
                            "playwrightVersion": importlib.metadata.version("playwright")}
            try:
                for number, (name, function) in enumerate(TESTS, 1):
                    begin = time.monotonic()
                    context = browser.new_context()
                    detail = ""
                    outcome = "PASS"
                    try:
                        # Keep only same-origin HTTP requests; no external CDNs.
                        def route_request(route):
                            if urlsplit(route.request.url)[:2] == target_origin:
                                route.continue_()
                            else:
                                route.abort()
                        context.route("**/*", route_request)
                        page = context.new_page()
                        page.set_default_timeout(TIMEOUT_MS)
                        response = page.goto(URL, wait_until="domcontentloaded")
                        require(response is not None and response.status == 200,
                                "Target page did not return HTTP 200")
                        source_hashes.add(hashlib.sha256(response.body()).hexdigest())
                        page.wait_for_function("typeof evaluateIntent === 'function' && typeof state === 'object'")
                        demo = Demo(page)
                        demo.scenario("routine")
                        demo.expect_spent(0.002)
                        demo.no_pending()
                        function(demo)
                    except Exception as error:
                        outcome = "FAIL"
                        detail = f"{type(error).__name__}: {error}"
                    finally:
                        context.close()
                    results.append({"id": number, "name": name, "status": outcome,
                                    "detail": detail,
                                    "durationSeconds": round(time.monotonic() - begin, 3)})
                    print(f"[{outcome}] {number:02d}. {name}" + (f"\n  {detail}" if detail else ""), flush=True)
            finally:
                browser.close()
        if len(source_hashes) != 1:
            suite_error = "Target HTML changed during the run or no source was verified."
    except Exception as error:
        suite_error = f"{type(error).__name__}: {error}"

    passed = sum(r["status"] == "PASS" for r in results)
    failed = sum(r["status"] == "FAIL" for r in results)
    report = {
        "schemaVersion": 1, "startedAt": started,
        "finishedAt": datetime.now(timezone.utc).isoformat(),
        "scope": "Local policy/UI simulation only; no external styling, chain, LLM, or hardware validation",
        "targetUrl": URL, "htmlSha256": sorted(source_hashes),
        "testScriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "browser": browser_info, "totalChecks": len(TESTS), "executed": len(results),
        "passed": passed, "failed": failed, "unrun": len(TESTS) - len(results),
        "suiteError": suite_error, "checks": results,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\n{passed}/{len(TESTS)} passed; {failed} failed; {report['unrun']} unrun.")
    print(f"Results: {OUTPUT}")
    if suite_error:
        print(f"Suite error: {suite_error}", file=sys.stderr)
        return 2
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
