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
  }

  // 3. WebSocket Connection Management (Page 2: queue.html)
  function setWsBadgeState(stateText, badgeClass) {
    if (!wsStatusBadge) return;
    wsStatusBadge.textContent = stateText;
    wsStatusBadge.className = `badge ${badgeClass}`;
  }

  function connectWebSocket() {
    if (!wsEventsTbody) return;

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

  function handleIncomingWsEvent(eventData) {
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

  // 9. Initialize Event Listeners & Defaults
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

    // Auto-connect WebSocket when opening the Decision Queue page (queue.html)
    if (wsEventsTbody) {
      connectWebSocket();
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
