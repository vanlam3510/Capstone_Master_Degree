# Capstone review: report, repository, and supplied research

Reviewed 29 October 2026. Repository HEAD: `760bb533cf94d20bff0082a46288d9fe12295355`.

## Scope and conclusion

Reviewed the 19-page capstone PDF, README, and both HTML files, and compared relevant threat-model, architecture, and evaluation sections in the two supplied papers. The HTML files are identical except for their final newline. Browser edge-case checks ran against `index.html`; their source findings apply to both copies. No repository files were changed. Reproducer: `/workspace/review-artifacts/check_demo.py`.

The separation of planning, policy, and signing is a defensible design direction supported by Alqithami. However, the submitted artifacts do not establish the deployed system or experimental results claimed in the report. The checkout is a static JavaScript simulation, and the Python listing in the PDF is a substantially smaller binary validator than the architecture described. Resolve this scope mismatch before presenting the work as an experimentally validated on-chain security implementation.

Absence of evidence in this checkout does not establish that experiments never happened. It does mean a reviewer cannot reproduce or verify them from the submission.

## 1. Highest-priority claim and evidence discrepancies

### 1.1 Implemented system versus simulation — critical

PDF pp. 2, 6, 12–18 and README lines 72–113 describe Python/Web3 execution, fork simulation, real transactions, signing, trading strategies, and evaluation. Tracked files consist only of the PDF, README, license, and two HTML pages. There is no `runtime_security_agent.py`, `read_chain.py`, dependency manifest, contract source/ABI, deployment record, actual benchmark runner, or results dataset.

The HTML generates its TIS from form inputs, waits with timers, generates a random hexadecimal string, and updates DOM elements. It does not invoke an LLM, compile transaction calldata, call an RPC, simulate EVM execution, request a Ledger signature, use MPC, or broadcast transactions. Receipt block numbers and gas use are random (`index.html:1123`); benchmark numbers are static table text (`index.html:434`).

Correction: explicitly distinguish proposed architecture, executable browser simulation, PDF illustrative listing, and separately verified deployments. If a real implementation exists elsewhere, include its exact commit, instructions, and evidence. Label simulated receipts and signatures on the UI, including copied/exported artifacts.

### 1.2 Benchmark provenance — critical

PDF pp. 16–18, README lines 92–104, and the demo report 200 adversarial executions, 0% ASR, 86.8% utility, and monetary loss figures. The checkout contains no corresponding harness, prompts, model configuration, run logs, transaction receipts, per-case outcomes, or statistical analysis.

The supplied Patlan paper has a particularly important mismatch: section 6.3 and Figure 10 evaluate **Qwen-2.5-14B-Instruct** and a fine-tuned defense on **31 single-step tasks and 121 MI attacks**. Figure 10 reports 83.9% default benign utility, 85.1% default MI ASR, and 87.1% benign utility / 1.7% ASR after fine-tuning. Your table assigns 85.1% ASR and 87.1% benign utility to an “ElizaOS baseline.” These are not a matched ElizaOS baseline from that experiment.

The paper also contains a separate real ElizaOS attack demonstration on Ethereum Sepolia. That does not turn the Qwen benchmark into a Base Sepolia experiment. Cite the two settings separately.

Searching the supplied papers did not locate the project's 45.2%, 92.4%, 78.5%, 86.8%, 86.4%, or $14.20 results as support for the submitted comparison. Their provenance remains unresolved. Neither supplied paper substantiates the displayed Flowguard comparison.

Correction: label each number as your measured result, a cited result with exact table/model/setting, or an illustrative placeholder. Remove unsupported empirical claims until supported. If 200 is a single unweighted denominator, percentages come in 0.5-point increments; values such as 85.1% require a different denominator, averaging, or another explanation. A separate benign denominator is also required. Zero successes in 200 independent trials is an observation, not proof of impossibility; the approximate one-sided 95% upper bound is 1.5% for that tested population.

The utility change from 87.1% to 86.8% is **0.3 percentage points**, approximately 0.34% relative, and is not a measurement of runtime overhead. Report latency separately.

### 1.3 Missing cryptographic trust boundary — critical

Alqithami section 8 and Figure 5 propose TIS/PDR as a roadmap, not a universally adopted implemented standard. Section 8.3 specifies a signed authorization artifact and independent signer checks: issuer signature, signer audience, expiration, canonical intent hash, and bound constraints.

The demo's PDR is unsigned JSON containing flags and a random `calldataHash`. It lacks actual signature verification, stable canonical intent binding, signer audience, policy version/digest, effective expiry checks, and nonce consumption. The PDF listing returns a Boolean and reason; it does not issue or verify a PDR at all. A UI label naming a signature scheme does not implement that scheme.

Correction: either describe a simplified PDR-inspired visualization, or implement and test the actual binding and verifier. Separate a simulation result, policy approval, human authorization, and execution receipt. Do not imply an off-chain JSON object is an on-chain attestation without a verification mechanism.

## 2. Confirmed demo behavior defects

These are local simulation defects; no blockchain transaction or real wallet was involved. The reproducer blocks external asset requests to isolate JavaScript behavior. Styling is not validated by these tests.

| Test | Observed result | Expected under the stated policy |
| --- | --- | --- |
| Set `state.currentGasGwei=20`, run routine | `APPROVED`, with `gasCeilingVerified=false` | Hard block above 15 Gwei |
| Enter amount `-1` | `APPROVED`; spend accumulator becomes `-0.998` | Reject negative amounts; never reduce spent budget |
| Set expected and minimum output to zero | `APPROVED`, slippage verified | Reject missing/invalid quote for a swap |
| Elevate, reject, then call confirmation | “ELEVATED ACTION CONFIRMED” | Rejected authorization must be unusable |
| Elevate, trip kill switch, confirm | “ELEVATED ACTION CONFIRMED” | Halt must also guard confirmation |
| Start routine, trip halt during timer waits | `APPROVED` while halt is true | Recheck before simulated signing/dispatch |
| Elevate, load/run blocked scenario, confirm old pending intent | Old elevated action confirms | Invalidate stale pending authorization |

Relevant locations: `index.html:826` (halt checked only at entry), `:896` (policy checks), `:931` (gas flag), `:947` (outcome resolution omits gas), `:1089` (confirmation), `:1117` (rejection does not clear pending state).

Additional source findings:

- No actual time-window reset, persistence, or concurrency control exists for browser spending state. Refresh restores the initial budget. PDF code uses a resetting one-hour bucket, not a rolling window.
- Nonce/expiry integrity is displayed as passing unconditionally (`:935`); it is not verified.
- No ERC-20 approval decoding or unlimited-approval guard exists.
- No simulation failure or portfolio-solvency computation exists; the success message is static (`:327`).
- JavaScript floating point is used for monetary comparisons. Use integer base units and validated token decimals in a real implementation.
- Ledger confirmation changes the banner and budget without updating the original elevated PDR into a clearly linked final authorization/execution record.
- A random 32-hex-digit value is only 16 bytes, whereas Ethereum transaction hashes and Keccak-256 digests are 32 bytes / 64 hex digits. Neither a valid transaction hash nor a calldata commitment is produced (`:889`).
- Audit messages are seeded in memory, clearable, and lost on reload. They are demonstration telemetry, not tamper-evident audit evidence.

The four preset scenarios passed their expected outcomes during onboarding. These edge-case failures explain why that earlier smoke check does not establish security correctness.

## 3. PDF internal inconsistencies and listing defects

1. **ERC-4337 implemented versus future work:** Executive summary p. 2 lists session-key account abstraction as an introduced component; section 8 p. 18 proposes upgrading from EOA keys in future. Choose one status and document it consistently.
2. **Hourly versus daily velocity:** p. 11 states 0.02 ETH per 24 hours; Python constants/reset logic pp. 13–14 and p. 17 use hourly limits. The demo has no timed reset. Define window type, duration, persistence, and rollover behavior.
3. **Hard cap versus escalation:** p. 11 calls 0.005 ETH a hard cap, p. 10 allows elevation for larger allocations and uses 0.02 ETH as an example, while the Python listing rejects anything above 0.005 ETH. Define an autonomous ceiling, a separate human-authorized ceiling, and truly non-overridable constraints.
4. **Schema mismatch:** PDF TIS pp. 8–9 uses `inputs`, `outputs`, and nested `constraints`; listing pp. 14–16 expects `targetContract`, `amountEth`, `estReturn`, and `minReturn`. The supplied example cannot be passed directly to the shown validator. Publish a versioned schema and adapter with explicit asset units and types.
5. **Import typo:** p. 13 line 12 visibly says `from web3 import Web`, but line 20 calls `Web3`. This is a real printed typo, visually checked in the PDF, and prevents the listing from running as written.
6. **Missing calldata:** p. 16 constructs a native-value transaction with no `data` field. It cannot perform the described Uniswap swap, mint/burn liquidity position, or multi-leg arbitrage. Sending ETH to a router address is not equivalent to calling its swap function.
7. **No pre-flight engine:** The listing has no `eth_call`, trace/state-diff processing, portfolio valuation, ABI compiler, or simulator result validation.
8. **No tri-state or hardware implementation:** The listing has binary rejection and a local `PRIVATE_KEY`; it contains no Ledger/EIP-712, ERC-7730 descriptor, MPC integration, independent signer service, or session-key module.
9. **Input and exception handling:** Only JSON decoding is caught. JSON arrays/null, malformed addresses, invalid/missing numeric fields, non-finite decimals, missing keys, RPC errors, and signing failures need structured rejection. Missing quote fields default to zero and skip the slippage branch. `minReturn > estReturn` produces negative “slippage” in the listing and is accepted. Positive finite amounts must be required.
10. **Budget lifecycle:** PDF listing increments budget before signing/broadcast, without reservation/reconciliation or persistence. Failed transactions, concurrent requests, crashes, nonce races, and retries need defined semantics. Reverted transactions still incur gas.
11. **Fee policy mismatch:** The listing checks `w3.eth.gas_price` and then sets `maxFeePerGas` to twice that value, without separately bounding worst-case total fees. Define whether 15 Gwei applies to base fee, effective price, or max fee. On Base, account for applicable L1 data fees as well.
12. **Dependency compatibility:** No versions are pinned. `signed_tx.rawTransaction` is version-dependent; current eth-account uses `raw_transaction`. Supply a tested dependency set rather than assuming the listing works across releases.

## 4. Security architecture omissions

These are requirements for a real system, not features demonstrated by the current repository.

- **Trust and threat model:** Identify whether the attacker controls prompts, memory, RPCs, price feeds, compiler, host, policy administration, signer, or browser. Separate malicious-user authorization from external data. Explain which trusted components remain uncompromised for each guarantee.
- **Enforcement outside the planner:** A Python object or browser variable is not immutable or air-gapped. A host process holding the private key can bypass its own validator if compromised. Specify process/service boundaries, authenticated channels, signer API restrictions, and on-chain enforcement where needed. ERC-4337 alone does not automatically provide session-key restrictions; modules must implement them.
- **Semantic authorization:** Whitelisting the router's `to` address does not constrain output recipient, token, spender, function selector, route, multicall subcalls, permit signatures, or allowance changes. An attacker can remain within a whitelisted router and send outputs elsewhere. Verify the complete compiled transaction and final economic effects.
- **Authenticated quote and valuation:** The demo trusts editable `estOut`/`minOut`. A malicious quote can satisfy the ratio while being economically disastrous. Specify trusted/stale-price checks, token decimal handling, oracle manipulation defenses, and independent price reference.
