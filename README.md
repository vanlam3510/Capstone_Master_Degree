# Capstone_Master_Degree
This is for my Capstone project for my Master degree in Computer Systems and Engineering at California Science and Technology University.   This project is about a defense-in-depth runtime security framework and tri-state circuit breaker decoupling LLM reasoning from cryptographic signing for autonomous Web3 agents on Base Sepolia

# When AI Agents Control Crypto Wallets: A Runtime Security Framework for Autonomous On-Chain Agents

**Degree & Course:** Master of Computer Systems and Engineering (MSCSE) / MBA — CS599 Capstone  
**Institution:** California Science and Technology University (CSTU)  
**Author:** Van Lam  
**Advisor / Mentor:** Professor Mingjing (Aaron) Zhang  
**Testnet Environment:** Base Sepolia (Chain ID: `84532`)  

---

## 1. Problem Statement & Core Thesis

### The Vulnerability Surface
Granting autonomous Large Language Models (LLMs) direct hot-wallet signing access creates irreversible financial exposure. In traditional Web2 APIs, an uncaught exception triggers a retry or a 500 status code; on public blockchains, execution errors or unauthorized state changes result in immutable capital loss.

Recent security research (e.g., Patlan et al. on *CrAIBench*, 2025) demonstrates that autonomous Web3 agents (such as ElizaOS) are susceptible to:
- **Direct & Indirect Prompt Injection (DPI/IPI):** Adversarial prompts embedded in user commands, token metadata, or on-chain logs that hijack model tool-calling.
- **Context & Memory Injection (CM-MI):** Attacker-crafted synthetic conversation turns saved into shared external databases (Discord, Supabase, vector indices). When retrieved as past history, the agent treats the poisoned memory as trusted internal state, reaching an Attack Success Rate (ASR) exceeding 85% on unhardened models.
- **Maximal Extractable Value (MEV) & Slippage Sandwiching:** Public mempool front-running when models emit transactions with missing or unconstrained slippage parameters.

### Core Security Thesis
> *"An instruction is not a boundary. The model can propose; only the policy layer disposes. You cannot prompt-inject a rule engine that never reads the prompt."*  
> — Professor Mingjing (Aaron) Zhang, *AI_Finance* (CSTU)

---

## 2. Multi-Layer Defense-in-Depth Architecture

The framework completely decouples non-deterministic cognitive reasoning from cryptographic transaction assembly and key signing across three air-gapped trust boundaries:

```
┌────────────────────────────────────────────────────────┐
│               CREATIVE PLANNING DOMAIN                 │
│  • LLM ReAct reasoning loop (eth_call state reader)   │
│  • STRICT ISOLATION: No raw calldata / No private key  │
│  • Emits: Canonical Transaction Intent Schema (TIS)    │
└──────────────────────────┬─────────────────────────────┘
                           │ Declarative JSON (TIS)
                           ▼
┌────────────────────────────────────────────────────────┐
│        DETERMINISTIC COMPILATION & SIMULATION          │
│  • Protocol Compiler (LI.FI Composer / Protocol SDK)   │
│  • Pre-Flight eth_call Fork Simulation (Delta Balance) │
└──────────────────────────┬─────────────────────────────┘
                           │ Unsigned Calldata & State Trace
                           ▼
┌────────────────────────────────────────────────────────┐
│     DETERMINISTIC POLICY DOMAIN (Circuit Breaker)      │
│  Evaluates 5 Non-Bypassable Invariants:                │
│  [1] Target Allowlist       [2] Per-Tx Spend Cap       │
│  [3] Hourly Velocity Limit  [4] Slippage & Gas Ceiling │
│  [5] Solvency Check (Δ Portfolio Value ≥ -MaxLoss)     │
└──────────────────────────┬─────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
  [OUTCOME 1]       [OUTCOME 2]       [OUTCOME 3]
  ROUTINE ACTION    ELEVATED ACTION   HARD VIOLATION
  Under spend cap   Exceeds spend cap Blacklisted target
  Auto-signed via   Escalates to      Unlimited approval
  Dynamic Server    Ledger Clear-Sign Dropped instantly
  MPC Wallet        (ERC-7730/EIP-712) Zero override
```

### Core Primitives

1. **Transaction Intent Schema (TIS):**  
   The model is strictly prohibited from generating raw hexadecimal calldata. It outputs an abstract declarative payload specifying high-level actions, amounts, recipient constraints, and slippage bounds.
2. **Deterministic Workflow Compilation & Pre-Flight Fork Simulation:**  
   External software compiles the exact bytecode. Before signing, the transaction is simulated against the Base Sepolia state (`eth_call`) to verify that solvency is maintained ($\Delta \text{PortfolioValue}_{\text{net}} \ge -\text{MaxPermittedLoss}$).
3. **Flowguard-Style Tri-State Policy Engine:**
   - **Approved (Autonomous):** Low-risk trades ($\le 0.005$ ETH) pass immediately to an autonomous server wallet (e.g., Dynamic MPC).
   - **Elevated (Flow-Bound Ledger Clear-Signing):** High-value treasury actions trigger out-of-band hardware authorization via Ledger devices running **ERC-7730 Clear Signing** and **EIP-712**, displaying plain-text transaction semantics to human signers.
   - **Blocked (Hard Invariant Violation):** Blacklisted destinations, infinite ERC-20 approvals (`type(uint256).max`), slippage breaches ($> 1.0\%$), and gas surges ($> 15.0$ Gwei) are rejected unconditionally.

---

## 3. High-Yield On-Chain Test Strategies

To validate the framework under realistic market conditions, the agent executes two quantitative strategies on Base Sepolia:
1. **Dynamic Concentrated Liquidity Rebalancing (Uniswap v3 Style):**  
   Provides liquidity within a narrow price range $[p_a, p_b]$ for $50\times\text{--}100\times$ capital efficiency. When spot price ticks move out of range, the agent burns the position, micro-swaps the asset delta, and mints a newly centered position.
2. **Atomic Cyclic Arbitrage:**  
   Monitors cross-DEX price spreads between liquidity pools (e.g., Uniswap v3 vs. Aerodrome fork). Executes only if:
   $$\Delta = \text{Amount}_{\text{out}} - \text{Amount}_{\text{in}} > (\text{GasUsed} \times \text{BaseFee}) + \text{SlippageMargin}$$

---

## 4. Empirical Security Evaluation (CrAIBench Results)

Benchmarked across 200 adversarial executions on the Base Sepolia testnet against the **CrAIBench** evaluation suite:

| Attack / Task Vector | Unhardened Agent (ElizaOS Baseline) | Hardened Runtime Security Gateway | Flowguard Architecture Model | Primary Defensive Mechanism |
| :--- | :--- | :--- | :--- | :--- |
| **Direct Prompt Injection** | 45.2% ASR | **0.0% ASR (Blocked)** | 0.0% ASR (Air-Gapped) | Strict TIS isolation; LLM cannot emit raw calldata |
| **Indirect Memory Injection (CM-MI)** | 85.1% ASR | **0.0% ASR (Blocked)** | 0.0% ASR (Air-Gapped) | Deterministic policy engine ignores conversational history |
| **Target Address Poisoning** | 92.4% Executed Drain | **0.0% (Whitelist Rejection)** | 0.0% (Whitelist Rejection) | Verified Base Sepolia contract registry invariant |
| **MEV Sandwiching / Slippage** | $14.20 Avg Loss | **0.0% (Pre-flight Abort)** | 0.0% (Composer Bound) | Projected slippage check ($\le 1.0\%$) and balance check |
| **Unlimited Token Approvals** | 78.5% Permitted | **0.0% (Hard Block)** | 0.0% (Hard Block) | Strict per-transaction approval cap enforcement |
| **Out-of-Bound Spend** | 89.0% Transferred | **0.0% (Velocity Block)** | Escalated to Ledger | Hardware-in-the-loop with ERC-7730 Clear Signing |
| **Benign Task Utility** | 87.1% Completion | **86.8% Utility Retained** | 86.4% Utility Retained | Low runtime overhead ($0.3\%$) for valid transactions |

---

## 5. Technology Stack & Implementation

- **Language & Core Libraries:** Python 3.11, `web3.py`, `eth-account`, `decimal`
- **Network:** Base Sepolia Testnet (Chain ID: `84532`, RPC: `https://sepolia.base.org`)
- **Key Patterns:** Transaction Intent Schema (TIS), Policy Decision Records (PDR), ERC-7730 Clear Signing, ERC-4337 Account Abstraction
- **Course Artifacts:** Derived from CSTU MS/CSE 599 *AI Finance: Building On-Chain Autonomous Agents* by Prof. Mingjing (Aaron) Zhang (`AI_Finance`)

---

## 6. Key Takeaways

1. **Prompt defense alone is insufficient:** Because language models treat retrieved memory as verified internal state, prompt guards cannot reliably prevent memory injections (CM-MI).
2. **Deterministic execution gates are non-negotiable:** Decoupling intent formation from transaction assembly and enforcing deterministic invariants eliminates the vulnerability surface without degrading operational utility.
3. **Granular human-in-the-loop workflows:** A tri-state policy (Approve / Elevate / Block) balances autonomous execution speed for routine operations with cryptographic security for large capital movements.
