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
Every check gets a new browser context and fresh page, and fails on any uncaught
page error. No fixed sleeps are used. A few click-through checks assert on button
labels, pill colour classes and badge text; because external styling is blocked,
visibility is asserted through the 'hidden' class rather than rendered layout.
Failures are recorded, never relabeled.
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


FIELD_IDS = {"amount": "amountInput", "gas": "gasInput", "est": "estOutInput",
             "min": "minOutInput", "target": "targetInput", "recipient": "recipientInput"}
ROUTER = "0x94cC0AaC535CCDB3C01d6787d6413C739ae12bc4"
DEAD = "0x000000000000000000000000000000000000dEaD"


class Demo:
    def __init__(self, page, page_errors=None):
        self.page = page
        self.errors = page_errors if page_errors is not None else []

    def select_action(self, action):
        self.page.locator("#actionTypeSelect").select_option(action)

    def case(self, events=None, action=None, **fields):
        """Load the routine preset, override fields, run, and return the decision."""
        self.scenario("routine")
        if events is None:
            events = [{"amount": 0.002, "ageMs": 0}]
        self.evaluate("""events => {
            state.spendEvents = events.map(e => ({time: Date.now() - e.ageMs, amount: e.amount}));
            refreshBudget();
        }""", events)
        for key, value in fields.items():
            self.fill(FIELD_IDS[key], value)
        if action:
            self.select_action(action)
        self.run()
        return self.decision()

    def expect_case(self, expected, **kwargs):
        decision = self.case(**kwargs)
        require(decision.get("status") == expected,
                f"{kwargs}: expected {expected}, received {decision}")
        return decision

    def pill(self, pill_id):
        return self.page.locator("#" + pill_id).get_attribute("class") or ""

    def hidden(self, element_id):
        return self.evaluate("id => document.getElementById(id).classList.contains('hidden')", element_id)

    def click_run(self):
        self.page.click("#runPipelineBtn")
        self.page.wait_for_function("state.isSimulating === false")

    def audit(self):
        return self.page.locator("#auditLogList").text_content()

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


@test("Memory-injection preset blocks without spending and reports every violated rule")
def unauthorized_target(d):
    d.scenario("memory_injection")
    d.run()
    d.expect_status("BLOCKED")
    d.expect_spent(0.002)
    d.no_pending()
    violations = " | ".join(d.decision().get("violations", []))
    for expected in ("router", "Recipient", "Unsupported", "0.10 ETH"):
        require(expected in violations, f"Missing '{expected}' violation: {violations}")


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
    require(d.decision().get("intentDigest") == expected,
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


# ---------------------------------------------------------------- isolated rules

@test("An unknown target alone is blocked when every other field is valid")
def isolated_allowlist(d):
    decision = d.expect_case("BLOCKED", target=DEAD, amount="0.004")
    require(decision["violations"] == ["Target is not the configured simulation router."],
            f"Unexpected violations: {decision['violations']}")
    d.expect_spent(0.002)
    d.no_pending()


@test("An unsupported action alone is blocked")
def unsupported_action(d):
    decision = d.expect_case("BLOCKED", action="NATIVE_TRANSFER")
    require(decision["violations"] == ["Unsupported simulation action."],
            f"Unexpected violations: {decision['violations']}")


@test("A malformed target address is blocked")
def malformed_target(d):
    decision = d.expect_case("BLOCKED", target="0x123")
    require(decision["violations"] == ["Target is not a well-formed 20-byte address."],
            f"Unexpected violations: {decision['violations']}")


@test("A minimum output above the estimate is blocked")
def min_above_estimate(d):
    decision = d.expect_case("BLOCKED", est="6.12", min="7")
    require(decision["violations"] == ["A positive valid quote and minimum output are required."],
            f"Unexpected violations: {decision['violations']}")


@test("A rebalance with zero quotes is blocked and the slippage pill agrees")
def zero_quote_rebalance(d):
    d.expect_case("BLOCKED", action="TREASURY_REBALANCE", est="0", min="0")
    require("rose" in d.pill("inv-slippage") and "emerald" not in d.pill("inv-slippage"),
            "Slippage pill does not agree with the BLOCKED decision")


@test("A recipient outside the configured vault is blocked")
def foreign_recipient(d):
    decision = d.expect_case("BLOCKED", recipient="0x2222222222222222222222222222222222222222")
    require(decision["violations"] == ["Recipient is not the configured simulation vault."],
            f"Unexpected violations: {decision['violations']}")
    require("rose" in d.pill("inv-whitelist"), "Allowlist pill does not show the recipient failure")


@test("A malformed recipient is blocked")
def malformed_recipient(d):
    decision = d.expect_case("BLOCKED", recipient="0xabc")
    require(decision["violations"] == ["Recipient is not the configured simulation vault."],
            f"Unexpected violations: {decision['violations']}")


@test("Pills agree with the decision: WETH target blocked, lowercase router approved")
def pills_agree(d):
    d.expect_case("BLOCKED", target="0x4200000000000000000000000000000000000006")
    require("rose" in d.pill("inv-whitelist"), "WETH target shows a passing allowlist pill")
    d.expect_case("APPROVED", target=ROUTER.lower())
    require("emerald" in d.pill("inv-whitelist"), "Lowercase router shows a failing allowlist pill")


@test("A consumed nonce is blocked at dispatch")
def consumed_nonce(d):
    d.scenario("routine")
    d.evaluate("() => { state.consumedNonces.add(state.activeNonce + 1); }")
    d.run()
    d.expect_status("BLOCKED")
    require("nonce" in d.decision().get("reason", "").lower(), "Nonce rejection missing")
    d.expect_spent(0.002)


@test("A tampered chain ID is rejected at confirmation")
def tampered_domain(d):
    d.elevate()
    d.evaluate("""() => {
        state.pendingElevatedIntent = {...state.pendingElevatedIntent,
          intent: {...state.pendingElevatedIntent.intent, chainId: 1}};
    }""")
    d.confirm()
    d.expect_status("BLOCKED")
    require("domain" in d.decision().get("reason", "").lower(), "Domain mismatch rejection missing")
    d.expect_spent(0.002)
    d.no_pending()


@test("Hashing failure at confirmation blocks, consumes the review, and spends nothing")
def confirmation_hash_failure(d):
    d.elevate()
    nonce = d.evaluate("state.pendingElevatedIntent.intent.nonce")
    d.evaluate("""() => {
        computeCompleteCanonicalDigest = async () => { throw new Error('test: crypto unavailable'); };
    }""")
    d.confirm()
    d.expect_status("BLOCKED")
    require("crypto unavailable" in d.decision().get("reason", ""), "Injected error not reported")
    d.expect_spent(0.002)
    d.no_pending()
    require(not d.evaluate("nonce => state.consumedNonces.has(nonce)", nonce),
            "A failed confirmation consumed the nonce")


@test("The digest does not depend on object key order")
def digest_key_order(d):
    digests = d.evaluate("""async () => [
        await computeCompleteCanonicalDigest({b: 1, a: [{d: 1, c: 2}]}),
        await computeCompleteCanonicalDigest({a: [{c: 2, d: 1}], b: 1})]""")
    require(digests[0] == digests[1], "Key order changed the digest")
    serialized = json.dumps({"a": [{"c": 2, "d": 1}], "b": 1}, sort_keys=True, separators=(",", ":"))
    require(digests[0] == "0x" + hashlib.sha256(serialized.encode()).hexdigest(),
            "Digest differs from the independently computed value")


@test("Human-approved spend counts toward the hourly cap")
def approved_spend_counts(d):
    d.elevate()
    d.confirm()
    d.expect_status("SIMULATED_AUTHORIZED")
    d.expect_spent(0.042)
    d.scenario("routine")
    d.run()
    d.expect_status("ELEVATED")
    d.expect_spent(0.042)


@test("HTML in the prompt field renders inert everywhere")
def prompt_injection_inert(d):
    payload = "<img src=x onerror=window.__test_xss2=true><script>window.__test_xss3=true</script>"
    d.scenario("routine")
    d.fill("promptInput", payload)
    d.run()
    d.expect_status("APPROVED")
    require(not d.evaluate("window.__test_xss2 === true || window.__test_xss3 === true"),
            "Injected markup executed")
    for selector in ("#stage1Json", "#pdrTisDisplay", "#outcomeBanner", "#auditLogList",
                     "#pdrAttestationDisplay"):
        require(d.page.locator(f"{selector} img, {selector} script").count() == 0,
                f"Markup became live DOM inside {selector}")
    require("<img" in d.page.locator("#stage1Json").text_content(),
            "Prompt text was not displayed as inert text")


# ---------------------------------------------------------------- boundaries

@test("Per-transaction cap boundary: 0.005 ETH approves, 0.006 ETH elevates")
def tx_cap_boundary(d):
    d.expect_case("APPROVED", amount="0.005")
    d.expect_case("ELEVATED", amount="0.006")


@test("Hard ceiling boundary: 0.10 ETH elevates, 0.100000001 ETH blocks")
def ceiling_boundary(d):
    d.expect_case("ELEVATED", amount="0.1")
    d.expect_case("BLOCKED", amount="0.100000001")


@test("Gas boundary: 15 Gwei approves, 15.01 Gwei blocks")
def gas_boundary(d):
    d.expect_case("APPROVED", gas="15")
    d.expect_case("BLOCKED", gas="15.01")


@test("Slippage boundary: exactly 1% approves, just over 1% blocks")
def slippage_boundary(d):
    d.expect_case("APPROVED", est="100", min="99")
    d.expect_case("BLOCKED", est="100", min="98.99")


@test("Hourly velocity boundary: exactly 0.02 ETH approves, 0.0201 ETH elevates")
def velocity_boundary(d):
    d.expect_case("APPROVED", amount="0.005", events=[{"amount": 0.015, "ageMs": 0}])
    d.expect_case("ELEVATED", amount="0.005", events=[{"amount": 0.0151, "ageMs": 0}])


@test("Spend events expire at exactly one hour")
def one_hour_edge(d):
    d.evaluate("""() => {
        state.spendEvents = [{time: Date.now() - 3600000, amount: 0.5},
                             {time: Date.now() - 3590000, amount: 0.004}];
        refreshBudget();
    }""")
    d.expect_spent(0.004)


@test("More than nine decimal places of ETH is blocked")
def precision_limit(d):
    decision = d.expect_case("BLOCKED", amount="0.0010000001")
    require(decision["violations"] == ["Simulation supports at most nine decimal places of ETH."],
            f"Unexpected violations: {decision['violations']}")


# ---------------------------------------------------------------- lifecycle

@test("Halt before dispatch blocks; re-arming restores operation")
def halt_before_dispatch(d):
    d.evaluate("() => { toggleKillSwitch(); }")
    d.run()
    d.expect_status("BLOCKED")
    require("halt" in d.decision().get("reason", "").lower(), "Halt reason missing")
    d.expect_spent(0.002)
    d.evaluate("() => { toggleKillSwitch(); }")
    d.run()
    d.expect_status("APPROVED")
    d.expect_spent(0.004)


@test("Halt during Stage 3 aborts, writes a decision, and re-enables the UI")
def halt_during_stage3(d):
    d.evaluate("() => { window.__p = runPipelineSimulation(); }")
    d.page.wait_for_function(
        "document.getElementById('pipelineStatusBadge').textContent.includes('Stage 3')")
    d.evaluate("() => { toggleKillSwitch(); }")
    d.evaluate("async () => { await window.__p; }")
    require("ABORTED" in d.page.locator("#outcomeBanner").text_content(), "ABORTED banner missing")
    d.expect_status("BLOCKED")
    d.expect_spent(0.002)
    d.no_pending()
    require(not d.evaluate("state.isSimulating"), "Run state stuck")
    require(d.page.locator("#runPipelineBtn").is_enabled(), "Run button stayed disabled")


@test("Controls lock during a run and scenario loads are ignored")
def controls_locked(d):
    d.evaluate("() => { window.__p = runPipelineSimulation(); }")
    require(d.page.locator("#amountInput").is_disabled(), "Amount input not locked")
    require(d.page.locator("#runPipelineBtn").is_disabled(), "Run button not locked")
    require(d.evaluate("""() => [...document.querySelectorAll('button[onclick^="loadScenario"]')]
                          .every(b => b.disabled)"""), "Scenario buttons not locked")
    d.evaluate("() => loadScenario('memory_injection')")
    require(d.page.locator("#amountInput").input_value() == "0.002", "Scenario load changed the form mid-run")
    d.evaluate("async () => { await window.__p; }")
    require(d.page.locator("#amountInput").is_enabled(), "Inputs stayed locked")
    d.expect_status("APPROVED")


@test("Reset View discards a pending review")
def reset_discards_pending(d):
    d.elevate()
    d.page.locator("button", has_text="Reset View").click()
    d.no_pending()
    require(d.hidden("stage4Content"), "Stage 4 stayed visible after reset")
    d.confirm()
    d.expect_spent(0.002)


@test("Each outcome writes an audit entry")
def audit_entries(d):
    d.run()
    require("POLICY_APPROVE" in d.audit(), "Approval not logged")
    d.scenario("memory_injection")
    d.run()
    require("POLICY_BLOCK" in d.audit(), "Block not logged")
    d.scenario("elevated_rebalance")
    d.run()
    d.expect_status("ELEVATED")
    require("ELEVATION" in d.audit(), "Elevation not logged")


# ---------------------------------------------------------------- click-through

@test("Click-through: routine preset approves with all pills green and a restored button")
def click_routine(d):
    d.page.locator("button", has_text="A. Routine Arbitrage Swap").click()
    d.click_run()
    d.expect_status("APPROVED")
    for pill in ("inv-whitelist", "inv-spend", "inv-velocity", "inv-slippage", "inv-gas", "inv-integrity"):
        require("emerald" in d.pill(pill), f"{pill} is not green")
    require(not d.hidden("stage4Content"), "Outcome panel hidden")
    require("Dispatch Agent Tool Call" in d.page.locator("#runPipelineBtn").text_content(),
            "Run button label was not restored")
    require(d.page.locator("#runPipelineBtn i.ph-play-fill").count() == 1, "Run button icon was lost")
    require("Simulated Execution Passed" in d.page.locator("#pipelineStatusBadge").text_content(),
            "Header badge not updated")


@test("Click-through: slippage preset shows a red pill, a banner, a log entry and a badge")
def click_blocked(d):
    d.page.locator("button", has_text="C. MEV Sandwich").click()
    d.click_run()
    decision = d.decision()
    require(decision["status"] == "BLOCKED" and len(decision["violations"]) == 1,
            f"Unexpected decision: {decision}")
    require("rose" in d.pill("inv-slippage"), "Slippage pill is not red")
    require("emerald" in d.pill("inv-whitelist"), "Allowlist pill should pass")
    require(not d.hidden("stage3Content") and not d.hidden("stage4Content"), "Stages not shown")
    require("Slippage" in d.page.locator("#outcomeBanner").text_content(), "Banner lacks the reason")
    require("Blocked by Policy" in d.page.locator("#pipelineStatusBadge").text_content(), "Badge not updated")
    require("POLICY_BLOCK" in d.audit(), "Block not logged")


@test("Click-through: elevated flow opens the review, confirms, and removes the button")
def click_elevated_confirm(d):
    d.page.locator("button", has_text="D. Treasury Rebalance").click()
    d.click_run()
    d.expect_status("ELEVATED")
    d.page.click("#openLedgerBtn")
    require(not d.hidden("ledgerModal"), "Review modal did not open")
    require(d.page.locator("#ledgerModalAction").text_content() == "TREASURY_REBALANCE",
            "Modal shows the wrong action")
    d.page.click("#ledgerConfirmBtn")
    d.page.wait_for_function("state.pendingElevatedIntent === null && state.epochSpentEth > 0.04")
    d.expect_status("SIMULATED_AUTHORIZED")
    require(d.hidden("ledgerModal"), "Modal stayed open")
    require(d.page.locator("#openLedgerBtn").count() == 0, "Stale review button remains")
    require("SIMULATED HUMAN APPROVAL CONFIRMED" in d.page.locator("#outcomeBanner").text_content(),
            "Confirmation banner missing")


@test("Click-through: rejecting a review discards it and removes the button")
def click_reject(d):
    d.page.locator("button", has_text="D. Treasury Rebalance").click()
    d.click_run()
    d.page.click("#openLedgerBtn")
    d.page.locator("#ledgerModal button", has_text="Reject & Cancel Transaction").click()
    d.no_pending()
    require(d.hidden("ledgerModal"), "Modal stayed open")
    require(d.page.locator("#openLedgerBtn").count() == 0, "Stale review button remains")
    require("Review Rejected" in d.page.locator("#pipelineStatusBadge").text_content(), "Badge stale")
    d.expect_spent(0.002)


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
                        page_errors = []
                        page.on("pageerror", lambda error, sink=page_errors: sink.append(str(error)))
                        page.set_default_timeout(TIMEOUT_MS)
                        response = page.goto(URL, wait_until="domcontentloaded")
                        require(response is not None and response.status == 200,
                                "Target page did not return HTTP 200")
                        source_hashes.add(hashlib.sha256(response.body()).hexdigest())
                        page.wait_for_function("typeof evaluateIntent === 'function' && typeof state === 'object'")
                        demo = Demo(page, page_errors)
                        demo.scenario("routine")
                        demo.expect_spent(0.002)
                        demo.no_pending()
                        function(demo)
                        require(not page_errors, f"Uncaught page errors: {page_errors}")
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