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

    // Initialize RDBMS table pages if active
    initUsersTablePage();
    initTransactionsTablePage();
    initScoresTablePage();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
