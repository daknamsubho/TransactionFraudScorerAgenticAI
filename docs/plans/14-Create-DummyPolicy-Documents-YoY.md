# Implementation Plan: Create Dummy Policy Documents Year on Year (PRD-014)

## Goal Description
Create realistic, structured, Year-on-Year (2025 vs. 2026) transaction fraud risk policy documents under `docs/policy-docs/` per [docs/prds/14-Create-DummyPolicy-Documents-YoY.md](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/prds/14-Create-DummyPolicy-Documents-YoY.md).

These policy documents will be indexed into the **ChromaDB Vector Store** (via LangChain RAG as specified in [`docs/rag-design.md`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/rag-design.md)) to demonstrate how evaluating the **exact same transaction** against the 2025 policy versus the 2026 policy produces meaningfully different risk assessments and dispositions (e.g. `APPROVE` -> `REVIEW`, or `REVIEW` -> `DECLINE`).

Per PRD-014, changes to web client, notebooks, or application code are **out-of-scope**.

---

## User Review Required

> [!IMPORTANT]
> **Proposed Year-on-Year Policy Divergence Strategy**:
> To ensure the RAG retrieval produces distinct, testable outcomes for identical transactions, the 2025 and 2026 policies reflect real-world regulatory shifts (PCI-DSS 4.0.1 mandatory enforcement, Visa VAMP consolidation, Mastercard 72-hour scam rules, and PSD3/PSR liability mandates):
>
> 1. **High-Risk MCCs (Crypto MCC 6051 & Online Casino MCC 7995)**:
>    - *2025 Policy*: Moderate tolerance. Transactions under $2,500.00 permitted with standard 3DS step-up (`REVIEW`).
>    - *2026 Policy*: Aggressive restriction. Hard cap lowered to $1,000.00 for `REVIEW`; transactions > $2,000.00 without physical card-present or verified biometrics are an immediate **`DECLINE`**.
>
> 2. **Cross-Border Digital Goods (MCC 5816 / 5815)**:
>    - *2025 Policy*: Step-up authentication triggered only above $1,500.00.
>    - *2026 Policy*: Step-up authentication mandate lowered to **$500.00** for all cross-border Card-Not-Present transactions.
>
> 3. **Velocity Bursts**:
>    - *2025 Policy*: Threshold of **3 transactions in 60 minutes** before triggering `HIGH` velocity alert.
>    - *2026 Policy*: Threshold lowered to **2 transactions in 60 minutes** for high-risk MCCs or international corridors.
>
> 4. **ACH / Wire Transfers (MCC 4829 / ACH)**:
>    - *2025 Policy*: Review triggered above $3,000.00.
>    - *2026 Policy*: Review triggered above $1,500.00 with mandatory Verification-of-Payee (VoP).

---

## Open Questions

> [!NOTE]
> 1. **Document Naming Convention**:
>    We propose:
>    - `docs/policy-docs/fraud-risk-policy-2025.md`
>    - `docs/policy-docs/fraud-risk-policy-2026.md`
>    - `docs/policy-docs/policy-comparison-guide.md` (A developer guide highlighting test scenarios from `test_transactions_dataset.json` and showing expected score/disposition deltas).
> 2. **Clause Tagging Format**:
>    Should each clause follow a structured anchor ID format (e.g. `[POL-2025-MCC-6051]`, `[POL-2026-VEL-01]`) so that the agent's RAG retriever can explicitly quote the clause ID in its `reasoning_summary`? (Recommended: Yes, this maximizes explainability).

---

## Proposed Changes

### Documentation & Policy Layer (`docs/policy-docs/`)

#### [NEW] [`docs/policy-docs/fraud-risk-policy-2025.md`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/policy-docs/fraud-risk-policy-2025.md)
Comprehensive, enterprise-grade policy specification for Calendar Year 2025 containing:
- **Policy Metadata**: Effective Date: January 1, 2025; Version 2025.4; Authority: Enterprise Fraud & Underwriting Committee.
- **Global Scoring Taxonomy**:
  - `0.0 - 29.9`: `APPROVE`
  - `30.0 - 69.9`: `REVIEW`
  - `70.0 - 100.0`: `DECLINE`
- **Section 1: Velocity Thresholds & Rapid Swipe Playbook**:
  - `[POL-2025-VEL-01]`: 3 transactions / 60 minutes baseline cutoff.
- **Section 2: Merchant Category Code (MCC) Scrutiny**:
  - `[POL-2025-MCC-6051]` (Crypto): Limit $2,500 for step-up review; decline > $5,000.
  - `[POL-2025-MCC-7995]` (Betting): Limit $1,500 for step-up review; decline > $3,500.
  - `[POL-2025-MCC-5816]` (Digital Goods): Step-up required > $1,500.
  - `[POL-2025-MCC-4829]` (Wire Transfers): Review required > $3,000.
- **Section 3: Geolocation, Corridor & Impossible Travel**:
  - `[POL-2025-GEO-01]`: Impossible travel speed cutoff at 900 km/h.
  - `[POL-2025-GEO-02]`: Standard cross-border review threshold ($2,000).
- **Section 4: Amount & Account History Multipliers**:
  - `[POL-2025-AMT-01]`: Spend deviation threshold at 4x historical average spend.

---

#### [NEW] [`docs/policy-docs/fraud-risk-policy-2026.md`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/policy-docs/fraud-risk-policy-2026.md)
Updated enterprise-grade policy specification for Calendar Year 2026 reflecting regulatory mandates:
- **Policy Metadata**: Effective Date: January 1, 2026; Version 2026.1; Compliance Mandates: PCI-DSS 4.0.1 Mandatory Enforcement, Visa VAMP Consolidation, Mastercard 72-Hour Scam Rules, EU PSR/PSD3 Alignment.
- **Global Scoring Taxonomy (Tightened Boundaries)**:
  - `0.0 - 24.9`: `APPROVE` (Tightened from 29.9)
  - `25.0 - 64.9`: `REVIEW`
  - `65.0 - 100.0`: `DECLINE` (Tightened from 70.0)
- **Section 1: Velocity Thresholds & Rapid Swipe Playbook**:
  - `[POL-2026-VEL-01]`: Burst limit reduced to 2 transactions / 60 minutes for high-risk MCCs and international corridors.
- **Section 2: Merchant Category Code (MCC) Scrutiny (Aggressive Reductions)**:
  - `[POL-2026-MCC-6051]` (Crypto): Hard cap lowered to $1,000 for step-up; automatic **`DECLINE`** for any transaction > $2,000 without verified biometric 3DS.
  - `[POL-2026-MCC-7995]` (Betting): Hard cap lowered to $1,000 for step-up; automatic **`DECLINE`** for transactions > $2,000.
  - `[POL-2026-MCC-5816]` (Digital Goods): Step-up mandatory for any CNP transaction > **$500.00**.
  - `[POL-2026-MCC-4829]` (Wire Transfers): Verification of Payee (VoP) mandatory; review triggered at **$1,500.00**.
- **Section 3: Geolocation, Corridor & Impossible Travel**:
  - `[POL-2026-GEO-01]`: Haversine speed cutoff lowered to 800 km/h; mandatory decline if origin IP country does not match card issuance corridor unless pre-notified travel flag exists.
- **Section 4: Amount & Account History Multipliers**:
  - `[POL-2026-AMT-01]`: Spend deviation threshold lowered to 2.5x historical average spend for accounts < 180 days old.

---

#### [NEW] [`docs/policy-docs/policy-comparison-guide.md`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/policy-docs/policy-comparison-guide.md)
Companion reference manual detailing:
- Side-by-side YoY threshold comparison table.
- 4 concrete transaction test scenarios (mapped to personas in `test_transactions_dataset.json`):
  1. *Scenario 1 (Crypto Purchase - `bad_persona_02`, $3,200 London MCC 6051)*: 2025 -> `REVIEW` (Score: 62) vs 2026 -> `DECLINE` (Score: 88).
  2. *Scenario 2 (Casino Purchase - `bad_persona_01`, $2,825 Tokyo MCC 7995)*: 2025 -> `REVIEW` (Score: 65) vs 2026 -> `DECLINE` (Score: 92).
  3. *Scenario 3 (Cross-Border Digital Goods, $1,450 UK MCC 5816)*: 2025 -> `APPROVE` (Score: 28) vs 2026 -> `REVIEW` (Score: 68).
  4. *Scenario 4 (ACH Wire Transfer - `bad_persona_03`, $3,575 Lagos MCC 4829)*: 2025 -> `REVIEW` (Score: 68) vs 2026 -> `DECLINE` (Score: 95).
- Guidance on how to ingest these files into ChromaDB with metadata filters `{"policy_year": "2025"}` and `{"policy_year": "2026"}`.

---

### Project Plans (`docs/plans/`)

#### [NEW] [`docs/plans/14-Create-DummyPolicy-Documents-YoY.md`](file:///Users/abhishekbiswas/AppDevelppment/TransactionFraudScorerAgenticAI/docs/plans/14-Create-DummyPolicy-Documents-YoY.md)
Save this plan to `docs/plans/` in accordance with user rules.

---

## Verification Plan

### Automated Verification
- Verify that markdown files are created with valid formatting and no broken links:
  ```bash
  python3 -c "
  import glob, re
  files = ['docs/policy-docs/fraud-risk-policy-2025.md', 'docs/policy-docs/fraud-risk-policy-2026.md', 'docs/policy-docs/policy-comparison-guide.md']
  for fpath in files:
      with open(fpath, 'r') as f:
          content = f.read()
          assert len(content) > 1000, f'{fpath} is too short'
          assert 'POL-' in content or 'policy' in content.lower(), f'{fpath} missing policy tags'
  print('All policy documents verified successfully!')
  "
  ```

### Manual Verification
- Review the generated documents against PRD-014 requirements:
  1. 2 distinct policy documents for Year 2025 and 2026.
  2. Clear YoY deltas in thresholds and clauses.
  3. Stored in `docs/policy-docs`.
  4. Verified alignment with transaction model (`src/fraud_scorer/models/transaction.py`) and RDBMS schema (`docs/rdbms-model-schema/schema.sql`).
