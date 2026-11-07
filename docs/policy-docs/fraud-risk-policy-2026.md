# Global Transaction Fraud Risk & Underwriting Policy (Calendar Year 2026)

- **Document Identifier**: `POL-FRAUD-2026-V1`
- **Effective Date**: January 1, 2026 – Active / Current
- **Issuing Body**: Enterprise Fraud Risk Committee, Compliance Directorate & Card Network Steering Group
- **Applicability**: All Card-Present (CP), Card-Not-Present (CNP), and Automated Clearing House (ACH) transactions across US and international corridors.
- **Regulatory Framework**:
  - **PCI-DSS v4.0.1** (Mandatory enforcement effective following post-March 2025 sunset of transitional requirements).
  - **Visa Acquirer Monitoring Program (VAMP)**: Unified fraud and dispute threshold enforcement (combined fraud/dispute ratio capped strictly at 0.5% / 50 bps).
  - **Mastercard 72-Hour Scam & High-Risk Merchant Rule**: Mandatory real-time containment and blocking of deceptive digital storefronts.
  - **EU Payment Services Regulation (PSR) & PSD3 Realignment**: Mandatory Verification-of-Payee (VoP) and strict PSP consumer refund liability for unauthorized and impersonation push payments.
- **Target Vector Store Metadata**: `{"policy_year": "2026", "policy_version": "2026.1", "status": "active"}`

---

## 1. Executive Policy Framework & Risk Appetite

Under the heightened regulatory mandates of 2026, enterprise risk posture has transitioned to **zero-tolerance for unverified digital and quasi-cash exposures**. Due to the aggressive enforcement of Visa's VAMP and Mastercard's scam-merchant surveillance directives, operational thresholds for Card-Not-Present (CNP) purchases, foreign currency conversions, cryptocurrency on-ramps, and high-velocity bursts have been systematically compressed.

### Global Decision Taxonomy & Tightened Risk Boundaries (2026 Mandate)
Every transaction evaluated by the Transaction Risk Score System receives a composite score between **0.0** and **100.0**:

| Composite Risk Score | Disposition Decision | Operational Handling |
|---|---|---|
| **0.0 – 24.9** | `APPROVE` | Frictionless straight-through authorization (Tightened from 29.9). |
| **25.0 – 64.9** | `REVIEW` | Mandatory Step-Up: Biometric 3DS 2.3 or real-time cryptographic passkey challenge. If unfulfilled, auto-declined within 15 minutes. |
| **65.0 – 100.0** | `DECLINE` | Immediate automated block (Tightened from 70.0). High-risk event logged to fraud SIEM. |

---

## 2. Specific Policy Clauses & Tightened Evaluation Rules

### Section A: Velocity & High-Frequency Swipes

#### `[POL-2026-VEL-01]` 60-Minute Velocity Burst Threshold (Compressed)
- **Scope**: Single account ID or card last four across all merchant categories.
- **Rule**:
  - **Standard Merchants**: If an account incurs **more than 2 completed or attempted transactions within a 60-minute window**, trigger a `VELOCITY` risk factor (+30.0).
  - **High-Risk MCCs (6051, 7995, 4829, 5816)**: **2 or more transactions in 60 minutes** triggers an immediate `HIGH` severity risk factor (+55.0) and forces disposition to at least **`REVIEW`**.
  - **3 or more transactions in 60 minutes** in any category: Trigger `CRITICAL` severity (+75.0); disposition set to **`DECLINE`**.

#### `[POL-2026-VEL-02]` 24-Hour Cumulative Spend Velocity
- **Scope**: Total aggregate transaction volume across all channels in 24 hours.
- **Rule**: Aggregate 24-hour spend exceeding **$5,000.00 USD** (lowered from $10,000.00 USD) triggers an automatic `VELOCITY_VOLUME` risk factor (+45.0) and requires step-up authentication.

---

### Section B: Merchant Category Code (MCC) Scrutiny & Hard Limits

#### `[POL-2026-MCC-6051]` Cryptocurrency, Virtual Assets & Quasi-Cash Exchanges
- **Regulatory Background**: Visa VAMP high-risk tiering and anti-money laundering (AML) Travel Rule enforcement.
- **Policy Directives**:
  - Transactions **<= $1,000.00 USD** (compressed from $2,500.00): Approved only with verified 3DS 2.3 authentication.
  - Transactions **$1,000.01 – $2,000.00 USD**: Assigned `HIGH` severity risk factor (+60.0); mandatory disposition **`REVIEW`** with device binding check.
  - Transactions **> $2,000.00 USD**: Assigned `CRITICAL` severity (+85.0); **AUTOMATIC `DECLINE`**. Unconditional block for all Card-Not-Present crypto purchases over $2,000.00.

#### `[POL-2026-MCC-7995]` Online Gambling, Casinos & Betting
- **Regulatory Background**: Card scheme chargeback mitigation and consumer vulnerability protections.
- **Policy Directives**:
  - Transactions **<= $1,000.00 USD** (compressed from $1,500.00): Permitted with standard scoring.
  - Transactions **$1,000.01 – $2,000.00 USD**: Assigned `HIGH` severity (+55.0); routed to **`REVIEW`**.
  - Transactions **> $2,000.00 USD** (compressed from $3,500.00): Assigned `CRITICAL` severity (+85.0); **AUTOMATIC `DECLINE`**.

#### `[POL-2026-MCC-5816]` Digital Goods, In-Game Assets & Software Downloads
- **Regulatory Background**: Surge in automated bot credential-stuffing and synthetic card testing rings.
- **Policy Directives**:
  - Domestic transactions **<= $500.00 USD**: Approved with baseline scoring.
  - Cross-border Card-Not-Present transactions **> $500.00 USD** (compressed from $1,500.00): Assigned `HIGH` severity (+50.0); mandatory routing to **`REVIEW`** for 3DS verification.
  - Micro-transactions (< $5.00): Any occurrence of 2 or more micro-transactions within 15 minutes triggers an immediate account velocity freeze.

#### `[POL-2026-MCC-4829]` Wire Transfers, Money Orders & Instant ACH
- **Regulatory Background**: EU PSR/PSD3 mandatory Verification-of-Payee (VoP) and Authorized Push Payment (APP) fraud rules.
- **Policy Directives**:
  - Outbound transfers **<= $1,500.00 USD** (compressed from $3,000.00): Permitted only with matched payee name and account registration tenure > 60 days.
  - Outbound transfers **> $1,500.00 USD**: Assigned `CRITICAL` severity (+80.0); mandatory **`DECLINE`** if originated from an unrecognized device or IP address; otherwise routed to **`REVIEW`** with out-of-band biometric approval.

#### `[POL-2026-MCC-5411]` Grocery Stores & Essential Retail
- **Policy Directives**:
  - In-store Card-Present purchases remain low risk (+5.0).
  - Online delivery orders (CNP) > $350.00 USD trigger `MEDIUM` severity (+25.0) if delivery address differs from historical profile zip code.

---

### Section C: Geolocation, Corridor & Impossible Travel

#### `[POL-2026-GEO-01]` Haversine Impossible Travel Speed & IP Origin Discrepancies
- **Rule**: Minimum required speed between consecutive transactions: `Speed (km/h) = Distance (km) / Time_Delta (hours)`.
- **Thresholds**:
  - Speed **> 800 km/h** (tightened from 900 km/h): Assigned `CRITICAL` severity (+90.0); immediate **`DECLINE`**, irrespective of whether the transaction is Card-Present or Card-Not-Present.
  - **IP Geolocation Mismatch**: If transaction IP country does not match the cardholder profile country AND does not match the merchant country, assign `HIGH` severity (+45.0) and force disposition to at least **`REVIEW`**.

#### `[POL-2026-GEO-02]` International Cross-Border Step-Up Thresholds
- **Thresholds**:
  - Cross-border transactions **<= $1,000.00 USD** (compressed from $2,000.00): Assigned `LOW` severity (+15.0).
  - Cross-border transactions **> $1,000.00 USD**: Assigned `HIGH` severity (+45.0); mandatory disposition **`REVIEW`**.

---

### Section D: Amount & Baseline Multipliers

#### `[POL-2026-AMT-01]` Historical Spend Multiplier & Early-Life Accounts
- **Baseline Metric**: `avg_transaction_amount` retrieved from SQLite account history.
- **Rule**:
  - For established accounts (> 180 days): Amount **> 2.5x `avg_transaction_amount`** (lowered from 4.0x) triggers `HIGH` severity (+40.0) if amount exceeds $300.00 USD.
  - For early-life accounts (<= 180 days): Any single transaction **> 2.0x `avg_transaction_amount`** triggers an automatic **`REVIEW`** disposition.

---

### Section E: PCI-DSS v4.0.1 Script Integrity & Device Binding

#### `[POL-2026-PCI-01]` Unrecognized Device & Anonymous Proxy / VPN Detection
- **Regulatory Requirement**: PCI-DSS v4.0.1 continuous client-side script integrity and session validation.
- **Rule**:
  - Any transaction originating from an unrecognized device (`device_id` unindexed in user history) operating behind a hosting provider/VPN/Tor exit node IP address receives a mandatory risk contribution of **+60.0 (`HIGH`)** and cannot be assigned `APPROVE`.

---

## 3. Mandatory Explainability & Adverse Action Guidelines

Under 2026 regulatory underwriting standards (FCRA, ECOA, EU PSD3):
- The `reasoning_summary` MUST explicitly quote the governing policy clause ID (e.g., `[POL-2026-MCC-6051]`) and explain the specific threshold breach that produced the disposition.
- If a transaction was declined due to regulatory hard caps (such as Crypto > $2,000), the response payload must state the adverse action reason code `REG_LIMIT_EXCEEDED` to satisfy customer dispute disclosure mandates.
