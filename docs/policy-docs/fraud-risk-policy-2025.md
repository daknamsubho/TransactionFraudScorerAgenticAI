# Global Transaction Fraud Risk & Underwriting Policy (Calendar Year 2025)

- **Document Identifier**: `POL-FRAUD-2025-V4`
- **Effective Date**: January 1, 2025 – December 31, 2025
- **Issuing Body**: Enterprise Fraud Risk Committee & Credit Policy Group
- **Applicability**: All Card-Present (CP), Card-Not-Present (CNP), and Automated Clearing House (ACH) transactions across US and international corridors.
- **Regulatory Framework**: PCI-DSS v4.0 (pre-transition), Visa Core Rules & Product Service Rules (VFMP/VDMP legacy dual-monitoring), Mastercard Security Rules, NACHA ACH Operating Rules.
- **Target Vector Store Metadata**: `{"policy_year": "2025", "policy_version": "2025.4", "status": "superseded"}`

---

## 1. Executive Policy Framework & Risk Appetite

This policy defines the quantitative and qualitative criteria governing transaction fraud risk scoring for the calendar year 2025. The objective is to balance merchant conversion and low user friction while maintaining an overall fraud-to-sales ratio below 0.08% (8 bps).

### Global Decision Taxonomy & Risk Score Boundaries (2025 Baseline)
Every evaluated transaction receives a normalized risk score between **0.0** and **100.0**:

| Composite Risk Score | Disposition Decision | Operational Handling |
|---|---|---|
| **0.0 – 29.9** | `APPROVE` | Frictionless straight-through authorization. |
| **30.0 – 69.9** | `REVIEW` | Stepped up for dynamic authentication (3D-Secure 2.1) or routed to manual fraud analyst review queue within 4 hours. |
| **70.0 – 100.0** | `DECLINE` | Automated authorization block. Immediate issuer/processor decline response. |

---

## 2. Specific Policy Clauses & Evaluation Rules

### Section A: Velocity & High-Frequency Swipes

#### `[POL-2025-VEL-01]` 60-Minute Velocity Burst Threshold
- **Scope**: Single account ID or card last four identifier across all merchant categories.
- **Rule**: If an account incurs **more than 3 completed or attempted transactions within a 60-minute rolling window**, the transaction shall trigger a `VELOCITY` risk factor.
  - 4 transactions in 60 minutes: Severity `MEDIUM` (Risk contribution score: +25.0).
  - 5 or more transactions in 60 minutes: Severity `HIGH` (Risk contribution score: +50.0).
- **Disposition Mandate**: Any transaction with velocity count >= 5 MUST be assigned a disposition of at least `REVIEW`.

#### `[POL-2025-VEL-02]` 24-Hour Cumulative Spend Velocity
- **Scope**: Total aggregate transaction volume across all channels in 24 hours.
- **Rule**: Aggregate 24-hour spend exceeding **$10,000.00 USD** on consumer debit/credit accounts (or $50,000.00 USD on commercial accounts) triggers a `VELOCITY_VOLUME` risk factor (+35.0).

---

### Section B: Merchant Category Code (MCC) Scrutiny & Thresholds

#### `[POL-2025-MCC-6051]` Quasi-Cash, Cryptocurrency & Foreign Currency Exchanges
- **Baseline Risk Profile**: Elevated high-risk category.
- **Policy Directives**:
  - Transactions **<= $2,500.00 USD**: Approved without manual intervention if account age > 90 days and CVV/AVS matches.
  - Transactions **$2,500.01 – $5,000.00 USD**: Assigned `HIGH` severity risk factor (+45.0) and routed to **`REVIEW`** for step-up OTP / 3DS challenge.
  - Transactions **> $5,000.00 USD**: Assigned `CRITICAL` severity (+75.0) and routed to **`DECLINE`** unless pre-authorized by an established VIP customer (> 1 year tenure).

#### `[POL-2025-MCC-7995]` Online Casinos, Sports Betting & Wagering
- **Baseline Risk Profile**: Elevated high-risk category.
- **Policy Directives**:
  - Transactions **<= $1,500.00 USD**: Permitted with normal scoring.
  - Transactions **$1,500.01 – $3,500.00 USD**: Assigned `HIGH` severity (+40.0); disposition set to **`REVIEW`**.
  - Transactions **> $3,500.00 USD**: Assigned `CRITICAL` severity (+70.0); automatic **`DECLINE`**.

#### `[POL-2025-MCC-5816]` Digital Goods, In-Game Content & Software
- **Baseline Risk Profile**: Moderate risk; high card-not-present chargeback potential.
- **Policy Directives**:
  - Domestic transactions **<= $1,500.00 USD**: Straight-through processing (`APPROVE`).
  - Cross-border transactions **> $1,500.00 USD**: Assigned `MEDIUM` severity (+30.0); routed to **`REVIEW`** for 3DS verification.
  - Micro-transactions (< $5.00) testing patterns: If more than 3 micro-transactions occur in 10 minutes, escalate to **`REVIEW`**.

#### `[POL-2025-MCC-4829]` Wire Transfer & Money Orders (ACH / Card)
- **Baseline Risk Profile**: Immediate irrevocable funds transfer risk.
- **Policy Directives**:
  - Outbound transfers **<= $3,000.00 USD**: Permitted with standard account baseline checks.
  - Outbound transfers **> $3,000.00 USD**: Assigned `HIGH` severity (+50.0); disposition set to **`REVIEW`** with mandatory callback verification.

#### `[POL-2025-MCC-5411]` Grocery Stores & Supermarkets
- **Baseline Risk Profile**: Low risk; routine consumer spend.
- **Policy Directives**:
  - Card-Present transactions up to $500.00 USD: Maximum risk contribution score capped at +10.0 (`LOW`), regardless of minor geolocation distance shifts within state boundaries.

---

### Section C: Geolocation, Corridor & Impossible Travel

#### `[POL-2025-GEO-01]` Haversine Impossible Travel Speed
- **Rule**: Calculate minimum required speed between consecutive transactions: `Speed (km/h) = Distance (km) / Time_Delta (hours)`.
- **Thresholds**:
  - Speed **> 900 km/h** (commercial aviation ceiling) with `is_card_present = True` on both transactions: Assigned `CRITICAL` severity (+85.0); automatic **`DECLINE`** due to physical clone card fraud.
  - Speed **> 900 km/h** with one transaction Card-Not-Present (`is_card_present = False`): Assigned `MEDIUM` severity (+25.0) as remote e-commerce spend while traveling is permissible.

#### `[POL-2025-GEO-02]` Cross-Border International Corridors
- **Rule**: Cardholder domestic country differing from merchant registered country.
- **Thresholds**:
  - Cross-border transactions **<= $2,000.00 USD**: Standard scoring with minor cross-border penalty (+15.0).
  - Cross-border transactions **> $2,000.00 USD**: Assigned `MEDIUM` severity (+30.0); routed to **`REVIEW`** if customer has no international spend history in preceding 180 days.

---

### Section D: Amount & Historical Baseline Deviations

#### `[POL-2025-AMT-01]` Historical Spend Multiplier
- **Baseline Metric**: `avg_transaction_amount` retrieved from account history.
- **Rule**:
  - Current amount **> 4.0x `avg_transaction_amount`**: Assigned `HIGH` severity (+40.0) if amount also exceeds $500.00 USD.
  - Accounts with fewer than 5 historical transactions: Multiplier waived; static tiering applied instead.

---

### Section E: Device & Identity Consistency

#### `[POL-2025-DEV-01]` Unrecognized Device & IP Anomalies
- **Rule**: Unrecognized `device_id` combined with foreign IP country:
  - If transaction amount < $1,000.00: Assigned `LOW` severity (+15.0).
  - If transaction amount >= $1,000.00: Assigned `MEDIUM` severity (+30.0); requires 3DS step-up.

---

## 3. Mandatory Explainability & Adverse Action Guidelines

Under 2025 regulatory underwriting standards:
- Any transaction resulting in `DECLINE` or `REVIEW` must cite the contributing factor categories in descending order of contribution score.
- Citing merchant name, MCC, and exact numerical threshold in the `reasoning_summary` is mandatory for internal compliance auditing.
