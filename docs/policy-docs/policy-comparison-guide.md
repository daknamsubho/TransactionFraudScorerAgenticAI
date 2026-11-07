# Policy Comparison Guide: 2025 vs. 2026 Year-on-Year (YoY) Impact

- **Document Identifier**: `GUIDE-POLICY-YOY-DIFF`
- **Purpose**: Technical and operational guide demonstrating how Year-on-Year policy updates alter transaction fraud scoring, risk factor severity, and final dispositions (`APPROVE`, `REVIEW`, `DECLINE`) for identical transaction payloads in the RAG Knowledge Layer.
- **Reference Policies**:
  - [`docs/policy-docs/fraud-risk-policy-2025.md`](./fraud-risk-policy-2025.md)
  - [`docs/policy-docs/fraud-risk-policy-2026.md`](./fraud-risk-policy-2026.md)

---

## 1. Executive Summary: The 2025 to 2026 Regulatory Paradigm Shift

Between 2025 and 2026, global card schemes and regulatory bodies enacted strict enforcement frameworks:
1. **PCI-DSS v4.0.1 Mandatory Enforcement**: Ended the transitional period on March 31, 2025, enforcing strict client-side script integrity, device fingerprinting, and non-bypassable authentication.
2. **Visa Acquirer Monitoring Program (VAMP)**: Merged the Visa Fraud Monitoring Program (VFMP) and Visa Dispute Monitoring Program (VDMP) into a single, aggressive program capping combined fraud and disputes at 0.5% (50 bps).
3. **Mastercard 72-Hour Scam Rules**: Required acquirers to investigate and freeze high-risk deceptive merchant storefronts within 72 hours.
4. **EU PSD3 & Payment Services Regulation (PSR)**: Introduced statutory consumer reimbursements for impersonation fraud and mandatory Verification-of-Payee (VoP).

These shifts compelled risk engines to **lower tolerance thresholds for high-risk MCCs (Crypto, Gambling, Wire Transfers, Digital Goods)** and **compress the straight-through `APPROVE` range**.

---

## 2. Side-by-Side Year-on-Year Policy Comparison Matrix

| Evaluation Dimension | 2025 Policy (`POL-FRAUD-2025-V4`) | 2026 Policy (`POL-FRAUD-2026-V1`) | YoY Impact on Scoring |
|---|---|---|---|
| **Global `APPROVE` Boundary** | `0.0 – 29.9` | **`0.0 – 24.9`** | Transactions with minor risk signals (25.0–29.9) are stepped up to `REVIEW`. |
| **Global `REVIEW` Boundary** | `30.0 – 69.9` | **`25.0 – 64.9`** | Wider step-up verification band; lower tolerance before escalation. |
| **Global `DECLINE` Boundary** | `70.0 – 100.0` | **`65.0 – 100.0`** | More aggressive automated blocking of high-risk transactions. |
| **Velocity (60-min window)** | `> 3` transactions triggers `MEDIUM` (+25.0); `5+` triggers `HIGH` (+50.0). | **`> 2`** triggers `VELOCITY` (+30.0); **`2+` in high-risk MCCs** triggers `HIGH` (+55.0); **`3+`** triggers `DECLINE`. | Rapid consecutive swipes face immediate rejection in 2026. |
| **24-Hour Aggregate Spend** | > $10,000.00 USD | **> $5,000.00 USD** | Cutoff halved to prevent fast synthetic credit bust-outs. |
| **Crypto Exchanges (MCC 6051)** | Allowed up to $2,500.00 without step-up; Review: $2,500 – $5,000; Decline: > $5,000. | Step-up required above **$1,000.00**; **Hard `DECLINE` > $2,000.00** for all CNP transactions. | Large unverified crypto transactions flip from `REVIEW` to immediate `DECLINE`. |
| **Online Casinos (MCC 7995)** | Normal up to $1,500.00; Review: $1,500 – $3,500; Decline: > $3,500. | Step-up required above **$1,000.00**; **Hard `DECLINE` > $2,000.00**. | Bets between $2,000 and $3,500 flip from `REVIEW` to `DECLINE`. |
| **Digital Goods (MCC 5816)** | Cross-border review threshold: **> $1,500.00**. | Cross-border review threshold lowered to **> $500.00**. | Medium-value digital purchases flip from `APPROVE` to `REVIEW`. |
| **Wire Transfers (MCC 4829)** | Review threshold: **> $3,000.00**. | Review threshold: **> $1,500.00** with mandatory VoP; Unrecognized device > $1,500 is **`DECLINE`**. | High-value ACH transfers flip from `REVIEW` to immediate `DECLINE`. |
| **Impossible Travel Speed** | `> 900 km/h` with CP required for Decline; CNP treated as `MEDIUM`. | **`> 800 km/h`** triggers unconditional **`DECLINE`** across both CP and CNP. | Stricter geographic travel velocity limits. |
| **Historical Spend Multiplier** | `> 4.0x` historical average spend. | **`> 2.5x`** historical average spend (or 2.0x for accounts < 180 days). | Rapid spend spikes flagged much earlier. |

---

## 3. Concrete Test Scenarios Demonstrating Policy Disposition Flips

The test scenarios below are mapped directly to sample records in [`docs/dataset/test_transactions_dataset.json`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/dataset/test_transactions_dataset.json). They illustrate how the exact same payload evaluated with RAG policy grounding yields opposing outcomes.

```
       +-----------------------------------------------------------+
       |             Single Incoming Test Transaction              |
       |  (e.g., $3,200 Crypto Purchase in London by bad_persona_02)|
       +-----------------------------------------------------------+
                                     |
               +---------------------+---------------------+
               |                                           |
               v                                           v
    [ Grounded in 2025 Policy ]                 [ Grounded in 2026 Policy ]
    Clause: [POL-2025-MCC-6051]                 Clause: [POL-2026-MCC-6051]
    Rule: $2,500 - $5,000 -> Step-Up            Rule: > $2,000 -> Auto Decline
               |                                           |
               v                                           v
      Composite Score: 62.0                       Composite Score: 88.0
      Disposition: REVIEW                         Disposition: DECLINE
    (Stepped up for 3DS challenge)              (Transaction immediately blocked)
```

---

### Scenario 1: Cryptocurrency Exchange Purchase (`bad_persona_02`)
* **Transaction Details**:
  - `username`: `bad_persona_02`
  - `amount`: `$3,200.00 USD`
  - `merchant`: `Instant Crypto OTC Exchange`, `mcc`: `"6051"`, `country`: `"GB"`
  - `payment_method`: `CREDIT` (Card-Not-Present), `device_id`: `dev_unrecognized_12`
  - `account_history`: 210 days old, 0 prior disputes, historical average spend $120.00.

#### Evaluation Result Under 2025 Policy (`POL-FRAUD-2025-V4`):
- **Cited Clause**: `[POL-2025-MCC-6051]` (Crypto $2,500.01 – $5,000.00 range).
- **Contributing Factors**:
  - `MERCHANT_RISK` (`HIGH`, +45.0): Quasi-cash exchange within step-up window.
  - `AMOUNT_ANOMALY` (`LOW`, +17.0): Deviation from historical baseline.
- **Composite Score**: **`62.0 / 100.0`** (within 30.0 – 69.9 range).
- **Disposition**: **`REVIEW`**
- **Reasoning Summary**:
  > *"Flagged for step-up review under [POL-2025-MCC-6051]. Cryptocurrency purchase of $3,200.00 falls between $2,500 and $5,000. Route to 3D-Secure OTP challenge."*

#### Evaluation Result Under 2026 Policy (`POL-FRAUD-2026-V1`):
- **Cited Clause**: `[POL-2026-MCC-6051]` (Crypto hard limit > $2,000.00) & `[POL-2026-PCI-01]`.
- **Contributing Factors**:
  - `MERCHANT_RISK` (`CRITICAL`, +85.0): Card-Not-Present crypto transaction exceeding the $2,000 hard ceiling.
  - `DEVICE_ANOMALY` (`HIGH`, +60.0): Unrecognized device on high-risk corridor.
- **Composite Score**: **`88.0 / 100.0`** (well above 65.0 threshold).
- **Disposition**: **`DECLINE`**
- **Reasoning Summary**:
  > *"Declined immediately under [POL-2026-MCC-6051]. Under 2026 Visa VAMP compliance rules, Card-Not-Present crypto purchases exceeding $2,000.00 are strictly prohibited. Adverse Action Code: REG_LIMIT_EXCEEDED."*

---

### Scenario 2: High-Stakes Online Casino Betting (`bad_persona_01`)
* **Transaction Details**:
  - `username`: `bad_persona_01`
  - `amount`: `$2,825.00 USD`
  - `merchant`: `Royal Flush Online Casino`, `mcc`: `"7995"`, `country`: `"JP"`
  - `payment_method`: `CREDIT` (Card-Not-Present), `device_id`: `dev_unrecognized_11`

#### Evaluation Result Under 2025 Policy (`POL-FRAUD-2025-V4`):
- **Cited Clause**: `[POL-2025-MCC-7995]` (Online gambling $1,500 – $3,500 range).
- **Composite Score**: **`65.0 / 100.0`**
- **Disposition**: **`REVIEW`** (Analyst queue).

#### Evaluation Result Under 2026 Policy (`POL-FRAUD-2026-V1`):
- **Cited Clause**: `[POL-2026-MCC-7995]` (Online gambling hard cap reduced to $2,000).
- **Composite Score**: **`92.0 / 100.0`**
- **Disposition**: **`DECLINE`** (Blocked at authorization).

---

### Scenario 3: Cross-Border E-Commerce Digital Goods
* **Transaction Details**:
  - `amount`: `$1,450.00 USD`
  - `merchant`: `Steam Global Gaming Store`, `mcc`: `"5816"`, `country`: `"GB"`
  - `payment_method`: `CREDIT` (Card-Not-Present, US cardholder)
  - `account_history`: 420 days old, 0 prior disputes, good velocity.

#### Evaluation Result Under 2025 Policy (`POL-FRAUD-2025-V4`):
- **Cited Clause**: `[POL-2025-MCC-5816]` (Cross-border threshold $1,500.00).
- **Composite Score**: **`26.5 / 100.0`** (< 30.0 baseline).
- **Disposition**: **`APPROVE`** (Straight-through frictionless payment).

#### Evaluation Result Under 2026 Policy (`POL-FRAUD-2026-V1`):
- **Cited Clause**: `[POL-2026-MCC-5816]` (Cross-border CNP step-up threshold lowered to $500.00).
- **Composite Score**: **`52.0 / 100.0`** (within 25.0 – 64.9 review range).
- **Disposition**: **`REVIEW`** (Stepped up for mandatory 3DS verification).

---

### Scenario 4: High-Value Wire Transfer (`bad_persona_03`)
* **Transaction Details**:
  - `username`: `bad_persona_03`
  - `amount`: `$3,575.00 USD`
  - `merchant`: `Global Express Wire Transfer`, `mcc`: `"4829"`, `country`: `"NG"`
  - `transaction_type`: `ACH`
  - `device_id`: `dev_unrecognized_13`, `location`: Lagos, Nigeria

#### Evaluation Result Under 2025 Policy (`POL-FRAUD-2025-V4`):
- **Cited Clause**: `[POL-2025-MCC-4829]` (Wire transfer review threshold > $3,000.00).
- **Composite Score**: **`68.0 / 100.0`**
- **Disposition**: **`REVIEW`** (Manual callback verification requested).

#### Evaluation Result Under 2026 Policy (`POL-FRAUD-2026-V1`):
- **Cited Clause**: `[POL-2026-MCC-4829]` (Transfers > $1,500 on unrecognized devices) & `[POL-2026-GEO-01]`.
- **Composite Score**: **`95.0 / 100.0`**
- **Disposition**: **`DECLINE`** (Immediate block; suspected Account Takeover & APP scam).

---

## 4. ChromaDB Ingestion & LangChain RAG Integration Guide

To ingest these policy documents into ChromaDB and enable Year-on-Year policy switching in the `Data Retrieval Agent`:

### Ingestion Metadata Schema
```json
{
  "doc_id": "pol_2025_mcc_6051",
  "policy_year": "2025",
  "category": "MCC_RULES",
  "clause_id": "POL-2025-MCC-6051",
  "effective_date": "2025-01-01"
}
```

### Retrieval Query Example with Policy Year Filter
```python
# Querying for 2025 policy context
retriever_2025 = vectorstore.as_retriever(
    search_kwargs={
        "k": 3,
        "filter": {"policy_year": "2025"}
    }
)

# Querying for 2026 policy context
retriever_2026 = vectorstore.as_retriever(
    search_kwargs={
        "k": 3,
        "filter": {"policy_year": "2026"}
    }
)
```

By toggling `filter: {"policy_year": "2025"}` to `filter: {"policy_year": "2026"}` in the scoring request or agent configuration, the `FraudScorerOrchestrator` dynamically retrieves the corresponding policy chunks, proving that policy-grounded RAG successfully dictates multi-agent scoring outcomes without code alterations.
