/**
 * Transaction Fraud Scorer — Vanilla JS Web Client (Multi-Page Controller)
 * Page 1 (index.html): Submit ACH & Card Transactions via REST (POST /api/v1/transactions/score)
 * Page 2 (queue.html): Real-Time WebSocket Event Queue (/ws/transactions/events) &
 *                      Accept/Reject Decisions (POST /api/v1/transactions/decision)
 */

(() => {
  const STORAGE_KEY_GATEWAY_URL = "fraud_scorer_gateway_url";

  // Shared DOM References (present on both index.html and queue.html)
  const gatewayUrlInput = document.getElementById("gateway-url");
  const btnCheckHealth = document.getElementById("btn-check-health");
  const healthStatusText = document.getElementById("health-status-text");
  const derivedScoreUrlCode = document.getElementById("derived-score-url");

  // Page 1 (Submit Transaction) DOM References
  const txForm = document.getElementById("transaction-form");
  const txTypeSelect = document.getElementById("tx-type");
  const cardFieldset = document.getElementById("card-details-fieldset");
  const achFieldset = document.getElementById("ach-details-fieldset");
  const btnPresetCard = document.getElementById("btn-preset-card");
  const btnPresetAch = document.getElementById("btn-preset-ach");
  const restScoreOutput = document.getElementById("rest-score-output");

  // Page 2 (Decision Queue) DOM References
  const wsUsernameFilterInput = document.getElementById("ws-username-filter");
  const btnConnectWs = document.getElementById("btn-connect-ws");
  const btnDisconnectWs = document.getElementById("btn-disconnect-ws");
  const wsStatusBadge = document.getElementById("ws-status-badge");
  const derivedWsUrlCode = document.getElementById("derived-ws-url");
  const wsEventsTbody = document.getElementById("ws-events-tbody");
  const btnClearEvents = document.getElementById("btn-clear-events");
  const wsEventInspector = document.getElementById("ws-event-inspector");

  const decisionTxIdInput = document.getElementById("decision-tx-id");
  const decisionReasonInput = document.getElementById("decision-reason");
  const btnAcceptTx = document.getElementById("btn-accept-tx");
  const btnRejectTx = document.getElementById("btn-reject-tx");
  const decisionResponseOutput = document.getElementById("decision-response-output");

  // PRD-018: Live Agent Reasoning Timeline & LangSmith Trace Badge
  const agentTimelineList = document.getElementById("live-agent-timeline-list");
  const langsmithTraceLink = document.getElementById("langsmith-trace-link");

  let activeSocket = null;
  const receivedEventsMap = new Map();

  // 1. Sync aria-invalid with CSS :user-invalid & WeakMap fallback per modern-web-guidance
  const UserInvalidFallback = (() => {
    const dirtyState = new WeakMap();

    const updateState = (input) => {
      const isValid = input.checkValidity();
      input.classList.toggle("user-invalid-fallback", !isValid);
      input.classList.toggle("user-valid-fallback", isValid);
      if (!isValid) {
        input.setAttribute("aria-invalid", "true");
      } else {
        input.removeAttribute("aria-invalid");
      }
    };

    const handleEvent = (event) => {
      const input = event.target;
      if (event.type === "reset") {
        const controls = input.elements || [];
        for (const control of controls) {
          dirtyState.delete(control);
          control.classList.remove("user-invalid-fallback", "user-valid-fallback");
          control.removeAttribute("aria-invalid");
        }
        return;
      }
      if (!input || typeof input.checkValidity !== "function") return;

      if (event.type === "input" || event.type === "change") {
        const state = dirtyState.get(input) || { hasInteracted: false, hasBlurred: false };
        state.hasInteracted = true;
        dirtyState.set(input, state);
        if (state.hasBlurred) updateState(input);
      } else if (event.type === "blur") {
        const state = dirtyState.get(input) || { hasInteracted: false, hasBlurred: false };
        state.hasBlurred = true;
        dirtyState.set(input, state);
        if (state.hasInteracted) updateState(input);
      }
    };

    const init = (root = document) => {
      if (typeof CSS !== "undefined" && CSS.supports("selector(:user-invalid)")) {
        const syncAria = (el) => {
          if (el && typeof el.matches === "function" && el.setAttribute) {
            el.setAttribute("aria-invalid", el.matches(":user-invalid") ? "true" : "false");
          }
        };
        root.addEventListener("blur", (e) => syncAria(e.target), true);
        root.addEventListener("input", (e) => {
          if (e.target && e.target.hasAttribute && e.target.hasAttribute("aria-invalid")) {
            syncAria(e.target);
          }
        });
        return;
      }
      root.addEventListener("blur", handleEvent, true);
      root.addEventListener("input", handleEvent);
      root.addEventListener("change", handleEvent);
      root.addEventListener("reset", handleEvent, true);
    };

    return { init };
  })();

  // 2. Gateway URL & Endpoint Derivation
  function getNormalizedBaseUrl() {
    const raw = (gatewayUrlInput && gatewayUrlInput.value ? gatewayUrlInput.value : "http://localhost:8000").trim();
    return raw.replace(/\/+$/, "");
  }

  function buildWebSocketUrl() {
    const baseUrl = getNormalizedBaseUrl();
    let wsBase = baseUrl;
    if (baseUrl.startsWith("https://")) {
      wsBase = "wss://" + baseUrl.slice("https://".length);
    } else if (baseUrl.startsWith("http://")) {
      wsBase = "ws://" + baseUrl.slice("http://".length);
    }
    const wsUrl = new URL(`${wsBase}/ws/transactions/events`);
    const usernameFilter = wsUsernameFilterInput ? (wsUsernameFilterInput.value || "").trim() : "";
    if (usernameFilter) {
      wsUrl.searchParams.set("username", usernameFilter);
    }
    return wsUrl.toString();
  }

  function updateDerivedEndpointsDisplay() {
    const baseUrl = getNormalizedBaseUrl();
    localStorage.setItem(STORAGE_KEY_GATEWAY_URL, baseUrl);

    if (derivedScoreUrlCode) {
      derivedScoreUrlCode.textContent = `${baseUrl}/api/v1/transactions/score`;
    }
    if (derivedWsUrlCode) {
      try {
        derivedWsUrlCode.textContent = buildWebSocketUrl();
      } catch {
        derivedWsUrlCode.textContent = "Invalid Gateway Base URL";
      }
    }
    const derivedUsersUrl = document.getElementById("derived-users-url");
    if (derivedUsersUrl) {
      derivedUsersUrl.textContent = `${baseUrl}/api/v1/db/user-profiles`;
    }
    const derivedTxUrl = document.getElementById("derived-transactions-url");
    if (derivedTxUrl) {
      derivedTxUrl.textContent = `${baseUrl}/api/v1/db/transactions`;
    }
    const derivedScoresUrl = document.getElementById("derived-scores-url");
    if (derivedScoresUrl) {
      derivedScoresUrl.textContent = `${baseUrl}/api/v1/db/transaction-scores`;
    }
    const derivedVectorUrl = document.getElementById("derived-vector-url");
    if (derivedVectorUrl) {
      derivedVectorUrl.textContent = `${baseUrl}/api/v1/vector/query`;
    }
  }

  // 3. WebSocket Connection Management (Page 2: queue.html)
  function setWsBadgeState(stateText, badgeClass) {
    if (!wsStatusBadge) return;
    wsStatusBadge.textContent = stateText;
    wsStatusBadge.className = `badge ${badgeClass}`;
  }

  function connectWebSocket() {
    if (!wsEventsTbody && !agentTimelineList) return;

    if (activeSocket) {
      activeSocket.close();
      activeSocket = null;
    }

    let wsUrl;
    try {
      wsUrl = buildWebSocketUrl();
    } catch {
      setWsBadgeState("Invalid URL", "badge-danger");
      return;
    }

    setWsBadgeState("Connecting...", "badge-warning");
    if (derivedWsUrlCode) {
      derivedWsUrlCode.textContent = wsUrl;
    }

    const socket = new WebSocket(wsUrl);
    activeSocket = socket;

    socket.addEventListener("open", () => {
      setWsBadgeState("Connected", "badge-success");
      if (btnConnectWs) btnConnectWs.textContent = "Reconnect WebSocket";
      if (btnDisconnectWs) btnDisconnectWs.disabled = false;
    });

    socket.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(event.data);
        handleIncomingWsEvent(payload);
      } catch {
        if (wsEventInspector) {
          wsEventInspector.textContent = `Raw WebSocket message: ${event.data}`;
        }
      }
    });

    socket.addEventListener("close", () => {
      if (activeSocket === socket) {
        setWsBadgeState("Disconnected", "badge-neutral");
        if (btnDisconnectWs) btnDisconnectWs.disabled = true;
        activeSocket = null;
      }
    });

    socket.addEventListener("error", () => {
      setWsBadgeState("Connection Error", "badge-danger");
    });
  }

  function disconnectWebSocket() {
    if (activeSocket) {
      activeSocket.close();
      activeSocket = null;
    }
    setWsBadgeState("Disconnected", "badge-neutral");
    if (btnDisconnectWs) btnDisconnectWs.disabled = true;
  }

  // 4. Render Incoming WebSocket Events (Page 2: queue.html)
  function statusToBadgeClass(status) {
    if (status === "APPROVE" || status === "ACCEPTED") return "badge-success";
    if (status === "REVIEW") return "badge-warning";
    return "badge-danger";
  }

  function updateTraceLink(runId, traceUrl) {
    if (!langsmithTraceLink) return;
    if (!runId) {
      langsmithTraceLink.classList.add("hidden");
      return;
    }
    const targetUrl = traceUrl || `https://smith.langchain.com/r/${encodeURIComponent(runId)}`;
    langsmithTraceLink.href = targetUrl;
    langsmithTraceLink.title = `LangSmith Run ID: ${runId}`;
    langsmithTraceLink.classList.remove("hidden");
  }

  function nodeToEmojiBadge(nodeName, status) {
    if (nodeName === "DataRetrieverAgent" || nodeName === "SupplementaryRetriever") return "🔵";
    if (nodeName === "AnalysisAgent") return "🟡";
    if (nodeName === "DecisionAgent") return "🟣";
    if (nodeName === "EvaluatorAgent") return status === "REJECTED" ? "🔴" : "🟢";
    if (nodeName === "CircuitBreakerFallback") return "🟠";
    return "⚪";
  }

  function handleAgentStepEvent(stepEvent) {
    const details = stepEvent.details || {};
    if (stepEvent.trace_id) {
      updateTraceLink(stepEvent.trace_id, details.trace_url);
    }
    if (!agentTimelineList) return;

    const emptyItem = agentTimelineList.querySelector(".agent-timeline-empty");
    if (emptyItem) {
      emptyItem.remove();
    }

    const txId = stepEvent.transaction_id || "tx";
    const nodeName = stepEvent.node_name || "Agent";
    const retryPass = typeof stepEvent.retry_count === "number" ? stepEvent.retry_count : 0;
    const itemId = `agent-step-${txId}-${nodeName}-${retryPass}`;

    let li = document.getElementById(itemId);
    if (!li) {
      li = document.createElement("li");
      li.id = itemId;
      li.className = "agent-timeline-item";
      agentTimelineList.appendChild(li);
    }

    const iconSpan = document.createElement("span");
    iconSpan.setAttribute("aria-hidden", "true");
    iconSpan.textContent = nodeToEmojiBadge(nodeName, stepEvent.status);

    const nodeSpan = document.createElement("span");
    nodeSpan.className = "agent-timeline-node";
    nodeSpan.textContent = `${nodeName}:`;

    const msgSpan = document.createElement("span");
    msgSpan.className = "agent-timeline-msg";
    msgSpan.textContent = stepEvent.message || stepEvent.status || "";

    const metaSpan = document.createElement("span");
    metaSpan.className = "agent-timeline-meta";
    const elapsedText =
      typeof stepEvent.elapsed_ms === "number" && stepEvent.elapsed_ms > 0
        ? `${Math.round(stepEvent.elapsed_ms)}ms`
        : stepEvent.status || "";
    metaSpan.textContent = retryPass > 0 ? `[retry #${retryPass}] ${elapsedText}` : elapsedText;

    li.replaceChildren(iconSpan, nodeSpan, msgSpan, metaSpan);
  }

  function handleIncomingWsEvent(eventData) {
    if (
      eventData &&
      eventData.event_type &&
      eventData.event_type !== "TRANSACTION_SCORED"
    ) {
      handleAgentStepEvent(eventData);
      return;
    }

    if (eventData && eventData.score_details && eventData.score_details.langsmith_run_id) {
      updateTraceLink(
        eventData.score_details.langsmith_run_id,
        eventData.score_details.trace_url
      );
    }

    if (!wsEventsTbody) return;

    const txId = eventData.transaction_id || "tx_unknown";
    receivedEventsMap.set(txId, eventData);

    const emptyRow = document.getElementById("ws-empty-row");
    if (emptyRow) {
      emptyRow.remove();
    }

    const status = (eventData.score_details && eventData.score_details.status) || "APPROVE";
    const amountFormatted = typeof eventData.amount === "number"
      ? `${eventData.amount.toFixed(2)} ${eventData.currency || "USD"}`
      : String(eventData.amount);

    const existingRow = document.getElementById(`row-${txId}`);
    if (existingRow) {
      existingRow.remove();
    }

    const tr = document.createElement("tr");
    tr.id = `row-${txId}`;

    const thTxId = document.createElement("th");
    thTxId.scope = "row";
    thTxId.textContent = txId;

    const tdUser = document.createElement("td");
    tdUser.textContent = eventData.username || "-";

    const tdAmount = document.createElement("td");
    tdAmount.textContent = amountFormatted;

    const tdScore = document.createElement("td");
    tdScore.textContent = typeof eventData.score === "number" ? eventData.score.toFixed(1) : String(eventData.score);

    const tdStatus = document.createElement("td");
    const statusBadge = document.createElement("span");
    statusBadge.id = `status-badge-${txId}`;
    statusBadge.className = `badge ${statusToBadgeClass(status)}`;
    statusBadge.textContent = status;
    tdStatus.appendChild(statusBadge);

    const tdActions = document.createElement("td");
    const actionWrap = document.createElement("div");
    actionWrap.className = "row-actions";

    const btnInspect = document.createElement("button");
    btnInspect.type = "button";
    btnInspect.className = "btn btn-sm btn-outline";
    btnInspect.textContent = "Inspect";
    btnInspect.addEventListener("click", () => selectTransactionEvent(txId));

    const btnAcceptRow = document.createElement("button");
    btnAcceptRow.type = "button";
    btnAcceptRow.className = "btn btn-sm btn-success";
    btnAcceptRow.textContent = "Accept";
    btnAcceptRow.addEventListener("click", () => {
      selectTransactionEvent(txId);
      const reason = decisionReasonInput ? decisionReasonInput.value : "Accepted via WebUI quick action.";
      submitDecision(txId, true, reason || "Accepted via WebUI quick action.");
    });

    const btnRejectRow = document.createElement("button");
    btnRejectRow.type = "button";
    btnRejectRow.className = "btn btn-sm btn-danger";
    btnRejectRow.textContent = "Reject";
    btnRejectRow.addEventListener("click", () => {
      selectTransactionEvent(txId);
      const reason = decisionReasonInput ? decisionReasonInput.value : "Rejected via WebUI quick action.";
      submitDecision(txId, false, reason || "Rejected via WebUI quick action.");
    });

    actionWrap.append(btnInspect, btnAcceptRow, btnRejectRow);
    tdActions.appendChild(actionWrap);

    tr.append(thTxId, tdUser, tdAmount, tdScore, tdStatus, tdActions);
    wsEventsTbody.prepend(tr);

    selectTransactionEvent(txId);
  }

  function selectTransactionEvent(txId) {
    if (decisionTxIdInput) {
      decisionTxIdInput.value = txId;
    }
    const eventData = receivedEventsMap.get(txId);
    if (eventData && wsEventInspector) {
      wsEventInspector.textContent = JSON.stringify(eventData, null, 2);
    }
  }

  // 5. Toggle CARD / ACH Form Sections & Presets (Page 1: index.html)
  function syncPaymentRailVisibility() {
    if (!txTypeSelect || !cardFieldset || !achFieldset) return;
    const isAch = txTypeSelect.value === "ACH";
    cardFieldset.classList.toggle("hidden", isAch);
    achFieldset.classList.toggle("hidden", !isAch);
  }

  function loadCardPreset() {
    if (!txTypeSelect) return;
    txTypeSelect.value = "CARD";
    syncPaymentRailVisibility();
    document.getElementById("tx-username").value = "jdoe_99";
    document.getElementById("tx-datetime").value = new Date().toISOString();
    document.getElementById("tx-ip").value = "198.51.100.42";
    document.getElementById("tx-device-id").value = "dev_macbook_pro_91a";
    document.getElementById("loc-latitude").value = "37.7749";
    document.getElementById("loc-longitude").value = "-122.4194";
    document.getElementById("loc-city").value = "San Francisco";
    document.getElementById("loc-state").value = "CA";
    document.getElementById("loc-country").value = "US";
    document.getElementById("loc-postal").value = "94103";
    document.getElementById("tx-amount").value = "1450.00";
    document.getElementById("tx-currency").value = "USD";
    document.getElementById("merch-id").value = "merch_88412";
    document.getElementById("merch-name").value = "ElectroWorld Online";
    document.getElementById("merch-mcc").value = "5732";
    document.getElementById("card-type").value = "CREDIT";
    document.getElementById("card-network").value = "VISA";
    document.getElementById("card-last-four").value = "4242";
    document.getElementById("card-present").checked = false;
    document.getElementById("card-cvv").checked = true;
    document.getElementById("card-avs").value = "Y";
  }

  function loadAchPreset() {
    if (!txTypeSelect) return;
    txTypeSelect.value = "ACH";
    syncPaymentRailVisibility();
    document.getElementById("tx-username").value = "jdoe_99";
    document.getElementById("tx-datetime").value = new Date().toISOString();
    document.getElementById("tx-ip").value = "198.51.100.42";
    document.getElementById("loc-latitude").value = "37.7749";
    document.getElementById("loc-longitude").value = "-122.4194";
    document.getElementById("loc-city").value = "San Francisco";
    document.getElementById("loc-state").value = "CA";
    document.getElementById("loc-country").value = "US";
    document.getElementById("tx-amount").value = "4800.00";
    document.getElementById("tx-currency").value = "USD";
    document.getElementById("merch-id").value = "merch_payroll_01";
    document.getElementById("merch-name").value = "Acme Financial Services";
    document.getElementById("merch-mcc").value = "6012";
    document.getElementById("ach-routing").value = "021000021";
    document.getElementById("ach-last-four").value = "9876";
    document.getElementById("ach-account-type").value = "CHECKING";
    document.getElementById("ach-sec-code").value = "WEB";
    document.getElementById("ach-direction").value = "DEBIT";
    document.getElementById("ach-bank-name").value = "Chase Bank";
  }

  // 5b. Manual Test Transaction Loaders (PRD-012, Page 1: index.html)
  //     Test data is loaded/generated entirely inside the WebClient. The API Gateway stays headless
  //     and never knows about test datasets — it only receives the standard score request on submit.
  const TEST_DATASET_URL = "dataset/test_transactions_dataset.json";

  // Mirrors _LOCATIONS / _GOOD_MERCHANTS / _BAD_MERCHANTS / _ANOMALY_LOCATIONS in src/sqllite/seed.py
  // so generated transactions line up with seeded persona histories.
  const HOME_LOCATIONS = [
    { city: "San Francisco", state: "CA", postal_code: "94103", latitude: 37.7749, longitude: -122.4194 },
    { city: "New York", state: "NY", postal_code: "10001", latitude: 40.7128, longitude: -74.006 },
    { city: "Austin", state: "TX", postal_code: "78701", latitude: 30.2672, longitude: -97.7431 },
    { city: "Seattle", state: "WA", postal_code: "98101", latitude: 47.6062, longitude: -122.3321 },
    { city: "Chicago", state: "IL", postal_code: "60601", latitude: 41.8781, longitude: -87.6298 },
    { city: "Denver", state: "CO", postal_code: "80202", latitude: 39.7392, longitude: -104.9903 },
    { city: "Boston", state: "MA", postal_code: "02108", latitude: 42.3601, longitude: -71.0589 },
    { city: "Miami", state: "FL", postal_code: "33131", latitude: 25.7617, longitude: -80.1918 },
    { city: "Atlanta", state: "GA", postal_code: "30303", latitude: 33.749, longitude: -84.388 },
    { city: "Phoenix", state: "AZ", postal_code: "85004", latitude: 33.4484, longitude: -112.074 },
  ];

  const GOOD_MERCHANTS = [
    { merchant_id: "merch_grocery_01", name: "Whole Foods Market", mcc: "5411" },
    { merchant_id: "merch_cafe_02", name: "Blue Bottle Coffee", mcc: "5814" },
    { merchant_id: "merch_fuel_03", name: "Shell Service Station", mcc: "5541" },
    { merchant_id: "merch_pharmacy_04", name: "Walgreens Pharmacy", mcc: "5912" },
    { merchant_id: "merch_retail_05", name: "Target Store", mcc: "5311" },
    { merchant_id: "merch_utility_06", name: "Pacific Gas & Electric", mcc: "4900" },
    { merchant_id: "merch_dining_07", name: "Sweetgreen Kitchen", mcc: "5812" },
    { merchant_id: "merch_books_08", name: "Powell's City of Books", mcc: "5942" },
  ];

  const FRAUD_MERCHANTS = [
    { merchant_id: "merch_casino_91", name: "Royal Flush Online Casino", mcc: "7995" },
    { merchant_id: "merch_crypto_92", name: "Instant Crypto OTC Exchange", mcc: "6051" },
    { merchant_id: "merch_wire_93", name: "Global Express Wire Transfer", mcc: "4829" },
    { merchant_id: "merch_tele_94", name: "Direct Inbound TeleServices", mcc: "5967" },
    { merchant_id: "merch_pawn_95", name: "Metro Gold & Bullion Exchange", mcc: "5933" },
  ];

  const FRAUD_LOCATIONS = [
    { city: "Tokyo", state: "TK", country: "JP", postal_code: "100-0001", latitude: 35.6762, longitude: 139.6503 },
    { city: "London", state: "LND", country: "GB", postal_code: "EC1A", latitude: 51.5074, longitude: -0.1278 },
    { city: "Lagos", state: "LA", country: "NG", postal_code: "100001", latitude: 6.5244, longitude: 3.3792 },
    { city: "Frankfurt", state: "HE", country: "DE", postal_code: "60311", latitude: 50.1109, longitude: 8.6821 },
    { city: "Sydney", state: "NSW", country: "AU", postal_code: "2000", latitude: -33.8688, longitude: 151.2093 },
    { city: "Bucharest", state: "B", country: "RO", postal_code: "010011", latitude: 44.4268, longitude: 26.1025 },
    { city: "Macau", state: "MO", country: "MO", postal_code: "999078", latitude: 22.1987, longitude: 113.5439 },
  ];

  let cachedTestDataset = null;
  let lastTestDatasetIndex = -1;

  const randInt = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;
  const pick = (items) => items[randInt(0, items.length - 1)];
  const randDigits = (count) => Array.from({ length: count }, () => randInt(0, 9)).join("");
  const randAmount = (min, max) => Math.round((Math.random() * (max - min) + min) * 100) / 100;
  const pad2 = (n) => String(n).padStart(2, "0");

  async function loadTestDatasetFromWebClient() {
    if (cachedTestDataset) return cachedTestDataset;
    // Relative URL => served by the WebClient's own server (src/web_client/server.py), never the API Gateway.
    const response = await fetch(TEST_DATASET_URL, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} loading ${TEST_DATASET_URL}`);
    }
    const data = await response.json();
    const items = Array.isArray(data) ? data : data.transactions || [];
    if (items.length === 0) {
      throw new Error("test_transactions_dataset.json contains no transactions");
    }
    cachedTestDataset = items;
    return cachedTestDataset;
  }

  function setFieldValue(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    if (el.type === "checkbox") {
      el.checked = Boolean(value);
    } else {
      el.value = value === null || value === undefined ? "" : String(value);
    }
  }

  function clearFormValidationState() {
    if (!txForm) return;
    for (const control of txForm.elements) {
      control.classList.remove("user-invalid-fallback", "user-valid-fallback");
      control.removeAttribute("aria-invalid");
    }
  }

  function populateFormFromTransaction(entry) {
    if (!txTypeSelect || !entry) return;
    const loc = entry.location || {};
    const details = entry.transaction_details || {};
    const merchant = details.merchant || {};

    setFieldValue("tx-username", entry.username);
    setFieldValue("tx-datetime", entry.datetime || new Date().toISOString());
    setFieldValue("tx-ip", entry.ip);
    setFieldValue("tx-device-id", entry.device_id);
    setFieldValue("loc-latitude", loc.latitude);
    setFieldValue("loc-longitude", loc.longitude);
    setFieldValue("loc-city", loc.city);
    setFieldValue("loc-state", loc.state);
    setFieldValue("loc-country", loc.country || "US");
    setFieldValue("loc-postal", loc.postal_code);

    txTypeSelect.value = details.transaction_type === "ACH" ? "ACH" : "CARD";
    syncPaymentRailVisibility();

    setFieldValue("tx-amount", typeof details.amount === "number" ? details.amount.toFixed(2) : details.amount);
    setFieldValue("tx-currency", details.currency || "USD");
    setFieldValue("merch-id", merchant.merchant_id);
    setFieldValue("merch-name", merchant.name);
    setFieldValue("merch-mcc", merchant.mcc);

    if (details.card_details) {
      const card = details.card_details;
      setFieldValue("card-type", card.card_type || "CREDIT");
      setFieldValue("card-network", card.card_network || "VISA");
      setFieldValue("card-last-four", card.card_last_four);
      setFieldValue("card-present", card.is_card_present);
      setFieldValue("card-cvv", card.cvv_verified);
      setFieldValue("card-avs", card.avs_result);
    }
    if (details.ach_details) {
      const ach = details.ach_details;
      setFieldValue("ach-routing", ach.routing_number);
      setFieldValue("ach-last-four", ach.account_last_four);
      setFieldValue("ach-account-type", ach.account_type || "CHECKING");
      setFieldValue("ach-sec-code", ach.sec_code || "WEB");
      setFieldValue("ach-direction", ach.direction || "DEBIT");
      setFieldValue("ach-bank-name", ach.bank_name);
    }

    clearFormValidationState();
  }

  function renderTestDetails(entry, sourceLabel) {
    const profile = (entry.transaction_profile || "").toLowerCase();
    const isGood = profile === "good";
    const profileBadge = document.getElementById("test-detail-profile");
    if (profileBadge) {
      profileBadge.textContent = isGood ? "Expected: GOOD" : "Expected: FRAUD";
      profileBadge.className = `badge ${isGood ? "badge-success" : "badge-danger"}`;
    }
    setText("test-detail-scenario-id", entry.scenario_id || "-");
    setText("test-detail-source", sourceLabel);
    setText("test-detail-persona", entry.persona_group || "-");
    setText("test-detail-username", entry.username || "-");
    setText("test-detail-description", entry.description || "-");
    setText("test-detail-json", JSON.stringify(entry, null, 2));
  }

  function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  async function importRandomTestTransaction() {
    try {
      const items = await loadTestDatasetFromWebClient();
      let idx = randInt(0, items.length - 1);
      if (items.length > 1 && idx === lastTestDatasetIndex) {
        idx = (idx + 1) % items.length;
      }
      lastTestDatasetIndex = idx;
      // Deep clone and refresh the timestamp so velocity/geo checks evaluate against "now".
      const entry = JSON.parse(JSON.stringify(items[idx]));
      entry.datetime = new Date().toISOString();
      populateFormFromTransaction(entry);
      renderTestDetails(entry, `test_transactions_dataset.json (#${idx + 1} of ${items.length})`);
    } catch (err) {
      const profileBadge = document.getElementById("test-detail-profile");
      if (profileBadge) {
        profileBadge.textContent = "Load Error";
        profileBadge.className = "badge badge-warning";
      }
      setText(
        "test-detail-description",
        `Could not load test_transactions_dataset.json from the WebClient (${err.message}). ` +
          "Start the WebClient with `uv run fraud-web-client` so /dataset/test_transactions_dataset.json is served."
      );
    }
  }

  function generateGoodTransaction() {
    const useNewPersona = Math.random() < 0.25;
    let username;
    let home;
    let personaGroup;
    if (useNewPersona) {
      username = `new_user_${randDigits(5)}`;
      home = pick(HOME_LOCATIONS);
      personaGroup = "generated_new_persona";
    } else {
      // good_persona_01..20 have weekly history; home city follows seed.py's (idx - 1) % 10 rule.
      const idx = randInt(1, 20);
      username = `good_persona_${pad2(idx)}`;
      home = HOME_LOCATIONS[(idx - 1) % HOME_LOCATIONS.length];
      personaGroup = "existing_persona";
    }
    const merchant = pick(GOOD_MERCHANTS);
    const amount = randAmount(12, 145);
    const isAch = Math.random() < 0.25;
    const stamp = Date.now().toString(36);

    const details = {
      transaction_id: `tx_gen_good_${stamp}`,
      transaction_type: isAch ? "ACH" : "CARD",
      amount,
      currency: "USD",
      merchant: { ...merchant, country: "US" },
    };
    if (isAch) {
      details.ach_details = {
        routing_number: "021000021",
        account_last_four: randDigits(4),
        account_type: "CHECKING",
        sec_code: pick(["PPD", "WEB"]),
        direction: "DEBIT",
        bank_name: "Chase Bank",
      };
    } else {
      details.card_details = {
        card_type: pick(["CREDIT", "DEBIT"]),
        card_network: pick(["VISA", "MASTERCARD"]),
        card_last_four: randDigits(4),
        is_card_present: true,
        cvv_verified: true,
        avs_result: "Y",
      };
    }

    const entry = {
      scenario_id: `generated_good_${stamp}`,
      persona_group: personaGroup,
      transaction_profile: "good",
      description:
        `Generated low-risk ${details.transaction_type} purchase by '${username}' at ${merchant.name} ` +
        `(MCC ${merchant.mcc}) in home city ${home.city}, ${home.state} for $${amount.toFixed(2)}.`,
      username,
      datetime: new Date().toISOString(),
      ip: `198.51.100.${randInt(2, 254)}`,
      device_id: `dev_${username}`,
      location: {
        latitude: home.latitude,
        longitude: home.longitude,
        city: home.city,
        state: home.state,
        country: "US",
        postal_code: home.postal_code,
      },
      transaction_details: details,
    };
    populateFormFromTransaction(entry);
    renderTestDetails(entry, "Generated Good Transaction (client-side)");
  }

  function generateFraudTransaction() {
    const takeover = Math.random() < 0.5;
    const username = takeover ? `good_persona_${pad2(randInt(1, 20))}` : `bad_persona_${pad2(randInt(1, 10))}`;
    const merchant = pick(FRAUD_MERCHANTS);
    const loc = pick(FRAUD_LOCATIONS);
    const amount = randAmount(3200, 9850);
    const isAch = Math.random() < 0.3;
    const stamp = Date.now().toString(36);

    const details = {
      transaction_id: `tx_gen_fraud_${stamp}`,
      transaction_type: isAch ? "ACH" : "CARD",
      amount,
      currency: "USD",
      merchant: { ...merchant, country: loc.country },
    };
    if (isAch) {
      details.ach_details = {
        routing_number: randDigits(9),
        account_last_four: randDigits(4),
        account_type: "CHECKING",
        sec_code: pick(["TEL", "WEB"]),
        direction: "DEBIT",
        bank_name: "Offshore Clearing Bank",
      };
    } else {
      details.card_details = {
        card_type: pick(["CREDIT", "PREPAID"]),
        card_network: pick(["VISA", "MASTERCARD", "OTHER"]),
        card_last_four: randDigits(4),
        is_card_present: false,
        cvv_verified: false,
        avs_result: "N",
      };
    }

    const entry = {
      scenario_id: `generated_fraud_${stamp}`,
      persona_group: takeover ? "existing_persona_account_takeover" : "existing_bad_persona",
      transaction_profile: "bad",
      description:
        `Generated fraudulent ${details.transaction_type} transaction for '${username}' from ${loc.city}, ` +
        `${loc.country} (impossible travel / unrecognized device) at high-risk merchant ${merchant.name} ` +
        `(MCC ${merchant.mcc}) for $${amount.toFixed(2)}.`,
      username,
      datetime: new Date().toISOString(),
      ip: `203.0.113.${randInt(2, 254)}`,
      device_id: `dev_unrecognized_${randDigits(6)}`,
      location: {
        latitude: loc.latitude,
        longitude: loc.longitude,
        city: loc.city,
        state: loc.state,
        country: loc.country,
        postal_code: loc.postal_code,
      },
      transaction_details: details,
    };
    populateFormFromTransaction(entry);
    renderTestDetails(entry, "Generated Fraud Transaction (client-side)");
  }

  // 6. Build & Submit REST Transaction Score Request (Page 1: index.html)
  function buildTransactionPayload() {
    const txType = txTypeSelect.value;
    const transactionDetails = {
      transaction_type: txType,
      amount: parseFloat(document.getElementById("tx-amount").value),
      currency: document.getElementById("tx-currency").value.trim().toUpperCase(),
      merchant: {
        merchant_id: document.getElementById("merch-id").value.trim(),
        name: document.getElementById("merch-name").value.trim(),
        mcc: document.getElementById("merch-mcc").value.trim(),
        country: document.getElementById("loc-country").value.trim().toUpperCase() || "US",
      },
    };

    if (txType === "CARD") {
      transactionDetails.card_details = {
        card_type: document.getElementById("card-type").value,
        card_network: document.getElementById("card-network").value,
        card_last_four: document.getElementById("card-last-four").value.trim(),
        is_card_present: document.getElementById("card-present").checked,
        cvv_verified: document.getElementById("card-cvv").checked,
        avs_result: document.getElementById("card-avs").value.trim() || null,
      };
    } else {
      transactionDetails.ach_details = {
        routing_number: document.getElementById("ach-routing").value.trim(),
        account_last_four: document.getElementById("ach-last-four").value.trim(),
        account_type: document.getElementById("ach-account-type").value,
        sec_code: document.getElementById("ach-sec-code").value,
        direction: document.getElementById("ach-direction").value,
        bank_name: document.getElementById("ach-bank-name").value.trim() || null,
      };
    }

    return {
      username: document.getElementById("tx-username").value.trim(),
      datetime: document.getElementById("tx-datetime").value.trim() || new Date().toISOString(),
      ip: document.getElementById("tx-ip").value.trim(),
      device_id: document.getElementById("tx-device-id").value.trim() || null,
      location: {
        latitude: parseFloat(document.getElementById("loc-latitude").value),
        longitude: parseFloat(document.getElementById("loc-longitude").value),
        city: document.getElementById("loc-city").value.trim() || null,
        state: document.getElementById("loc-state").value.trim() || null,
        country: document.getElementById("loc-country").value.trim().toUpperCase(),
        postal_code: document.getElementById("loc-postal").value.trim() || null,
      },
      transaction_details: transactionDetails,
    };
  }

  async function handleTransactionSubmit(event) {
    event.preventDefault();
    const baseUrl = getNormalizedBaseUrl();
    const payload = buildTransactionPayload();
    if (restScoreOutput) {
      restScoreOutput.textContent = "Submitting transaction to API Gateway...";
    }
    if (agentTimelineList) {
      agentTimelineList.innerHTML = `
        <li class="agent-timeline-empty">
          Streaming LangGraph agent execution steps...
        </li>
      `;
    }

    try {
      const response = await fetch(`${baseUrl}/api/v1/transactions/score`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (restScoreOutput) {
        restScoreOutput.textContent = JSON.stringify(data, null, 2);
      }
      if (data && data.langsmith_run_id) {
        updateTraceLink(data.langsmith_run_id, data.trace_url);
      }
      if (data && data.transaction_id && decisionTxIdInput) {
        decisionTxIdInput.value = data.transaction_id;
      }
    } catch (err) {
      if (restScoreOutput) {
        restScoreOutput.textContent = `Request Error: ${err.message}`;
      }
    }
  }

  // 7. Submit Accept / Reject Decision (`POST /api/v1/transactions/decision`) (Page 2: queue.html)
  async function submitDecision(transactionId, accept, reason) {
    const txId = (transactionId || "").trim();
    const cleanReason = (reason || "").trim();
    if (!txId || !cleanReason) {
      if (decisionResponseOutput) {
        decisionResponseOutput.textContent = "Please provide both a Transaction ID and a Reason.";
      }
      return;
    }

    const baseUrl = getNormalizedBaseUrl();
    if (decisionResponseOutput) {
      decisionResponseOutput.textContent = "Submitting decision...";
    }

    try {
      const response = await fetch(`${baseUrl}/api/v1/transactions/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          transaction_id: txId,
          accept: Boolean(accept),
          reason: cleanReason,
        }),
      });
      const data = await response.json();
      if (decisionResponseOutput) {
        decisionResponseOutput.textContent = JSON.stringify(data, null, 2);
      }

      if (data && data.decision_applied) {
        const badgeEl = document.getElementById(`status-badge-${txId}`);
        if (badgeEl) {
          badgeEl.textContent = data.decision_applied;
          badgeEl.className = `badge ${statusToBadgeClass(data.decision_applied)}`;
        }
      }
    } catch (err) {
      if (decisionResponseOutput) {
        decisionResponseOutput.textContent = `Decision Request Error: ${err.message}`;
      }
    }
  }

  // 8. Check Gateway Health (`GET /health`)
  async function checkGatewayHealth() {
    const baseUrl = getNormalizedBaseUrl();
    if (healthStatusText) {
      healthStatusText.textContent = "Checking /health...";
    }
    try {
      const response = await fetch(`${baseUrl}/health`);
      const data = await response.json();
      if (healthStatusText) {
        healthStatusText.textContent = `Health OK (Model: ${data.model || "N/A"}, Ollama: ${
          data.ollama_connected ? "Online" : "Offline/Mock"
        })`;
      }
    } catch (err) {
      if (healthStatusText) {
        healthStatusText.textContent = `Health Check Failed: ${err.message}`;
      }
    }
  }

  // 9. RDBMS Paginated Table Controllers (Page 3: users.html, Page 4: transactions.html, Page 5: scores.html)
  function initUsersTablePage() {
    const tbody = document.getElementById("users-table-tbody");
    if (!tbody) return;

    const pageSizeSelect = document.getElementById("users-page-size");
    const pageInfo = document.getElementById("users-page-info");
    const prevBtn = document.getElementById("users-prev-btn");
    const nextBtn = document.getElementById("users-next-btn");
    const refreshBtn = document.getElementById("btn-refresh-users");
    const form = document.getElementById("user-profile-form");
    const btnUpdate = document.getElementById("btn-update-user");
    const output = document.getElementById("user-crud-output");

    let currentPage = 1;
    let totalPages = 1;

    async function loadUsersPage() {
      const baseUrl = getNormalizedBaseUrl();
      const pageSize = parseInt(pageSizeSelect ? pageSizeSelect.value : "10", 10) || 10;
      try {
        const resp = await fetch(`${baseUrl}/api/v1/db/user-profiles?page=${currentPage}&page_size=${pageSize}`);
        const data = await resp.json();
        totalPages = data.total_pages || 1;
        currentPage = data.page || 1;
        if (pageInfo) {
          pageInfo.textContent = `Page ${currentPage} of ${totalPages} (${data.total || 0} total)`;
        }
        if (prevBtn) prevBtn.disabled = currentPage <= 1;
        if (nextBtn) nextBtn.disabled = currentPage >= totalPages;

        tbody.innerHTML = "";
        const items = data.items || [];
        if (items.length === 0) {
          tbody.innerHTML = `<tr><td colspan="8" class="empty-cell">No user_profiles rows found.</td></tr>`;
          return;
        }

        for (const item of items) {
          const tr = document.createElement("tr");
          const th = document.createElement("th");
          th.scope = "row";
          th.textContent = item.username;

          const tdCreated = document.createElement("td");
          tdCreated.textContent = item.created_date || "-";
          const tdAddr = document.createElement("td");
          tdAddr.textContent = item.address || "-";
          const tdCity = document.createElement("td");
          tdCity.textContent = item.city || "-";
          const tdState = document.createElement("td");
          tdState.textContent = item.state || "-";
          const tdCountry = document.createElement("td");
          tdCountry.textContent = item.country || "US";
          const tdPostal = document.createElement("td");
          tdPostal.textContent = item.postal_code || "-";

          const tdActions = document.createElement("td");
          const actionWrap = document.createElement("div");
          actionWrap.className = "row-actions";

          const btnEdit = document.createElement("button");
          btnEdit.type = "button";
          btnEdit.className = "btn btn-sm btn-outline";
          btnEdit.textContent = "Edit";
          btnEdit.addEventListener("click", () => {
            document.getElementById("up-username").value = item.username || "";
            document.getElementById("up-address").value = item.address || "";
            document.getElementById("up-city").value = item.city || "";
            document.getElementById("up-state").value = item.state || "";
            document.getElementById("up-country").value = item.country || "US";
            document.getElementById("up-postal").value = item.postal_code || "";
            if (output) output.textContent = JSON.stringify(item, null, 2);
          });

          const btnDelete = document.createElement("button");
          btnDelete.type = "button";
          btnDelete.className = "btn btn-sm btn-danger";
          btnDelete.textContent = "Delete";
          btnDelete.addEventListener("click", async () => {
            const delResp = await fetch(
              `${getNormalizedBaseUrl()}/api/v1/db/user-profiles/${encodeURIComponent(item.username)}`,
              { method: "DELETE" }
            );
            const delData = await delResp.json();
            if (output) output.textContent = JSON.stringify(delData, null, 2);
            await loadUsersPage();
          });

          actionWrap.append(btnEdit, btnDelete);
          tdActions.appendChild(actionWrap);
          tr.append(th, tdCreated, tdAddr, tdCity, tdState, tdCountry, tdPostal, tdActions);
          tbody.appendChild(tr);
        }
      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="8" class="empty-cell">Error loading user_profiles: ${err.message}</td></tr>`;
      }
    }

    if (prevBtn) {
      prevBtn.addEventListener("click", () => {
        if (currentPage > 1) {
          currentPage -= 1;
          loadUsersPage();
        }
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", () => {
        if (currentPage < totalPages) {
          currentPage += 1;
          loadUsersPage();
        }
      });
    }
    if (pageSizeSelect) {
      pageSizeSelect.addEventListener("change", () => {
        currentPage = 1;
        loadUsersPage();
      });
    }
    if (refreshBtn) {
      refreshBtn.addEventListener("click", loadUsersPage);
    }
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const payload = {
          username: document.getElementById("up-username").value.trim(),
          address: document.getElementById("up-address").value.trim() || null,
          city: document.getElementById("up-city").value.trim() || null,
          state: document.getElementById("up-state").value.trim() || null,
          country: document.getElementById("up-country").value.trim().toUpperCase() || "US",
          postal_code: document.getElementById("up-postal").value.trim() || null,
        };
        const resp = await fetch(`${getNormalizedBaseUrl()}/api/v1/db/user-profiles`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (output) output.textContent = JSON.stringify(data, null, 2);
        await loadUsersPage();
      });
    }
    if (btnUpdate) {
      btnUpdate.addEventListener("click", async () => {
        const username = document.getElementById("up-username").value.trim();
        if (!username) return;
        const payload = {
          address: document.getElementById("up-address").value.trim() || null,
          city: document.getElementById("up-city").value.trim() || null,
          state: document.getElementById("up-state").value.trim() || null,
          country: document.getElementById("up-country").value.trim().toUpperCase() || "US",
          postal_code: document.getElementById("up-postal").value.trim() || null,
        };
        const resp = await fetch(
          `${getNormalizedBaseUrl()}/api/v1/db/user-profiles/${encodeURIComponent(username)}`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          }
        );
        const data = await resp.json();
        if (output) output.textContent = JSON.stringify(data, null, 2);
        await loadUsersPage();
      });
    }

    loadUsersPage();
  }

  function initTransactionsTablePage() {
    const tbody = document.getElementById("transactions-table-tbody");
    if (!tbody) return;

    const statusFilter = document.getElementById("tx-filter-status");
    const pageSizeSelect = document.getElementById("tx-page-size");
    const pageInfo = document.getElementById("tx-page-info");
    const prevBtn = document.getElementById("tx-prev-btn");
    const nextBtn = document.getElementById("tx-next-btn");
    const refreshBtn = document.getElementById("btn-refresh-transactions");
    const form = document.getElementById("db-transaction-form");
    const btnUpdate = document.getElementById("btn-update-db-tx");
    const output = document.getElementById("tx-crud-output");

    let currentPage = 1;
    let totalPages = 1;

    async function loadTransactionsPage() {
      const baseUrl = getNormalizedBaseUrl();
      const pageSize = parseInt(pageSizeSelect ? pageSizeSelect.value : "10", 10) || 10;
      const statusVal = statusFilter ? statusFilter.value : "";
      const params = new URLSearchParams({
        page: String(currentPage),
        page_size: String(pageSize),
      });
      if (statusVal) params.set("status", statusVal);

      try {
        const resp = await fetch(`${baseUrl}/api/v1/db/transactions?${params.toString()}`);
        const data = await resp.json();
        totalPages = data.total_pages || 1;
        currentPage = data.page || 1;
        if (pageInfo) {
          pageInfo.textContent = `Page ${currentPage} of ${totalPages} (${data.total || 0} total)`;
        }
        if (prevBtn) prevBtn.disabled = currentPage <= 1;
        if (nextBtn) nextBtn.disabled = currentPage >= totalPages;

        tbody.innerHTML = "";
        const items = data.items || [];
        if (items.length === 0) {
          tbody.innerHTML = `<tr><td colspan="8" class="empty-cell">No transactions rows found.</td></tr>`;
          return;
        }

        for (const item of items) {
          const tr = document.createElement("tr");
          const th = document.createElement("th");
          th.scope = "row";
          th.textContent = item.transaction_id;

          const tdUser = document.createElement("td");
          tdUser.textContent = item.username;
          const tdType = document.createElement("td");
          tdType.textContent = item.transaction_type;
          const tdAmount = document.createElement("td");
          tdAmount.textContent = `${Number(item.amount).toFixed(2)} ${item.currency || "USD"}`;
          const tdMerch = document.createElement("td");
          tdMerch.textContent = item.merchant_name || item.merchant_id || "-";
          const tdLoc = document.createElement("td");
          tdLoc.textContent = `${item.city || "-"}, ${item.country || "US"}`;

          const tdStatus = document.createElement("td");
          const badge = document.createElement("span");
          badge.className = `badge ${statusToBadgeClass(item.status)}`;
          badge.textContent = item.status;
          tdStatus.appendChild(badge);

          const tdActions = document.createElement("td");
          const actionWrap = document.createElement("div");
          actionWrap.className = "row-actions";

          const btnEdit = document.createElement("button");
          btnEdit.type = "button";
          btnEdit.className = "btn btn-sm btn-outline";
          btnEdit.textContent = "Edit";
          btnEdit.addEventListener("click", () => {
            document.getElementById("db-tx-id").value = item.transaction_id;
            document.getElementById("db-tx-username").value = item.username;
            document.getElementById("db-tx-type").value = item.transaction_type;
            document.getElementById("db-tx-amount").value = item.amount;
            document.getElementById("db-tx-lat").value = item.latitude;
            document.getElementById("db-tx-lon").value = item.longitude;
            document.getElementById("db-tx-city").value = item.city || "";
            document.getElementById("db-tx-status").value = item.status;
            if (output) output.textContent = JSON.stringify(item, null, 2);
          });

          const btnDelete = document.createElement("button");
          btnDelete.type = "button";
          btnDelete.className = "btn btn-sm btn-danger";
          btnDelete.textContent = "Delete";
          btnDelete.addEventListener("click", async () => {
            const delResp = await fetch(
              `${getNormalizedBaseUrl()}/api/v1/db/transactions/${encodeURIComponent(item.transaction_id)}`,
              { method: "DELETE" }
            );
            const delData = await delResp.json();
            if (output) output.textContent = JSON.stringify(delData, null, 2);
            await loadTransactionsPage();
          });

          actionWrap.append(btnEdit, btnDelete);
          tdActions.appendChild(actionWrap);
          tr.append(th, tdUser, tdType, tdAmount, tdMerch, tdLoc, tdStatus, tdActions);
          tbody.appendChild(tr);
        }
      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="8" class="empty-cell">Error loading transactions: ${err.message}</td></tr>`;
      }
    }

    if (prevBtn) {
      prevBtn.addEventListener("click", () => {
        if (currentPage > 1) {
          currentPage -= 1;
          loadTransactionsPage();
        }
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", () => {
        if (currentPage < totalPages) {
          currentPage += 1;
          loadTransactionsPage();
        }
      });
    }
    if (pageSizeSelect) {
      pageSizeSelect.addEventListener("change", () => {
        currentPage = 1;
        loadTransactionsPage();
      });
    }
    if (statusFilter) {
      statusFilter.addEventListener("change", () => {
        currentPage = 1;
        loadTransactionsPage();
      });
    }
    if (refreshBtn) {
      refreshBtn.addEventListener("click", loadTransactionsPage);
    }
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const payload = {
          transaction_id: document.getElementById("db-tx-id").value.trim() || null,
          username: document.getElementById("db-tx-username").value.trim(),
          transaction_type: document.getElementById("db-tx-type").value,
          amount: parseFloat(document.getElementById("db-tx-amount").value),
          latitude: parseFloat(document.getElementById("db-tx-lat").value),
          longitude: parseFloat(document.getElementById("db-tx-lon").value),
          city: document.getElementById("db-tx-city").value.trim() || null,
          status: document.getElementById("db-tx-status").value,
        };
        const resp = await fetch(`${getNormalizedBaseUrl()}/api/v1/db/transactions`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (output) output.textContent = JSON.stringify(data, null, 2);
        await loadTransactionsPage();
      });
    }
    if (btnUpdate) {
      btnUpdate.addEventListener("click", async () => {
        const txId = document.getElementById("db-tx-id").value.trim();
        if (!txId) return;
        const payload = {
          amount: parseFloat(document.getElementById("db-tx-amount").value),
          city: document.getElementById("db-tx-city").value.trim() || null,
          status: document.getElementById("db-tx-status").value,
        };
        const resp = await fetch(
          `${getNormalizedBaseUrl()}/api/v1/db/transactions/${encodeURIComponent(txId)}`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          }
        );
        const data = await resp.json();
        if (output) output.textContent = JSON.stringify(data, null, 2);
        await loadTransactionsPage();
      });
    }

    loadTransactionsPage();
  }

  function initScoresTablePage() {
    const tbody = document.getElementById("scores-table-tbody");
    if (!tbody) return;

    const pageSizeSelect = document.getElementById("scores-page-size");
    const pageInfo = document.getElementById("scores-page-info");
    const prevBtn = document.getElementById("scores-prev-btn");
    const nextBtn = document.getElementById("scores-next-btn");
    const refreshBtn = document.getElementById("btn-refresh-scores");
    const form = document.getElementById("db-score-form");
    const btnUpdate = document.getElementById("btn-update-db-score");
    const output = document.getElementById("score-crud-output");

    let currentPage = 1;
    let totalPages = 1;

    async function loadScoresPage() {
      const baseUrl = getNormalizedBaseUrl();
      const pageSize = parseInt(pageSizeSelect ? pageSizeSelect.value : "10", 10) || 10;
      try {
        const resp = await fetch(`${baseUrl}/api/v1/db/transaction-scores?page=${currentPage}&page_size=${pageSize}`);
        const data = await resp.json();
        totalPages = data.total_pages || 1;
        currentPage = data.page || 1;
        if (pageInfo) {
          pageInfo.textContent = `Page ${currentPage} of ${totalPages} (${data.total || 0} total)`;
        }
        if (prevBtn) prevBtn.disabled = currentPage <= 1;
        if (nextBtn) nextBtn.disabled = currentPage >= totalPages;

        tbody.innerHTML = "";
        const items = data.items || [];
        if (items.length === 0) {
          tbody.innerHTML = `<tr><td colspan="8" class="empty-cell">No transaction_scores rows found.</td></tr>`;
          return;
        }

        for (const item of items) {
          const tr = document.createElement("tr");
          const th = document.createElement("th");
          th.scope = "row";
          th.textContent = item.transaction_id;

          const tdAssess = document.createElement("td");
          tdAssess.textContent = item.assessment_id;
          const tdScore = document.createElement("td");
          tdScore.textContent = Number(item.score).toFixed(1);

          const tdStatus = document.createElement("td");
          const badge = document.createElement("span");
          badge.className = `badge ${statusToBadgeClass(item.approval_status)}`;
          badge.textContent = item.approval_status;
          tdStatus.appendChild(badge);

          const tdAccepted = document.createElement("td");
          tdAccepted.textContent =
            item.decision_accepted === null || item.decision_accepted === undefined
              ? "-"
              : item.decision_accepted
              ? "Yes"
              : "No";
          const tdReason = document.createElement("td");
          tdReason.textContent = item.decision_reason || item.reasoning_summary || "-";
          const tdEval = document.createElement("td");
          tdEval.textContent = item.evaluated_at || "-";

          const tdActions = document.createElement("td");
          const actionWrap = document.createElement("div");
          actionWrap.className = "row-actions";

          const btnEdit = document.createElement("button");
          btnEdit.type = "button";
          btnEdit.className = "btn btn-sm btn-outline";
          btnEdit.textContent = "Edit";
          btnEdit.addEventListener("click", () => {
            document.getElementById("db-score-tx-id").value = item.transaction_id;
            document.getElementById("db-score-value").value = item.score;
            document.getElementById("db-score-status").value = item.approval_status;
            document.getElementById("db-score-summary").value = item.reasoning_summary || "";
            document.getElementById("db-score-reason").value = item.decision_reason || "";
            if (output) output.textContent = JSON.stringify(item, null, 2);
          });

          const btnDelete = document.createElement("button");
          btnDelete.type = "button";
          btnDelete.className = "btn btn-sm btn-danger";
          btnDelete.textContent = "Delete";
          btnDelete.addEventListener("click", async () => {
            const delResp = await fetch(
              `${getNormalizedBaseUrl()}/api/v1/db/transaction-scores/${encodeURIComponent(item.transaction_id)}`,
              { method: "DELETE" }
            );
            const delData = await delResp.json();
            if (output) output.textContent = JSON.stringify(delData, null, 2);
            await loadScoresPage();
          });

          actionWrap.append(btnEdit, btnDelete);
          tdActions.appendChild(actionWrap);
          tr.append(th, tdAssess, tdScore, tdStatus, tdAccepted, tdReason, tdEval, tdActions);
          tbody.appendChild(tr);
        }
      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="8" class="empty-cell">Error loading transaction_scores: ${err.message}</td></tr>`;
      }
    }

    if (prevBtn) {
      prevBtn.addEventListener("click", () => {
        if (currentPage > 1) {
          currentPage -= 1;
          loadScoresPage();
        }
      });
    }
    if (nextBtn) {
      nextBtn.addEventListener("click", () => {
        if (currentPage < totalPages) {
          currentPage += 1;
          loadScoresPage();
        }
      });
    }
    if (pageSizeSelect) {
      pageSizeSelect.addEventListener("change", () => {
        currentPage = 1;
        loadScoresPage();
      });
    }
    if (refreshBtn) {
      refreshBtn.addEventListener("click", loadScoresPage);
    }
    if (form) {
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const payload = {
          transaction_id: document.getElementById("db-score-tx-id").value.trim(),
          score: parseFloat(document.getElementById("db-score-value").value),
          approval_status: document.getElementById("db-score-status").value,
          reasoning_summary: document.getElementById("db-score-summary").value.trim(),
          decision_reason: document.getElementById("db-score-reason").value.trim() || null,
        };
        const resp = await fetch(`${getNormalizedBaseUrl()}/api/v1/db/transaction-scores`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (output) output.textContent = JSON.stringify(data, null, 2);
        await loadScoresPage();
      });
    }
    if (btnUpdate) {
      btnUpdate.addEventListener("click", async () => {
        const txId = document.getElementById("db-score-tx-id").value.trim();
        if (!txId) return;
        const payload = {
          score: parseFloat(document.getElementById("db-score-value").value),
          approval_status: document.getElementById("db-score-status").value,
          reasoning_summary: document.getElementById("db-score-summary").value.trim(),
          decision_reason: document.getElementById("db-score-reason").value.trim() || null,
        };
        const resp = await fetch(
          `${getNormalizedBaseUrl()}/api/v1/db/transaction-scores/${encodeURIComponent(txId)}`,
          {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          }
        );
        const data = await resp.json();
        if (output) output.textContent = JSON.stringify(data, null, 2);
        await loadScoresPage();
      });
    }

    loadScoresPage();
  }

  // 9b. Vector DB (ChromaDB) Page (Page 6: vectordb.html)
  function initVectorDbPage() {
    const vectorQueryForm = document.getElementById("vector-query-form");
    if (!vectorQueryForm) return;

    const queryInput = document.getElementById("vector-query-input");
    const topKSelect = document.getElementById("vector-top-k");
    const categorySelect = document.getElementById("vector-category-filter");
    const resultsContainer = document.getElementById("vector-results-container");
    const resultsCountBadge = document.getElementById("vector-results-summary");
    const btnRefreshStats = document.getElementById("btn-refresh-vector-stats");

    const statCollectionName = document.getElementById("stat-collection-name");
    const statTotalChunks = document.getElementById("stat-total-chunks");
    const statChunks2025 = document.getElementById("stat-chunks-2025");
    const statChunks2026 = document.getElementById("stat-chunks-2026");
    const collectionBadge = document.getElementById("vector-collection-badge");

    const uploadForm = document.getElementById("vector-upload-form");
    const uploadFileInput = document.getElementById("vector-upload-file");
    const uploadTitleInput = document.getElementById("vector-upload-title");
    const uploadClauseInput = document.getElementById("vector-upload-clause-id");
    const uploadYearInput = document.getElementById("vector-upload-year");
    const uploadCategorySelect = document.getElementById("vector-upload-category");
    const uploadContentTextarea = document.getElementById("vector-upload-content");
    const uploadOutputPre = document.getElementById("vector-upload-output");

    async function loadVectorStats() {
      const baseUrl = getNormalizedBaseUrl();
      try {
        const resp = await fetch(`${baseUrl}/api/v1/vector/stats`);
        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}`);
        }
        const stats = await resp.json();
        const totalDocs = stats.total_documents ?? stats.total_chunks ?? 0;
        const byYear = stats.chunks_per_year || stats.by_policy_year || {};
        if (statCollectionName) statCollectionName.textContent = stats.collection_name || "fraud_policies";
        if (statTotalChunks) statTotalChunks.textContent = String(totalDocs);
        if (statChunks2025) statChunks2025.textContent = String(byYear["2025"] ?? 0);
        if (statChunks2026) statChunks2026.textContent = String(byYear["2026"] ?? 0);
        if (collectionBadge) {
          collectionBadge.textContent = `${stats.collection_name} (${totalDocs} chunks)`;
          collectionBadge.className = "badge badge-success";
        }
      } catch (err) {
        if (collectionBadge) {
          collectionBadge.textContent = `Stats Error: ${err.message}`;
          collectionBadge.className = "badge badge-danger";
        }
      }
    }

    function renderVectorResults(data) {
      if (!resultsContainer) return;
      resultsContainer.innerHTML = "";

      const items = (data && data.results) || [];
      if (resultsCountBadge) {
        resultsCountBadge.textContent = `${items.length} result${items.length === 1 ? "" : "s"}`;
        resultsCountBadge.className = items.length > 0 ? "badge badge-success" : "badge badge-neutral";
      }

      if (items.length === 0) {
        const emptyP = document.createElement("p");
        emptyP.className = "empty-cell";
        emptyP.textContent = "No matching policy clauses found for the selected query and metadata filters.";
        resultsContainer.appendChild(emptyP);
        return;
      }

      for (const [idx, item] of items.entries()) {
        const meta = item.metadata || {};
        const card = document.createElement("article");
        card.className = "vector-result-card";

        const header = document.createElement("div");
        header.className = "vector-result-header";

        const titleEl = document.createElement("h3");
        titleEl.className = "vector-result-title";
        titleEl.textContent = `${idx + 1}. ${item.title || meta.title || item.id}`;

        const badgesWrap = document.createElement("div");
        badgesWrap.className = "vector-result-badges";

        const simVal = typeof item.similarity_score === "number" ? item.similarity_score : (item.similarity || 0);
        const simPct = (simVal * 100).toFixed(1);
        const simBadge = document.createElement("span");
        simBadge.className = simVal >= 0.5 ? "badge badge-success" : "badge badge-warning";
        simBadge.textContent = `Similarity: ${simPct}% (dist ${Number(item.distance || 0).toFixed(3)})`;

        const yearBadge = document.createElement("span");
        const yearVal = String(item.policy_year || meta.policy_year || "N/A");
        yearBadge.className = yearVal === "2026" ? "badge badge-success" : "badge badge-neutral";
        yearBadge.textContent = `Year: ${yearVal}`;

        const clauseBadge = document.createElement("span");
        clauseBadge.className = "badge badge-neutral";
        clauseBadge.textContent = item.clause_id || meta.clause_id || item.id;

        const catBadge = document.createElement("span");
        catBadge.className = "badge badge-neutral";
        catBadge.textContent = item.category || meta.category || "GENERAL";

        badgesWrap.append(yearBadge, clauseBadge, catBadge, simBadge);
        header.append(titleEl, badgesWrap);

        const docPre = document.createElement("pre");
        docPre.className = "vector-result-text";
        docPre.textContent = item.text || item.document || "";

        const metaDetails = document.createElement("details");
        metaDetails.className = "vector-result-meta";
        const metaSummary = document.createElement("summary");
        metaSummary.textContent = `Chunk ID: ${item.id} — View Full Metadata JSON`;
        const metaCode = document.createElement("pre");
        metaCode.className = "code-output";
        metaCode.textContent = JSON.stringify(meta, null, 2);
        metaDetails.append(metaSummary, metaCode);

        card.append(header, docPre, metaDetails);
        resultsContainer.appendChild(card);
      }
    }

    async function executeVectorQuery() {
      if (!vectorQueryForm.checkValidity()) {
        const firstInvalid = vectorQueryForm.querySelector(":invalid");
        if (firstInvalid) firstInvalid.focus();
        return;
      }

      const baseUrl = getNormalizedBaseUrl();
      const queryText = (queryInput ? queryInput.value : "").trim();
      const topK = parseInt(topKSelect ? topKSelect.value : "4", 10) || 4;
      const selectedYearRadio = vectorQueryForm.querySelector('input[name="policy_year"]:checked');
      const policyYearVal = selectedYearRadio && selectedYearRadio.value ? selectedYearRadio.value : null;
      const categoryVal = categorySelect && categorySelect.value ? categorySelect.value : null;

      const payload = {
        query: queryText,
        top_k: topK,
        policy_year: policyYearVal,
        category: categoryVal,
      };

      if (resultsCountBadge) {
        resultsCountBadge.textContent = "Querying...";
        resultsCountBadge.className = "badge badge-warning";
      }

      try {
        const resp = await fetch(`${baseUrl}/api/v1/vector/query`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!resp.ok) {
          throw new Error(data.detail || `HTTP ${resp.status}`);
        }
        renderVectorResults(data);
      } catch (err) {
        if (resultsCountBadge) {
          resultsCountBadge.textContent = "Query Error";
          resultsCountBadge.className = "badge badge-danger";
        }
        if (resultsContainer) {
          resultsContainer.innerHTML = "";
          const errP = document.createElement("p");
          errP.className = "empty-cell";
          errP.textContent = `Error querying ChromaDB: ${err.message}`;
          resultsContainer.appendChild(errP);
        }
      }
    }

    vectorQueryForm.addEventListener("submit", (e) => {
      e.preventDefault();
      executeVectorQuery();
    });

    const presetButtons = document.querySelectorAll(".btn-vector-preset");
    for (const btn of presetButtons) {
      btn.addEventListener("click", () => {
        const presetQuery = btn.getAttribute("data-query");
        if (presetQuery && queryInput) {
          queryInput.value = presetQuery;
          executeVectorQuery();
        }
      });
    }

    if (btnRefreshStats) {
      btnRefreshStats.addEventListener("click", loadVectorStats);
    }

    if (uploadFileInput) {
      uploadFileInput.addEventListener("change", () => {
        const file = uploadFileInput.files && uploadFileInput.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.addEventListener("load", () => {
          if (uploadContentTextarea && typeof reader.result === "string") {
            uploadContentTextarea.value = reader.result;
          }
          if (uploadTitleInput && !uploadTitleInput.value.trim()) {
            uploadTitleInput.value = file.name.replace(/\.(md|txt)$/i, "");
          }
        });
        reader.readAsText(file);
      });
    }

    if (uploadForm) {
      uploadForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (!uploadForm.checkValidity()) {
          const firstInvalid = uploadForm.querySelector(":invalid");
          if (firstInvalid) firstInvalid.focus();
          return;
        }

        const baseUrl = getNormalizedBaseUrl();
        const file = uploadFileInput && uploadFileInput.files && uploadFileInput.files[0];
        const payload = {
          content: (uploadContentTextarea ? uploadContentTextarea.value : "").trim(),
          title: (uploadTitleInput ? uploadTitleInput.value : "").trim() || "Custom Policy Clause",
          clause_id: (uploadClauseInput && uploadClauseInput.value.trim()) || null,
          policy_year: (uploadYearInput ? uploadYearInput.value : "2026").trim() || "2026",
          category: (uploadCategorySelect ? uploadCategorySelect.value : "GENERAL") || "GENERAL",
          filename: file ? file.name : null,
        };

        if (uploadOutputPre) {
          uploadOutputPre.textContent = "Uploading and embedding policy document into ChromaDB...";
        }

        try {
          const resp = await fetch(`${baseUrl}/api/v1/vector/documents`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          const data = await resp.json();
          if (uploadOutputPre) {
            uploadOutputPre.textContent = JSON.stringify(data, null, 2);
          }
          if (resp.ok) {
            await loadVectorStats();
          }
        } catch (err) {
          if (uploadOutputPre) {
            uploadOutputPre.textContent = JSON.stringify({ error: err.message }, null, 2);
          }
        }
      });
    }

    loadVectorStats();
    executeVectorQuery();
  }

  // 10. Initialize Event Listeners & Defaults
  function init() {
    UserInvalidFallback.init(document);

    const savedUrl = localStorage.getItem(STORAGE_KEY_GATEWAY_URL);
    if (savedUrl && gatewayUrlInput) {
      gatewayUrlInput.value = savedUrl;
    }

    const txDatetimeInput = document.getElementById("tx-datetime");
    if (txDatetimeInput) {
      txDatetimeInput.value = new Date().toISOString();
    }

    updateDerivedEndpointsDisplay();
    syncPaymentRailVisibility();

    if (gatewayUrlInput) {
      gatewayUrlInput.addEventListener("input", updateDerivedEndpointsDisplay);
    }
    if (wsUsernameFilterInput) {
      wsUsernameFilterInput.addEventListener("input", updateDerivedEndpointsDisplay);
    }
    if (btnCheckHealth) {
      btnCheckHealth.addEventListener("click", checkGatewayHealth);
    }

    // Keep Gateway URL synchronized across open browser tabs (Submit tab <-> Queue tab)
    window.addEventListener("storage", (event) => {
      if (event.key === STORAGE_KEY_GATEWAY_URL && event.newValue && gatewayUrlInput) {
        gatewayUrlInput.value = event.newValue;
        updateDerivedEndpointsDisplay();
      }
    });

    // Page 1 (Submit Transaction) bindings
    if (txTypeSelect) {
      txTypeSelect.addEventListener("change", syncPaymentRailVisibility);
    }
    if (btnPresetCard) {
      btnPresetCard.addEventListener("click", loadCardPreset);
    }
    if (btnPresetAch) {
      btnPresetAch.addEventListener("click", loadAchPreset);
    }
    const btnImportRandomTest = document.getElementById("btn-import-random-test");
    const btnGenerateGoodTx = document.getElementById("btn-generate-good-tx");
    const btnGenerateFraudTx = document.getElementById("btn-generate-fraud-tx");
    if (btnImportRandomTest) {
      btnImportRandomTest.addEventListener("click", importRandomTestTransaction);
    }
    if (btnGenerateGoodTx) {
      btnGenerateGoodTx.addEventListener("click", generateGoodTransaction);
    }
    if (btnGenerateFraudTx) {
      btnGenerateFraudTx.addEventListener("click", generateFraudTransaction);
    }
    if (txForm) {
      txForm.addEventListener("submit", handleTransactionSubmit);
    }

    // Page 2 (Decision Queue) bindings
    if (btnConnectWs) {
      btnConnectWs.addEventListener("click", connectWebSocket);
    }
    if (btnDisconnectWs) {
      btnDisconnectWs.addEventListener("click", disconnectWebSocket);
    }
    if (btnClearEvents && wsEventsTbody) {
      btnClearEvents.addEventListener("click", () => {
        receivedEventsMap.clear();
        wsEventsTbody.innerHTML = `
          <tr id="ws-empty-row">
            <td colspan="6" class="empty-cell">
              Waiting for WebSocket events... Connect to the Gateway and submit a transaction from the Submit page.
            </td>
          </tr>
        `;
        if (wsEventInspector) {
          wsEventInspector.textContent = "Select or receive a WebSocket event to inspect its full payload.";
        }
      });
    }
    if (btnAcceptTx) {
      btnAcceptTx.addEventListener("click", () => {
        submitDecision(decisionTxIdInput.value, true, decisionReasonInput.value);
      });
    }
    if (btnRejectTx) {
      btnRejectTx.addEventListener("click", () => {
        submitDecision(decisionTxIdInput.value, false, decisionReasonInput.value);
      });
    }

    // Auto-connect WebSocket when opening the Decision Queue page (queue.html) or Submit page (index.html)
    if (wsEventsTbody || agentTimelineList) {
      connectWebSocket();
    }

    // Initialize RDBMS table pages & Vector DB page if active
    initUsersTablePage();
    initTransactionsTablePage();
    initScoresTablePage();
    initVectorDbPage();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
