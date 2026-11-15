# Capstone Agent Guardrails & Risk Controls Report: Transaction Fraud Scorer

- **Document Identifier**: `DOC-GUARD-RISK-2026-V1`
- **Date**: November 15, 2026
- **System**: Transaction Fraud Scorer Multi-Agent System (`src/fraud_scorer/`, `src/api_gateway/`, `src/chromadb/`, `src/sqllite/`)
- **Author**: Lead AI Safety & Systems Architect
- **Target Audience**: Risk Committees, Engineering Leadership, Compliance Officers, and AI Evaluators

---

## 1. System Purpose & Operational Risk Landscape

### A. What the Capstone Agent is Designed to Do
The **Transaction Fraud Scorer Agentic AI** is an enterprise-grade, multi-agent financial risk evaluation system. Operating synchronously at payment checkout and asynchronously in post-transaction surveillance, it ingests Card-Present (CP), Card-Not-Present (CNP), and Automated Clearing House (ACH) transactions. 

The system coordinates a team of specialized agents:
* **Data Retriever Agent** (`src/fraud_scorer/agents/data_retriever_agent.py`): Extracts customer baselines from relational storage (SQLite) and retrieves regulatory policy clauses from ChromaDB vector collections.
* **Analysis Agent** (`src/fraud_scorer/agents/analysis_agent.py`): Executes concurrent analytical skills to detect transaction velocity spikes, Haversine geographic hops (impossible travel), high-risk Merchant Category Codes (MCC), and anomalous spending amounts.
* **Decision Agent (Actor)** (`src/fraud_scorer/agents/decision_agent.py`): Synthesizes quantitative risk signals and regulatory policy clauses to propose a normalized risk score ($0.0 – 100.0$), disposition (`APPROVE`, `REVIEW`, `DECLINE`), and natural-language justification.
* **Evaluator Agent (Critic)** (`src/fraud_scorer/agents/evaluator_agent.py`): Audits the draft assessment using deterministic rubrics and adversarial scrutiny before authorizing release.
* **Orchestrator Agent (Supervisor)** (`src/fraud_scorer/agents/orchestrator_agent.py`): Coordinates the state machine using a compiled LangGraph workflow (`src/fraud_scorer/agents/workflow.py`).

---

### B. Safety, Security & Reliability Risks in the Workflow

Deploying autonomous generative agents into financial transaction flows creates severe failure modes if unconstrained:

```
+---------------------------------------------------------------------------------------------------+
|                                   OPERATIONAL RISK LANDSCAPE                                      |
+------------------------------------+--------------------------------------------------------------+
| Risk Vector                        | Failure Manifestation & Impact                               |
+------------------------------------+--------------------------------------------------------------+
| 1. Financial Loss / False Negatives| Agent fails to identify synthetic fraud rings or velocity   |
|                                    | bursts, approving fraudulent charges that result in charge-   |
|                                    | backs and payment network fines (e.g. Visa VAMP penalties).  |
+------------------------------------+--------------------------------------------------------------+
| 2. Customer Insult / False Positives| Agent hallucinate risks on legitimate transactions, causing |
|                                    | checkout abandonment, merchant friction, and lost revenue.   |
+------------------------------------+--------------------------------------------------------------+
| 3. Confirmation Bias & Self-Defense| A monolithic scoring agent defends its initial flawed draft  |
|                                    | rather than critically correcting mathematical errors.       |
+------------------------------------+--------------------------------------------------------------+
| 4. Latency SLA Explosion           | Multi-agent dialogue loops exceed payment gateway budgets    |
|                                    | (p95 > 2,000 ms), causing HTTP 504 timeouts at POS terminals.|
+------------------------------------+--------------------------------------------------------------+
| 5. Sensitive Data Leakage (PCI-DSS)| Unmasked 16-digit Primary Account Numbers (PANs), CVVs, or   |
|                                    | PII enter LLM prompt contexts, telemetry traces, or logs.    |
+------------------------------------+--------------------------------------------------------------+
| 6. Epistemic Blindness             | Agent guesses decisions on cold-start profiles (< 14 days old)|
|                                    | or when analytical tools return contradictory signals.       |
+------------------------------------+--------------------------------------------------------------+
| 7. Offline Infrastructure Paralysis| When Ollama or cloud LLMs are offline, the system either:    |
|                                    | (a) fails open (approves fraud), or                         |
|                                    | (b) routes 100% of traffic to manual review, choking queues.  |
+------------------------------------+--------------------------------------------------------------+
| 8. Adverse Action Non-Compliance   | Declining transactions without grounded policy citations     |
|                                    | violates fair lending (ECOA / FCRA) adverse action mandates. |
+------------------------------------+--------------------------------------------------------------+
```

---

## 2. Multi-Tier Guardrail Architecture

To constrain agent behavior and mitigate these risks, the system establishes a **defense-in-depth guardrail framework** spanning ingress, runtime execution, and egress:

```
[ Ingress Boundary ] ────> [ Data & Tool Limits ] ────> [ Runtime State Constraints ] ────> [ Egress Scrubbing ]
  • Pydantic Schema          • Read-Only Queries          • Actor-Critic Audit               • PCI-DSS Masking
  • Lat/Lon Coordinates      • Sub-Delegation Capped at 1 • Math Consistency (+-5)           • PII Anonymization
  • Value-Based Offline Gate • Hardcoded Tool Contracts   • Impossible Travel Floor (>=75)   • Adverse Action Check
```

### A. Input Checks & Ingress Schema Validation
* **Pydantic v2 Ingress Validation** ([transaction.py](../src/fraud_scorer/models/transaction.py#L43-L87)):
  * `amount`: Strictly enforced as positive float ($> 0.0$).
  * `currency`: Validated against 3-letter ISO-4217 standard codes.
  * `location.latitude` & `longitude`: Strictly bounded to valid geographic ranges ($-90.0 \le \text{lat} \le 90.0$, $-180.0 \le \text{lon} \le 180.0$).
  * `merchant.mcc`: Validated as exact 4-digit Merchant Category Code strings.
  * `payment_method.card_last_four`: Enforced as exactly 4 numerical digits.

### B. Data Privacy & PCI-DSS Scrubbing
* **Zero-Leakage Telemetry Sanitizer** ([sanitizer.py](../src/fraud_scorer/observability/sanitizer.py)):
  * **Cardholder Numbers**: Regex pattern matching 13-to-19 digit PANs tokenizes values to `****-****-****-1234`.
  * **Authentication Data**: Keys matching `cvv`, `cvc`, `pin`, `password`, `ssn`, `iban`, `api_key`, `secret` are overwritten with `***REDACTED***`.
  * **Customer PII**: Name, street address, email, and phone numbers are scrubbed to `***REDACTED_PII***`.
  * **Network Identifiers**: IPv4/IPv6 addresses mask final octets (e.g., `192.168.1.***`).
* **Telemetry Egress Filter** ([tracer.py](../src/fraud_scorer/observability/tracer.py#L111-L144)): LangSmith and OpenTelemetry trace interceptors wrap all inputs with `process_inputs=sanitize_transaction_payload` before emitting spans.

### C. Output Constraints & Hard Decision Taxonomy
* **Immutable Decision Taxonomy**:
  * $0.0 – 29.9 \rightarrow$ `APPROVE`
  * $30.0 – 69.9 \rightarrow$ `REVIEW`
  * $70.0 – 100.0 \rightarrow$ `DECLINE`
* **Deterministic Safety Floors**:
  * **Impossible Travel Floor**: Any transaction triggering a `CRITICAL GEO_ANOMALY` (speed $> 800\text{ km/h}$) automatically forces the composite score to $\ge 75.0$ and blocks `APPROVE` ([risk_scoring_decision_skill.py](../src/fraud_scorer/skills/risk_scoring_decision_skill.py#L33-L39)).
  * **High-Exposure Dollar Ceiling**: Any transaction $> \$5,000.00$ or 24h volume $> \$5,000.00$ automatically revokes autonomous approval authority, forcing disposition $\ge$ `REVIEW`.

### D. Source Verification & Policy Grounding
* **ChromaDB Policy Retrieval**: Retrieval-Augmented Generation embeds current rulebooks ([fraud-risk-policy-2026.md](policy-docs/fraud-risk-policy-2026.md)).
* **Mandatory Policy Citations**: The Decision Agent must ground its justification in specific clause identifiers (e.g., `[POL-2026-VEL-01]`, `[POL-2026-MCC-6051]`). Ungrounded assertions are formally rejected by the Evaluator Critic.

### E. Tool Access Limits & Least Privilege Ring-Fencing
* **Read-Only Separation of Concerns**: Scoring agents possess read-only database and tool permissions (`SELECT` on SQLite, similarity queries on ChromaDB). No agent has write authority to freeze accounts, move money, or alter balances.
* **Bounded Sub-Delegation**: Supplementary queries from Analysis to Data Retrieval are hard-capped at **1 round-trip** per transaction ([workflow.py](../src/fraud_scorer/agents/workflow.py#L637-L646)), preventing recursive execution cascades.

### F. Runtime SLA Circuit Breakers & Fallback Logic
* **Retry Counter**: The Actor-Critic feedback loop is capped at `max_evaluation_retries = 3`.
* **Execution Timeout Budget**: Wall-clock execution is monitored against `max_timeout_ms = 1800.0`. If exceeded, the loop trips into `circuit_breaker_fallback_node`, failing safe to `REVIEW` for human dispatch ([workflow.py](../src/fraud_scorer/agents/workflow.py#L564-L635)).

---

## 3. Comprehensive Evaluation & Reliability Metrics

To assess whether the agent fleet performs accurately, safely, and within budget, the system tracks a balanced scorecard of quantitative metrics:

```
                                  AGENT PERFORMANCE SCORECARD
┌────────────────────────────────┬────────────────────────────────┬────────────────────────────────┐
│ 1. Decision Correctness        │ 2. Groundedness & Calibration   │ 3. Safety & Policy Adherence   │
├────────────────────────────────┼────────────────────────────────┼────────────────────────────────┤
│ • ROC-AUC & PR-AUC             │ • Arithmetic Deviation (<=5.0) │ • Critical Geo Violations (0%) │
│ • False Positive Rate (FPR)    │ • Policy Citation Precision    │ • Blast Radius Violations (0%) │
│ • False Negative Rate (FNR)    │ • RAG Faithfulness Score       │ • PII Leakage Incidents (0)    │
└────────────────────────────────┴────────────────────────────────┴────────────────────────────────┘
┌────────────────────────────────┬────────────────────────────────┬────────────────────────────────┐
│ 4. Operational Latency & SLA   │ 5. Fleet Governance & Fallback │ 6. Human Review Effectiveness  │
├────────────────────────────────┼────────────────────────────────┼────────────────────────────────┤
│ • p50, p95, p99 Latency (ms)   │ • Offline Fast-Path Ratio      │ • Human Override Rate          │
│ • SLA Breach Rate (< 1800ms)   │ • Circuit Breaker Trip Rate    │ • Analyst Decision Turnaround  │
│ • Tool Execution Overhead      │ • Macro Fleet Surge Rate       │ • Model-Analyst Agreement F1   │
└────────────────────────────────┴────────────────────────────────┴────────────────────────────────┘
```

### Detailed Metric Definitions

1. **Mathematical Calibration ($\Delta_{\text{math}}$)**:
   $$\Delta_{\text{math}} = \left| \text{overall\_risk\_score} - \min\left(100.0, \sum \text{factor\_contribution\_scores}\right) \right|$$
   *Target*: $\Delta_{\text{math}} \le 5.0$ on $100\%$ of approved transactions.
2. **Policy Grounding Precision**:
   $$\text{Precision}_{\text{grounding}} = \frac{\text{Valid Codified Clause Citations in Summary}}{\text{Total Citations in Summary}}$$
   *Target*: $\ge 98\%$. Zero hallucinated policy clause IDs allowed.
3. **Safety Compliance Rate**:
   *Target*: Exactly $100\%$. Zero occurrences where `impossible_travel == true` or `amount > $5000` receives an autonomous `APPROVE`.
4. **Latency Budget Adherence (p95)**:
   *Target*: p95 latency $\le 1,400\text{ ms}$; hard cap p99.9 $\le 1,800\text{ ms}$ in online mode; $\le 20\text{ ms}$ in offline fast-path mode.
5. **Human Escalation Rate**:
   *Target*: $5\% – 8\%$ of total transaction traffic routed to `REVIEW`. Higher indicates excessive uncertainty; lower indicates potential reckless automation.
6. **Macro Outlier Drift Alert**:
   Tracks the ratio of autonomous declines in a rolling 10-minute window against the 24-hour moving average. If the ratio exceeds $3.0\times$, an automated macro freeze triggers.

---

## 4. Human Intervention & Escalation Triggers

Autonomous agent authority must terminate whenever confidence decreases, data degrades, or financial exposure crosses acceptable thresholds. The system defines **four explicit conditions requiring human intervention**:

```
                             CONDITIONS REQUIRING HUMAN INTERVENTION
                                                │
         ┌──────────────────────┬───────────────┴──────────────┬──────────────────────┐
         ▼                      ▼                              ▼                      ▼
  [ Epistemic Ambiguity ] [ High Financial Impact ]  [ Offline Infrastructure ] [ Critic Deadlock ]
  • Cold start (<14d)     • Single tx > $5,000       • Amount > $500 to new     • Evaluator rejects
  • Divergence >= 45.0    • 24h spend > $5,000         destination               draft >= 2 times
  • RAG distance > 0.65   • Merchant dispute >= 25%  • Max-velocity >= 10       • Math error > 15.0
```

### Condition 1: Epistemic Uncertainty & Data Incompleteness
* **Cold-Start Profiles**: If customer account tenure is $< 14$ days or historical transactions $< 3$, automated `APPROVE` is barred for amounts $> \$100.00$. Transaction must be routed to `REVIEW` for KYC verification.
* **Signal Divergence / Contradiction**: If analytical risk factors exhibit violent disagreement (e.g. Geo Haversine flags Critical $90.0$ while Merchant MCC flags Low $5.0$, yielding $\Delta \ge 45.0$), the agent must not average the scores. Flag `AMBIGUITY_CONTRADICTORY_SIGNALS` $\rightarrow$ route to `REVIEW`.
* **Uncodified RAG Policy Scenarios**: If semantic retrieval distance against ChromaDB policy clauses exceeds $0.65$, no codified policy governs the transaction. The model cannot invent rules $\rightarrow$ route to compliance analyst.
* **Degraded Critical Telemetry**: Transactions $> \$500.00$ lacking verified IP geolocation or device fingerprinting cannot be approved autonomously.

### Condition 2: Financial Blast-Radius & Exposure Ceilings
* **Single Transaction Value Cap**: Any transaction $> \$5,000.00\text{ USD}$ automatically revokes autonomous approval authority. Requires human analyst sign-off or cryptographic step-up approval regardless of how low the agent's risk score is.
* **Cumulative 24-Hour Velocity Cap**: If 24-hour aggregate spend exceeds $\$5,000.00$ ([POL-2026-VEL-02](policy-docs/fraud-risk-policy-2026.md#L42-L45)), autonomous straight-through processing is suspended.
* **Chronic Merchant Dispute Rate**: Merchants exhibiting chargeback/dispute rates $\ge 25\%$ trigger mandatory analyst queue routing.

### Condition 3: Offline Infrastructure & Value-Based Fast-Path Gating (Pattern 2)
When Ollama, local models, or cloud LLMs are unreachable or disabled, routing 100% of traffic to manual review creates a severe queue bottleneck. Under **Pattern 2**:
* Deterministic feature extraction runs first via SQLite ([sqllite/crud.py](../src/sqllite/crud.py)).
* The system evaluates value-based risk criteria before calling the LLM reasoning plane:
  1. **Mandatory Human Escalation (`REVIEW`)**:
     * `amount > $500.00` to a **new destination** (country/city not in customer history, or merchant unverified).
     * **OR** transaction reaches **max-velocity $\ge 10$ transactions in 60 minutes**, even for new personas.
     * Response explicitly returns `system_state="OFFLINE_DETERMINISTIC_FAST_PATH"` and justifies the escalation.
  2. **Fast-Path Automated Approval (`APPROVE`)**:
     * Low-value transactions ($\le \$500.00$) with verified historical destinations and velocity $< 10$ auto-approve with `system_state="OFFLINE_DETERMINISTIC_FAST_PATH"` to keep checkout queues moving.

### Condition 4: Critic Deadlock & Retries Exceeded
* If the Evaluator Agent rejects the Decision Agent's draft twice with arithmetic discrepancies $> 15.0$ points or ungrounded assertions, execution aborts to `circuit_breaker_fallback_node`, forcing `REVIEW`.

---

## 5. Holistic Defense-in-Depth Safety Architecture

Safety is not achieved by an isolated prompt or a single rule. It operates as an **integrated triad**:

```
                       ┌─────────────────────────────────────────┐
                       │           STATIC GUARDRAILS             │
                       │ (Schema, Redaction, Hard Caps, Floors)  │
                       └────────────────────┬────────────────────┘
                                            │
                                            ▼
                       ┌─────────────────────────────────────────┐
                       │        AGENTIC AUDIT TRIAD              │
                       │    Actor (Decision) vs Critic (Evaluator)│
                       │       Grounding in ChromaDB RAG         │
                       └────────────────────┬────────────────────┘
                                            │
                                            ▼
                       ┌─────────────────────────────────────────┐
                       │     HUMAN-IN-THE-LOOP SAFETY NET        │
                       │ (Asynchronous State Suspension, REVIEW) │
                       └────────────────────┬────────────────────┘
                                            │
                                            ▼
                       ┌─────────────────────────────────────────┐
                       │      CONTINUOUS FEEDBACK FLYWHEEL       │
                       │ (Analyst overrides logged to LangSmith) │
                       └─────────────────────────────────────────┘
```

### How the Triad Operates Synergistically
1. **Static Guardrails Filter the Ingress**: Pydantic models and regex filters scrub data and reject malformed payloads before models burn compute or risk data leakage.
2. **Actor-Critic Dynamics Enforce Grounding**: The Decision Agent generates a risk rationale, but the Evaluator Agent acts as an independent compliance officer, verifying mathematical consistency, taxonomy adherence, and evidence citations before output release.
3. **Circuit Breakers Fail-Safe to Humans**: When ambiguity, model failure, or high financial exposure is detected, the system gracefully suspends execution into an `AWAITING_HUMAN_DECISION` state.
4. **Analyst Decisions Train the System**: When a human analyst approves or declines an escalated dossier via `POST /api/v1/transactions/{id}/decision`, the decision delta is captured in SQLite and LangSmith. This feedback loop identifies emerging fraud patterns and calibrates prompts without code deployments.

---

## 6. Architectural Trade-Off Analysis

Every robust architectural decision requires balancing competing priorities. The following trade-offs were evaluated:

| Architectural Dimension | Option Considered | Trade-Off Analysis | Adopted Decision & Justification |
|---|---|---|---|
| **1. Agent Coordination** | Strict Hierarchy vs. Peer-to-Peer | Peer-to-peer allows fast querying but risks infinite ping-pong loops and unmanaged latency. Hierarchical supervisor provides 100% auditability but adds orchestration overhead. | **Hybrid Tool-Proxy**: Central LangGraph supervisor controls state, but Analysis Agent is granted a supervised tool callback (`request_supplementary_data`) capped at 1 round-trip. |
| **2. Actor-Critic vs. Latency SLA** | Single-Pass LLM vs. Multi-Pass Evaluator Loop | Single-pass saves 1.5s but suffers from confirmation bias. Multi-pass critic loop audits decisions but risks blowing the 1,800 ms SLA. | **Targeted Differential Feedback**: The Evaluator audits drafts, but re-invokes *only* the failing agent (Decision or Analysis) with targeted instructions, capped at 3 retries with a hard 1.8s timeout. |
| **3. Offline Failure Strategy** | Blanket Human Review vs. Value-Based Fast-Path | Routing 100% of offline traffic to human review prevents all fraud but causes systemic checkout paralysis. Blanket auto-approval prevents bottlenecks but leaks financial loss. | **Pattern 2 Value-Based Gating**: Deterministic SQL features calculate velocity and destination offline; only high-value ($> \$500$ new dest) or burst ($\ge 10$ vel) route to humans; low-value ($\le \$500$) auto-approves. |
| **4. Ingress Offline Gate Placement** | Gateway Interceptor (Pattern 1) vs. Post-Feature Pre-LLM (Pattern 2) | Pattern 1 runs in API gateway middleware in $< 2\text{ ms}$ but duplicates tool SQL queries. Pattern 2 runs after feature skills in $\sim 15\text{ ms}$ within LangGraph. | **Pattern 2 Adopted**: Preserves 100% code reuse of modular skills, keeps the full WebSocket `AgentStepEvent` stream intact, and provides seamless graceful degradation. |
| **5. Autonomy vs. Oversight** | Unbounded Agent Decisions vs. Monetary Blast-Radius Cap | Unbounded autonomy allows straight-through processing of any amount but risks catastrophic loss on single-prompt failure. Hard caps require human effort on large transactions. | **Tiered Autonomy**: Full autonomy up to $\$1,000$; step-up authentication $\$1,000–\$5,000$; absolute mandatory human sign-off above $\$5,000$. |

---

## 7. Real-World Dependable Deployment Strategy

To ensure safe, robust, and compliant operation in production enterprise environments, the deployment plan enforces:

### A. Regulatory Compliance & Adverse Action Readiness
* **PCI-DSS v4.0.1 Compliance**: Continuous client-side masking guarantees PANs, PINs, and CVVs never touch LLM context windows, vector embeddings, or disk logs.
* **Fair Lending & ECOA/FCRA Alignment**: By requiring strict ChromaDB policy grounding and barring demographic proxy variables (such as zip-code redlining), adverse action notices cite verified, auditable business rules ([fraud-risk-policy-2026.md](policy-docs/fraud-risk-policy-2026.md)).

### B. High Availability & Graceful Degradation
* **Local LLM Independence**: The system defaults to local Ollama inference (`llama3.1:8b`, `llama3.2:3b`), ensuring zero dependency on external third-party cloud APIs for core scoring.
* **Deterministic Skill Fallback**: If local Ollama instances crash or run out of VRAM, the system transparently transitions to **Pattern 2 Value-Based Gating**, maintaining checkout availability while containing exposure on high-value transactions.

### C. Observability, Telemetry & Audit Trails
* **End-to-End Tracing**: OpenTelemetry and LangSmith traces bind every transaction to an immutable `trace_id`, capturing per-node latencies, token consumption, and model tiers.
* **Dual-Plane WebSocket Timeline**: Front-end analyst consoles receive real-time granular step events (`STEP_STARTED`, `TOOL_EXECUTED`, `CRITIC_VERDICT`, `CIRCUIT_BREAKER_TRIGGERED`), providing total explainability into why an agent reached its conclusion.

### D. Macro Circuit Breakers & Emergency Kill-Switches
* **Agent Feature Flags**: Every agent (`enable_orchestrator_agent`, `enable_data_retriever_agent`, `enable_analysis_agent`, `enable_decision_agent`, `enable_evaluator_agent`, `enable_rag_policy_retrieval`) can be toggled via environment variables without redeploying code.
* **Fleet Anomaly Tripping**: If fleet-wide decline rates surge $3\times$ beyond normal moving averages, a macro circuit breaker halts autonomous declining, reverting edge transactions to human queues to protect legitimate customers during unexpected model drift.

---

## 8. Summary Conclusion

The Transaction Fraud Scorer Agentic AI reconciles the cognitive power of generative multi-agent systems with the non-negotiable safety requirements of financial infrastructure. By pairing an **Actor-Critic architecture** with **immutable deterministic floors**, **epistemic ambiguity tripwires**, **value-based offline gating (Pattern 2)**, and **asynchronous human suspension**, the system ensures that:
1. High-confidence legitimate transactions proceed with zero checkout friction.
2. High-confidence fraud is blocked immediately with auditable legal citations.
3. Ambiguity, high financial exposure, and infrastructure degradation always fail safe to human oversight.

*This report constitutes the authoritative safety, risk control, and guardrail specification for enterprise deployment.*
