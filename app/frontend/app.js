document.addEventListener("DOMContentLoaded", () => {
  let sessionId = null;
  let challengeId = null;
  let conversationLocked = false;

  const messages = document.getElementById("messages");
  const actions = document.getElementById("actions");
  const trace = document.getElementById("trace");
  const debugPanel = document.getElementById("debug-panel");
  const dialog = document.getElementById("auth-dialog");
  const handoffDialog = document.getElementById("handoff-dialog");
  const services = document.getElementById("services");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const sendButton = document.getElementById("send-message");
  const authEmailStep = document.getElementById("auth-step-email");
  const authCodeStep = document.getElementById("auth-step-code");
  const authEmail = document.getElementById("auth-email");
  const authCode = document.getElementById("auth-code");
  const authMessage = document.getElementById("auth-message");
  const authEmailError = document.getElementById("auth-email-error");
  const authCodeError = document.getElementById("auth-code-error");
  const sessionStateLabel = document.getElementById("session-state-label");

  const debugEnabled = new URLSearchParams(window.location.search).get("debug") === "1";
  if (debugEnabled) {
    debugPanel.hidden = false;
  }

  try {
    sessionId = localStorage.getItem("bookly_session_id");
  } catch (error) {
    console.warn("Bookly: localStorage unavailable; session will be in-memory only.", error);
  }

  function appendSafeFormattedText(container, text) {
    const parts = String(text).split(/(\*\*[^*]+\*\*|\*[^*\n]+\*)/g);

    for (const part of parts) {
      if (!part) continue;

      if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
        const strong = document.createElement("strong");
        strong.textContent = part.slice(2, -2);
        container.appendChild(strong);
        continue;
      }

      if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
        const emphasis = document.createElement("em");
        emphasis.textContent = part.slice(1, -1);
        container.appendChild(emphasis);
        continue;
      }

      container.appendChild(document.createTextNode(part));
    }
  }

  function scrollConversation() {
    messages.scrollTop = messages.scrollHeight;
  }

  function clearWelcome() {
    document.getElementById("welcome")?.remove();
  }

  function renderWelcome() {
    messages.innerHTML = "";

    const welcome = document.createElement("section");
    welcome.id = "welcome";
    welcome.className = "welcome";

    const mark = document.createElement("div");
    mark.className = "welcome-mark";
    mark.innerHTML = `
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5.5 5.5c2.5 0 4.4.7 6.5 2.4v11c-2.1-1.7-4-2.4-6.5-2.4z"></path>
        <path d="M18.5 5.5c-2.5 0-4.4.7-6.5 2.4v11c2.1-1.7 4-2.4 6.5-2.4z"></path>
      </svg>
    `;
    welcome.appendChild(mark);

    const eyebrow = document.createElement("div");
    eyebrow.className = "welcome-eyebrow";
    eyebrow.textContent = "Bookly concierge";
    welcome.appendChild(eyebrow);

    const title = document.createElement("h1");
    title.textContent = "What can I help you with today?";
    welcome.appendChild(title);

    const copy = document.createElement("p");
    copy.textContent =
      "Ask about an order, delivery, return, account question, or anything about shopping with Bookly.";
    welcome.appendChild(copy);

    const suggestions = document.createElement("div");
    suggestions.className = "suggestions";

    const prompts = [
      "Where are my orders?",
      "Can I return a book?",
      "How long does delivery take to Finland?",
      "Can I speak to a human?"
    ];

    for (const prompt of prompts) {
      const button = document.createElement("button");
      button.className = "suggestion-chip";
      button.type = "button";
      button.textContent = prompt;
      button.addEventListener("click", () => sendMessage(prompt));
      suggestions.appendChild(button);
    }

    welcome.appendChild(suggestions);
    messages.appendChild(welcome);
  }

  function addMessage(role, text, sources = []) {
    clearWelcome();

    if (role === "assistant") {
      text = String(text).replaceAll("—", "-").replaceAll("–", "-");
    }

    const wrap = document.createElement("div");
    wrap.className = `message-wrap ${role}`;

    const el = document.createElement("div");
    el.className = `message ${role}`;
    appendSafeFormattedText(el, text);
    wrap.appendChild(el);

    if (role === "assistant" && sources.length) {
      const sourceWrap = document.createElement("div");
      sourceWrap.className = "sources";
      for (const source of sources) {
        const chip = document.createElement("div");
        chip.className = "source";
        chip.textContent = source.title;
        sourceWrap.appendChild(chip);
      }
      wrap.appendChild(sourceWrap);
    }

    messages.appendChild(wrap);
    scrollConversation();
  }

  function showThinking(label = "Bookly is thinking") {
    hideThinking();
    clearWelcome();

    const wrap = document.createElement("div");
    wrap.id = "thinking-indicator";
    wrap.className = "message-wrap assistant thinking-wrap";
    wrap.setAttribute("role", "status");
    wrap.setAttribute("aria-live", "polite");

    const bubble = document.createElement("div");
    bubble.className = "message assistant thinking";

    const labelEl = document.createElement("span");
    labelEl.className = "thinking-label";
    labelEl.textContent = label;
    bubble.appendChild(labelEl);

    const dots = document.createElement("span");
    dots.className = "thinking-dots";
    dots.setAttribute("aria-hidden", "true");
    for (let i = 0; i < 3; i += 1) {
      dots.appendChild(document.createElement("span"));
    }
    bubble.appendChild(dots);

    wrap.appendChild(bubble);
    messages.appendChild(wrap);
    scrollConversation();
  }

  function hideThinking() {
    document.getElementById("thinking-indicator")?.remove();
  }

  function addTrace(events = []) {
    if (!debugEnabled) return;

    for (const event of events) {
      const el = document.createElement("div");
      el.className = "trace-event";

      const title = document.createElement("strong");
      title.textContent = event.type;
      el.appendChild(title);
      el.appendChild(document.createElement("br"));
      el.appendChild(document.createTextNode(event.message));

      if (event.data && Object.keys(event.data).length) {
        const data = document.createElement("div");
        data.className = "trace-data";
        data.textContent = JSON.stringify(event.data, null, 2);
        el.appendChild(data);
      }

      trace.prepend(el);
    }
  }

  function rememberSession(id) {
    sessionId = id;
    try {
      localStorage.setItem("bookly_session_id", id);
    } catch (error) {
      console.warn("Bookly: could not persist session ID.", error);
    }
  }

  function showRequestFailure(context, error) {
    console.error(`Bookly ${context} failed`, error);
    addMessage(
      "assistant",
      "I couldn't complete that request right now. No action was taken. Please try again."
    );
    addTrace([
      {
        type: "ui_error",
        message: `Frontend request failed during ${context}.`,
        data: {error: String(error)}
      }
    ]);
  }

  async function apiFetch(url, options = {}) {
    const response = await fetch(url, options);
    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json")
      ? await response.json()
      : {detail: await response.text()};

    if (!response.ok) {
      const detail = typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail || data);
      throw new Error(`${response.status} ${detail}`);
    }
    return data;
  }

  function formatDate(value) {
    if (!value) return "Not available";
    const date = new Date(`${value}T00:00:00Z`);
    return new Intl.DateTimeFormat("en-GB", {
      day: "numeric",
      month: "short",
      timeZone: "UTC"
    }).format(date);
  }

  function statusMeta(status) {
    const normalized = String(status || "").toLowerCase();

    if (normalized === "delivered") {
      return {label: "Delivered", className: "status-delivered"};
    }
    if (normalized.includes("delayed")) {
      return {label: "Delayed", className: "status-delayed"};
    }
    if (normalized.includes("transit")) {
      return {label: "In transit", className: "status-in-transit"};
    }
    return {
      label: String(status || "Unknown").replaceAll("_", " "),
      className: "status-neutral"
    };
  }

  function renderOrdersTable(action) {
    const orders = action.payload?.orders || [];
    if (!orders.length) return;

    const wrap = document.createElement("div");
    wrap.className = "rich-card-wrap";

    const card = document.createElement("section");
    card.className = "order-card";

    const header = document.createElement("div");
    header.className = "order-card-header";

    const heading = document.createElement("div");
    const kicker = document.createElement("div");
    kicker.className = "card-kicker";
    kicker.textContent = "Your account";
    const title = document.createElement("h3");
    title.textContent = "Recent orders";
    heading.append(kicker, title);

    const count = document.createElement("div");
    count.className = "card-count";
    count.textContent = `${orders.length} ${orders.length === 1 ? "order" : "orders"}`;

    header.append(heading, count);
    card.appendChild(header);

    const table = document.createElement("table");
    table.className = "order-table";
    table.innerHTML = `
      <thead>
        <tr>
          <th>Order</th>
          <th>Items</th>
          <th>Status</th>
          <th>Key date</th>
        </tr>
      </thead>
    `;

    const tbody = document.createElement("tbody");

    for (const order of orders) {
      const row = document.createElement("tr");

      const orderCell = document.createElement("td");
      const orderId = document.createElement("div");
      orderId.className = "order-id";
      orderId.textContent = order.order_id;
      orderCell.appendChild(orderId);

      const itemsCell = document.createElement("td");
      const itemTitles = (order.items || []).map(item => item.title);
      const primaryItems = document.createElement("div");
      primaryItems.className = "order-items";
      primaryItems.textContent = itemTitles.join(", ");
      itemsCell.appendChild(primaryItems);
      if ((order.items || []).length > 1) {
        const secondary = document.createElement("div");
        secondary.className = "order-items-secondary";
        secondary.textContent = `${order.items.length} items`;
        itemsCell.appendChild(secondary);
      }

      const statusCell = document.createElement("td");
      const status = statusMeta(order.status);
      const pill = document.createElement("span");
      pill.className = `status-pill ${status.className}`;
      pill.textContent = status.label;
      statusCell.appendChild(pill);

      const dateCell = document.createElement("td");
      dateCell.className = "order-date";
      if (order.delivered_at) {
        dateCell.textContent = `Delivered ${formatDate(order.delivered_at)}`;
      } else if (order.expected_delivery) {
        const prefix = String(order.status || "").includes("delayed") ? "Promised" : "Expected";
        dateCell.textContent = `${prefix} ${formatDate(order.expected_delivery)}`;
      } else {
        dateCell.textContent = "No date available";
      }

      row.append(orderCell, itemsCell, statusCell, dateCell);
      tbody.appendChild(row);
    }

    table.appendChild(tbody);
    card.appendChild(table);
    wrap.appendChild(card);
    messages.appendChild(wrap);
    scrollConversation();
  }

  function humanize(value) {
    const labels = {
      original_payment_method: "Original payment method",
      after_item_received: "After Bookly receives the item",
      immediate_after_approval: "Immediately after approval",
      prepaid_label: "Prepaid return label",
      not_required: "No return required"
    };

    if (labels[value]) return labels[value];

    const text = String(value || "").replaceAll("_", " ");
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  async function confirmAction(action, card) {
    const actionId = action.payload.action_id;
    const buttons = card.querySelectorAll("button");
    buttons.forEach(button => { button.disabled = true; });
    showThinking("Confirming your return");

    try {
      const data = await apiFetch(
        `/api/actions/${encodeURIComponent(actionId)}/confirm`,
        {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({session_id: sessionId})
        }
      );
      actions.innerHTML = "";
      addMessage("assistant", data.message);
      addTrace(data.trace || []);
    } catch (error) {
      buttons.forEach(button => { button.disabled = false; });
      showRequestFailure("action confirmation", error);
    } finally {
      hideThinking();
    }
  }

  function renderReturnCard(action) {
    const card = document.createElement("section");
    card.className = "action-card";

    const header = document.createElement("div");
    header.className = "action-card-header";

    const heading = document.createElement("div");
    const kicker = document.createElement("div");
    kicker.className = "card-kicker";
    kicker.textContent = "Return details";
    const title = document.createElement("h3");
    title.textContent = action.payload.item_title || "Confirm return";
    heading.append(kicker, title);

    const ready = document.createElement("span");
    ready.className = "action-ready";
    ready.textContent = "Ready to confirm";

    header.append(heading, ready);
    card.appendChild(header);

    const grid = document.createElement("div");
    grid.className = "action-grid";

    const rows = [
      ["Refund", `£${Number(action.payload.refund_amount).toFixed(2)}`],
      ["Refund method", humanize(action.payload.refund_method)],
      ["Refund timing", humanize(action.payload.refund_timing)],
      ["Return shipping", humanize(action.payload.return_shipping)]
    ];

    for (const [label, value] of rows) {
      const row = document.createElement("div");
      row.className = "action-row";

      const labelEl = document.createElement("div");
      labelEl.className = "action-label";
      labelEl.textContent = label;

      const valueEl = document.createElement("div");
      valueEl.className = "action-value";
      valueEl.textContent = value;

      row.append(labelEl, valueEl);
      grid.appendChild(row);
    }

    card.appendChild(grid);

    const footer = document.createElement("div");
    footer.className = "action-footer";

    const confirm = document.createElement("button");
    confirm.className = "button button-primary";
    confirm.type = "button";
    confirm.textContent = "Confirm return";
    confirm.addEventListener("click", () => confirmAction(action, card));

    const cancel = document.createElement("button");
    cancel.className = "button button-ghost";
    cancel.type = "button";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", () => {
      actions.innerHTML = "";
      addMessage("assistant", "No problem. I haven't created the return.");
    });

    footer.append(confirm, cancel);
    card.appendChild(footer);
    actions.appendChild(card);
  }

  function resetAuthDialog() {
    challengeId = null;
    authEmailStep.hidden = false;
    authCodeStep.hidden = true;
    authEmailError.hidden = true;
    authCodeError.hidden = true;
    authEmailError.textContent = "";
    authCodeError.textContent = "";
    authCode.value = "";
    authMessage.textContent = "We sent a six-digit verification code.";
  }

  function openAuthDialog() {
    resetAuthDialog();
    if (!dialog.open) {
      dialog.showModal();
    }
    window.setTimeout(() => authEmail.focus(), 50);
  }

  function closeAuthDialog() {
    if (dialog.open) dialog.close();
  }

  function enterHumanHandoff() {
    conversationLocked = true;
    actions.innerHTML = "";
    chatInput.disabled = true;
    sendButton.disabled = true;
    chatInput.placeholder = "Conversation handed to human support";

    if (!handoffDialog.open) {
      handoffDialog.showModal();
    }
  }

  async function startNewDemoChat() {
    const previousSessionId = sessionId;

    if (previousSessionId) {
      try {
        await apiFetch(`/api/session/${encodeURIComponent(previousSessionId)}`, {
          method: "DELETE"
        });
      } catch (error) {
        console.warn("Bookly: server-side session reset failed; resetting local demo state.", error);
      }
    }

    sessionId = null;
    challengeId = null;
    conversationLocked = false;
    sessionStateLabel.textContent = "AI Concierge";

    try {
      localStorage.removeItem("bookly_session_id");
    } catch (error) {
      console.warn("Bookly: could not clear persisted session ID.", error);
    }

    hideThinking();
    actions.innerHTML = "";
    trace.innerHTML = "";
    renderWelcome();

    closeAuthDialog();
    if (handoffDialog.open) handoffDialog.close();

    authEmail.value = "";
    resetAuthDialog();

    chatInput.disabled = false;
    sendButton.disabled = false;
    chatInput.placeholder = "Ask about orders, delivery, returns, or Bookly policies";
    chatInput.value = "";
    chatInput.focus();
  }

  function renderActions(uiActions = []) {
    const replacesPendingAction = uiActions.some(
      action => action.type === "confirm_action" || action.type === "human_handoff"
    );
    if (replacesPendingAction) {
      actions.innerHTML = "";
    }

    for (const action of uiActions) {
      if (action.type === "human_handoff") {
        enterHumanHandoff();
        continue;
      }

      if (action.type === "verify_email") {
        openAuthDialog();
        continue;
      }

      if (action.type === "orders_table") {
        renderOrdersTable(action);
        continue;
      }

      if (action.type === "confirm_action") {
        renderReturnCard(action);
      }
    }
  }

  function renderAgentResponse(data) {
    addMessage("assistant", data.message, data.sources || []);
    addTrace(data.trace || []);
    renderActions(data.ui_actions || []);
  }

  async function sendMessage(text) {
    if (conversationLocked) return;

    addMessage("user", text);
    sendButton.disabled = true;
    chatInput.disabled = true;
    showThinking("Bookly is checking that for you");

    try {
      const data = await apiFetch("/api/chat", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({session_id: sessionId, message: text})
      });
      rememberSession(data.session_id);
      renderAgentResponse(data);
    } catch (error) {
      showRequestFailure("chat", error);
    } finally {
      hideThinking();
      if (!conversationLocked) {
        sendButton.disabled = false;
        chatInput.disabled = false;
        chatInput.focus();
      }
    }
  }

  chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = chatInput.value.trim();
    if (!value || conversationLocked) return;
    chatInput.value = "";
    await sendMessage(value);
  });

  document.getElementById("new-demo-chat").addEventListener("click", startNewDemoChat);
  document.getElementById("handoff-new-demo").addEventListener("click", startNewDemoChat);
  document.getElementById("auth-close").addEventListener("click", closeAuthDialog);
  document.getElementById("auth-back").addEventListener("click", () => {
    authCodeStep.hidden = true;
    authEmailStep.hidden = false;
    authCodeError.hidden = true;
    window.setTimeout(() => authEmail.focus(), 50);
  });

  handoffDialog.addEventListener("cancel", event => event.preventDefault());

  for (const button of document.querySelectorAll(".demo-user")) {
    button.addEventListener("click", () => {
      authEmail.value = button.dataset.email;
      authEmailError.hidden = true;
      authEmail.focus();
    });
  }

  document.getElementById("send-code").addEventListener("click", async () => {
    const email = authEmail.value.trim();
    const button = document.getElementById("send-code");

    authEmailError.hidden = true;
    if (!email || !authEmail.checkValidity()) {
      authEmailError.textContent = "Enter a valid email address to continue.";
      authEmailError.hidden = false;
      authEmail.focus();
      return;
    }

    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = "Sending code...";

    try {
      const data = await apiFetch("/api/auth/start", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({session_id: sessionId, email})
      });

      rememberSession(data.session_id);
      challengeId = data.challenge_id;
      authMessage.textContent = `We sent a six-digit code to ${email}.`;
      authEmailStep.hidden = true;
      authCodeStep.hidden = false;
      authCode.value = "";
      window.setTimeout(() => {
        authCode.focus();
        authCode.select();
      }, 50);
    } catch (error) {
      console.error("Bookly verification start failed", error);
      authEmailError.textContent =
        "We couldn't send a verification code right now. Please try again.";
      authEmailError.hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = originalLabel;
    }
  });

  document.getElementById("verify-code").addEventListener("click", async () => {
    const code = authCode.value.trim();
    const verifyButton = document.getElementById("verify-code");
    const originalLabel = verifyButton.textContent;

    authCodeError.hidden = true;
    if (!challengeId || code.length !== 6) {
      authCodeError.textContent = "Enter the six-digit verification code.";
      authCodeError.hidden = false;
      authCode.focus();
      return;
    }

    verifyButton.disabled = true;
    verifyButton.textContent = "Verifying...";

    try {
      const data = await apiFetch("/api/auth/verify", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          session_id: sessionId,
          challenge_id: challengeId,
          code
        })
      });

      closeAuthDialog();
      sessionStateLabel.textContent = "Verified";
      addTrace([
        {
          type: "verification_completed",
          message: "Identity verified the customer; the scoped token remains server-side.",
          data: {scopes: data.scopes}
        }
      ]);

      if (data.pending_request) {
        chatInput.disabled = true;
        sendButton.disabled = true;
        showThinking("Verified. Picking up where we left off");

        try {
          const resumed = await apiFetch("/api/auth/resume", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({session_id: sessionId})
          });

          addTrace([
            {
              type: "pending_intent_resumed",
              message: resumed.resumed_response
                ? "The application resumed the original customer request automatically."
                : "No pending request to resume.",
              data: {}
            }
          ]);

          if (resumed.resumed_response) {
            renderAgentResponse(resumed.resumed_response);
          }
        } catch (error) {
          showRequestFailure("request resume", error);
        } finally {
          hideThinking();
          if (!conversationLocked) {
            chatInput.disabled = false;
            sendButton.disabled = false;
            chatInput.focus();
          }
        }
      }
    } catch (error) {
      console.error("Bookly code verification failed", error);
      authCodeError.textContent =
        "That code couldn't be verified. Check it and try again.";
      authCodeError.hidden = false;
    } finally {
      verifyButton.disabled = false;
      verifyButton.textContent = originalLabel;
    }
  });

  async function loadStatus() {
    if (!debugEnabled) return;

    try {
      const data = await apiFetch("/api/services");
      const infrastructureOk = data.identity && data.commerce && data.knowledge;
      const model = data.model ? "model ready" : "model key missing";
      services.textContent =
        `${infrastructureOk ? "Services online" : "Service issue"} · ${model}`;
    } catch (error) {
      console.error("Bookly service status failed", error);
      services.textContent = "Status unavailable";
      addTrace([
        {
          type: "status_error",
          message: "Could not load service health.",
          data: {error: String(error)}
        }
      ]);
    }
  }

  renderWelcome();
  loadStatus();
});
