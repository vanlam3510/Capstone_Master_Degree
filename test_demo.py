"""
Playwright automated regression suite for Agent Runtime Security Framework (index.html).
Validates 26 policy, lifecycle, UI state, and input-sanitization checks.

Prerequisites:
    pip install playwright
    playwright install chromium

Usage:
    # 1. In one terminal, serve your index.html:
    python3 -m http.server 8004 --bind 127.0.0.1

    # 2. In another terminal, run this test suite:
    python3 test_demo.py
"""

import json
import os
import sys
import time
from playwright.sync_api import sync_playwright

TEST_URL = os.getenv("CAPSTONE_TEST_URL", "http://127.0.0.1:8004/index.html")

results = []

def record(test_id, name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] Check {test_id:02d}: {name} {f'- {detail}' if detail else ''}")
    results.append({
        "id": test_id,
        "name": name,
        "status": status,
        "detail": detail
    })

def run_tests():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        # Isolate local policy tests from external network dependencies
        context.route("**/*", lambda route, req: (
            route.abort() if any(cdn in req.url for cdn in ["cdn.tailwindcss.com", "unpkg.com", "fonts.googleapis.com", "fonts.gstatic.com"])
            else route.continue_()
        ))

        page = context.new_page()
        page.goto(TEST_URL)
        page.wait_for_load_state("domcontentloaded")

        def reset():
            page.evaluate("resetPipeline()")
            page.evaluate("state.pendingElevatedIntent = null")
            page.evaluate("if(state.masterKillSwitch) toggleKillSwitch()")

        def get_stage_text(stage_id):
            return page.inner_text(f"#{stage_id}Badge").strip()

        def dispatch():
            page.click("#runPipelineBtn")
            page.wait_for_timeout(1800)

        # ---------------------------------------------------------------------
        # 1-4: Preset Scenarios
        # ---------------------------------------------------------------------
        # Check 01: Preset A (Routine Swap) -> APPROVED
        reset()
        page.evaluate("loadScenario('routine')")
        dispatch()
        badge = get_stage_text("stage4")
        record(1, "Preset A: Routine Swap Approved", "Approved" in badge, f"Badge: {badge}")

        # Check 02: Preset B (Memory Injection) -> BLOCKED
        reset()
        page.evaluate("loadScenario('memory_injection')")
        dispatch()
        badge = get_stage_text("stage4")
        record(2, "Preset B: Memory Injection Blocked", "Blocked" in badge, f"Badge: {badge}")

        # Check 03: Preset C (MEV Slippage) -> BLOCKED
        reset()
        page.evaluate("loadScenario('mev_slippage')")
        dispatch()
        badge = get_stage_text("stage4")
        record(3, "Preset C: MEV Slippage Breach Blocked", "Blocked" in badge, f"Badge: {badge}")

        # Check 04: Preset D (Elevated Rebalance) -> ELEVATED
        reset()
        page.evaluate("loadScenario('elevated_rebalance')")
        dispatch()
        badge = get_stage_text("stage4")
        record(4, "Preset D: High-Value Rebalance Elevated", "Elevated" in badge, f"Badge: {badge}")

        # ---------------------------------------------------------------------
        # 5-8: Gas Bounds & Negative Input Checks
        # ---------------------------------------------------------------------
        # Check 05: Reject Negative Gas
        reset()
        page.fill("#gasInput", "-5")
        page.dispatch_event("#gasInput", "input")
        dispatch()
        record(5, "Reject Negative Gas (-5 Gwei)", "Blocked" in get_stage_text("stage4"))

        # Check 06: Reject Gas Exceeding Ceiling (> 15 Gwei)
        reset()
        page.fill("#gasInput", "20")
        page.dispatch_event("#gasInput", "input")
        dispatch()
        record(6, "Reject Gas > 15 Gwei", "Blocked" in get_stage_text("stage4"))

        # Check 07: Accept Valid Zero Gas
        reset()
        page.fill("#gasInput", "0")
        page.dispatch_event("#gasInput", "input")
        page.evaluate("loadScenario('routine')")
        page.fill("#gasInput", "0")
        page.dispatch_event("#gasInput", "input")
        dispatch()
        record(7, "Accept Valid 0 Gwei Gas Input", "Approved" in get_stage_text("stage4"))

        # Check 08: Reject Blank / Non-numeric Gas
        reset()
        page.fill("#gasInput", "")
        page.dispatch_event("#gasInput", "input")
        dispatch()
        record(8, "Reject Blank / NaN Gas Input", "Blocked" in get_stage_text("stage4"))

        # ---------------------------------------------------------------------
        # 9-12: Amount & Ceiling Checks
        # ---------------------------------------------------------------------
        # Check 09: Reject Zero Spend Amount
        reset()
        page.fill("#amountInput", "0")
        dispatch()
        record(9, "Reject Zero Amount (0 ETH)", "Blocked" in get_stage_text("stage4"))

        # Check 10: Reject Negative Spend Amount
        reset()
        page.fill("#amountInput", "-1.5")
        dispatch()
        record(10, "Reject Negative Amount (-1.5 ETH)", "Blocked" in get_stage_text("stage4"))

        # Check 11: Elevate Spend Above Autonomous Cap (0.04 ETH <= 0.10 ETH)
        reset()
        page.fill("#amountInput", "0.04")
        dispatch()
        record(11, "Elevate Amount > 0.005 ETH Cap", "Elevated" in get_stage_text("stage4"))

        # Check 12: Hard Block Spend Exceeding 0.10 ETH Ceiling
        reset()
        page.fill("#amountInput", "0.20")
        dispatch()
        record(12, "Hard Block Spend > 0.10 ETH Absolute Ceiling", "Blocked" in get_stage_text("stage4"))

        # ---------------------------------------------------------------------
        # 13-16: Slippage, Quotes, and Address Formatting
        # ---------------------------------------------------------------------
        # Check 13: Inverted Quote (minOut > estOut) Rejection
        reset()
        page.fill("#estOutInput", "5.0")
        page.fill("#minOutInput", "6.0")
        dispatch()
        record(13, "Reject Inverted Quote (minOut > estOut)", "Blocked" in get_stage_text("stage4"))

        # Check 14: Zero Quote Return Rejection
        reset()
        page.fill("#estOutInput", "0")
        page.fill("#minOutInput", "0")
        dispatch()
        record(14, "Reject Zero Output Estimates", "Blocked" in get_stage_text("stage4"))

        # Check 15: Target Address Regex Validation (Malformed Hex)
        reset()
        page.fill("#targetInput", "0xInvalidAddressLength")
        dispatch()
        record(15, "Reject Malformed EVM Address Format", "Blocked" in get_stage_text("stage4"))

        # Check 16: HTML / XSS Injection Neutralization in Target Field
        reset()
        xss_payload = "<img src=x onerror=window.__xss_tripped=true>"
        page.fill("#targetInput", xss_payload)
        dispatch()
        xss_executed = page.evaluate("window.__xss_tripped === true")
        record(16, "Neutralize HTML/XSS Payload in Target Input", not xss_executed and "Blocked" in get_stage_text("stage4"))

        # ---------------------------------------------------------------------
        # 17-21: Approval Lifecycle & Confirmation Edge Cases
        # ---------------------------------------------------------------------
        # Check 17: Invalidate Stale Elevated Authorization on New Run
        reset()
        page.evaluate("loadScenario('elevated_rebalance')")
        dispatch()
        page.evaluate("loadScenario('memory_injection')")
        dispatch()
        pending = page.evaluate("state.pendingElevatedIntent")
        record(17, "Invalidate Stale Review on Subsequent Dispatch", pending is None)

        # Check 18: Reject Confirmation After Rejection
        reset()
        page.evaluate("loadScenario('elevated_rebalance')")
        dispatch()
        page.evaluate("rejectLedgerSignature()")
        page.evaluate("confirmLedgerSignature()")
        badge = page.inner_text("#pipelineStatusBadge")
        record(18, "Prevent Confirming After Modal Rejection", "Executed" not in badge)

        # Check 19: Block Confirmation if Gas Surges Above 15 Gwei During Human Review
        reset()
        page.evaluate("loadScenario('elevated_rebalance')")
        dispatch()
        page.fill("#gasInput", "25")
        page.dispatch_event("#gasInput", "input")
        page.evaluate("confirmLedgerSignature()")
        badge = page.inner_text("#pipelineStatusBadge")
        record(19, "Block Confirmation if Live Gas Spikes (>15 Gwei)", "Executed" not in badge)

        # Check 20: Prevent Duplicate Consumption of Consumed Intent
        reset()
        page.evaluate("loadScenario('elevated_rebalance')")
        dispatch()
        page.evaluate("confirmLedgerSignature()")
        spent_after_first = page.evaluate("state.epochSpentEth")
        page.evaluate("confirmLedgerSignature()")
        spent_after_second = page.evaluate("state.epochSpentEth")
        record(20, "Prevent Replay / Duplicate Confirmation", spent_after_first == spent_after_second)

        # Check 21: Emergency Halt Blocks Active Confirmation
        reset()
        page.evaluate("loadScenario('elevated_rebalance')")
        dispatch()
        page.evaluate("toggleKillSwitch()")
        page.evaluate("confirmLedgerSignature()")
        badge = page.inner_text("#pipelineStatusBadge")
        record(21, "Emergency Kill Switch Blocks Pending Confirmation", "Executed" not in badge)

        # ---------------------------------------------------------------------
        # 22-26: Digest Verification, Budget & State Integrity
        # ---------------------------------------------------------------------
        # Check 22: Mid-Pipeline Halt Aborts Dispatch
        reset()
        page.evaluate("toggleKillSwitch()")
        dispatch()
        badge = page.inner_text("#pipelineStatusBadge")
        record(22, "Circuit Breaker Blocks Tool Dispatch at Entry", "Neutralized" in badge or "Halted" in badge or "Awaiting" in badge)

        # Check 23: Action Type Switching Preserves Quote Validation
        reset()
        page.select_option("#actionTypeSelect", "SWAP_EXACT_IN")
        page.fill("#amountInput", "0.015")
        page.fill("#estOutInput", "10.0")
        page.fill("#minOutInput", "5.0") # 50% slippage -> breach
        dispatch()
        record(23, "Action Type Preservation (Swap Quote Checks)", "Blocked" in get_stage_text("stage4"))

        # Check 24: Canonical SHA-256 Digest Matches Standard Hashing
        reset()
        page.evaluate("loadScenario('routine')")
        dispatch()
        tis_raw = page.inner_text("#stage1Json")
        tis = json.loads(tis_raw)
        preimage = ":".join([
            str(tis.get("intentId", "")),
            str(tis.get("action", "")),
            str(tis.get("protocol", "")),
            str(tis.get("chainId", "")),
            str(tis.get("targetContract", "")),
            str(tis.get("amountEth", "")),
            str(tis.get("estReturn", "")),
            str(tis.get("minReturn", "")),
            str(tis.get("recipient", "")),
            str(tis.get("deadline", "")),
            str(tis.get("nonce", ""))
        ])
        import hashlib
        expected_hash = "0x" + hashlib.sha256(preimage.encode("utf-8")).hexdigest()
        generated_hash = page.evaluate("computeCompleteCanonicalDigest(JSON.parse(document.getElementById('stage1Json').innerText))")
        record(24, "Independent SHA-256 Canonical Digest Verification", expected_hash.lower() == generated_hash.lower())

        # Check 25: Hourly Rolling Budget Accumulator Integrity
        reset()
        page.evaluate("state.epochSpentEth = 0.019")
        page.evaluate("updateTelemetryUI()")
        page.fill("#amountInput", "0.003") # 0.019 + 0.003 = 0.022 ETH > 0.02 ETH
        dispatch()
        record(25, "Enforce Hourly Rolling Budget (0.02 ETH Velocity)", "Elevated" in get_stage_text("stage4"))

        # Check 26: Hardware Ceiling Rejection Leaves Budget Unchanged
        reset()
        initial_spent = page.evaluate("state.epochSpentEth")
        page.fill("#amountInput", "0.50")
        dispatch()
        after_spent = page.evaluate("state.epochSpentEth")
        record(26, "Hard Ceiling Drop Leaves Spending Counter Unchanged", initial_spent == after_spent)

        # Output Summary
        browser.close()

    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = total - passed

    print("\n" + "=" * 60)
    print(f"REGRESSION SUITE FINISHED: {passed}/{total} Passed ({failed} Failures)")
    print("=" * 60)

    with open("regression-results.json", "w") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "totalChecks": total,
            "passed": passed,
            "failed": failed,
            "checks": results
        }, f, indent=2)

    print("Detailed evidence saved to regression-results.json")
    if failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    run_tests()