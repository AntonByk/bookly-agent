document.addEventListener("DOMContentLoaded", () => {
  let sessionId = null;
  let challengeId = null;

  const messages = document.getElementById("messages");
  const actions = document.getElementById("actions");
  const trace = document.getElementById("trace");
  const dialog = document.getElementById("auth-dialog");
  const services = document.getElementById("services");
  const chatForm = document.getElementById("chat-form");
  const chatInput = document.getElementById("chat-input");
  const sendButton = document.getElementById("send-message");

  try {
    sessionId = localStorage.getItem("bookly_session_id");
  } catch (error) {
    console.warn("Bookly: localStorage unavailable; session will be in-memory only.", error);
  }

  function addMessage(role, text, sources = []) {
    const wrap = document.createElement("div");
    wrap.className = `message-wrap ${role}`;

    const el = document.createElement("div");
    el.className = `message ${role}`;
    el.textContent = text;
    wrap.appendChild(el);

    if (role === "assistant" && sources.length) {
      const sourceWrap = document.createElement("div");
      sourceWrap.className = "sources";
      for (const source of sources) {
        const chip = document.createElement("div");
        chip.className = "source";
        chip.textContent = `Bookly Help Centre · ${source.title}`;
        sourceWrap.appendChild(chip);
      }
      wrap.appendChild(sourceWrap);
    }

    messages.appendChild(wrap);
    messages.scrollTop = messages.scrollHeight;
  }

  function showThinking(label = "Bookly is thinking") {
    hideThinking();

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
    messages.scrollTop = messages.scrollHeight;
  }

  function hideThinking() {
    document.getElementById("thinking-indicator")?.remove();
  }

  function addTrace(events = []) {
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
      "Something went wrong while contacting Bookly. Check the terminal or browser console and try again."
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

  async function confirmAction(action) {
    const actionId = action.payload.action_id;
    showThinking("Processing your return");
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
      showRequestFailure("action confirmation", error);
    } finally {
      hideThinking();
    }
  }

  function renderActions(uiActions = []) {
    actions.innerHTML = "";

    for (const action of uiActions) {
      if (action.type === "verify_email") {
        const button = document.createElement("button");
        button.textContent = action.label;
        button.onclick = () => dialog.showModal();
        actions.appendChild(button);
        continue;
      }

      if (action.type === "confirm_action") {
        const card = document.createElement("div");
        card.className = "action-card";

        const title = document.createElement("strong");
        title.textContent = "Confirm return";
        card.appendChild(title);

        const details = document.createElement("dl");
        const rows = [
          ["Item", action.payload.item_title],
          ["Refund", `£${Number(action.payload.refund_amount).toFixed(2)}`],
          ["Refund method", String(action.payload.refund_method).replaceAll("_", " ")],
          ["Refund timing", String(action.payload.refund_timing).replaceAll("_", " ")],
          ["Return shipping", String(action.payload.return_shipping).replaceAll("_", " ")],
        ];
        for (const [label, value] of rows) {
          const dt = document.createElement("dt");
          dt.textContent = label;
          const dd = document.createElement("dd");
          dd.textContent = value;
          details.appendChild(dt);
          details.appendChild(dd);
        }
        card.appendChild(details);

        const confirm = document.createElement("button");
        confirm.textContent = action.label;
        confirm.onclick = () => confirmAction(action);
        card.appendChild(confirm);

        const cancel = document.createElement("button");
        cancel.className = "secondary";
        cancel.style.marginLeft = "8px";
        cancel.textContent = "Cancel";
        cancel.onclick = () => { actions.innerHTML = ""; };
        card.appendChild(cancel);

        actions.appendChild(card);
      }
    }
  }

  function renderAgentResponse(data) {
    addMessage("assistant", data.message, data.sources || []);
    addTrace(data.trace || []);
    renderActions(data.ui_actions || []);
  }

  async function sendMessage(text) {
    addMessage("user", text);
    sendButton.disabled = true;
    chatInput.disabled = true;
    showThinking();

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
      sendButton.disabled = false;
      chatInput.disabled = false;
      chatInput.focus();
    }
  }

  chatForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = chatInput.value.trim();
    if (!value) return;
    chatInput.value = "";
    await sendMessage(value);
  });

  document.getElementById("send-code").onclick = async () => {
    const email = document.getElementById("auth-email").value;
    try {
      const data = await apiFetch("/api/auth/start", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({session_id: sessionId, email})
      });
      challengeId = data.challenge_id;
      document.getElementById("auth-message").textContent =
        `${data.message}${data.demo_code ? ` Demo code: ${data.demo_code}` : ""}`;
      document.getElementById("code-area").hidden = false;
    } catch (error) {
      document.getElementById("auth-message").textContent = String(error);
    }
  };

  document.getElementById("verify-code").onclick = async () => {
    const code = document.getElementById("auth-code").value;
    const verifyButton = document.getElementById("verify-code");
    const originalLabel = verifyButton.textContent;
    verifyButton.disabled = true;
    verifyButton.textContent = "Verifying…";
    try {
      const data = await apiFetch("/api/auth/verify", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({session_id: sessionId, challenge_id: challengeId, code})
      });

      dialog.close();
      addTrace([
        {
          type: "verification_completed",
          message: "Identity verified the customer; the scoped token remains server-side.",
          data: {scopes: data.scopes}
        },
        {
          type: "pending_intent_resumed",
          message: data.resumed_response
            ? "The application resumed the original customer request automatically."
            : "No pending request to resume.",
          data: {}
        }
      ]);

      if (data.resumed_response) {
        renderAgentResponse(data.resumed_response);
      }
    } catch (error) {
      document.getElementById("auth-message").textContent = String(error);
    } finally {
      verifyButton.disabled = false;
      verifyButton.textContent = originalLabel;
    }
  };

  async function loadStatus() {
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

  services.textContent = "UI ready · checking services…";
  loadStatus();
});
