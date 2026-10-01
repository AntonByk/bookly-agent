let sessionId = localStorage.getItem("bookly_session_id");
let challengeId = null;

const messages = document.getElementById("messages");
const actions = document.getElementById("actions");
const trace = document.getElementById("trace");
const dialog = document.getElementById("auth-dialog");

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

async function confirmAction(action) {
  const actionId = action.payload.action_id;
  const response = await fetch(`/api/actions/${encodeURIComponent(actionId)}/confirm`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({session_id: sessionId})
  });
  const data = await response.json();

  if (!response.ok) {
    addMessage("assistant", `I couldn't complete that action: ${data.detail || "unknown error"}`);
    return;
  }

  actions.innerHTML = "";
  addMessage("assistant", data.message);
  addTrace(data.trace || []);
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
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({session_id: sessionId, message: text})
  });
  const data = await response.json();
  sessionId = data.session_id;
  localStorage.setItem("bookly_session_id", sessionId);
  renderAgentResponse(data);
}

document.getElementById("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.getElementById("chat-input");
  const value = input.value.trim();
  if (!value) return;
  input.value = "";
  await sendMessage(value);
});

document.getElementById("send-code").onclick = async () => {
  const email = document.getElementById("auth-email").value;
  const response = await fetch("/api/auth/start", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({session_id: sessionId, email})
  });
  const data = await response.json();
  challengeId = data.challenge_id;
  document.getElementById("auth-message").textContent =
    `${data.message}${data.demo_code ? ` Demo code: ${data.demo_code}` : ""}`;
  document.getElementById("code-area").hidden = false;
};

document.getElementById("verify-code").onclick = async () => {
  const code = document.getElementById("auth-code").value;
  const response = await fetch("/api/auth/verify", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({session_id: sessionId, challenge_id: challengeId, code})
  });
  const data = await response.json();

  if (!response.ok) {
    document.getElementById("auth-message").textContent = data.detail || "Verification failed";
    return;
  }

  dialog.close();
  addTrace([
    {
      type: "verification_completed",
      message: "Identity verified the customer; the scoped token remains server-side.",
      data: {scopes: data.scopes}
    },
    {
      type: "pending_intent_resumed",
      message: data.resumed_response ? "The application resumed the original customer request automatically." : "No pending request to resume.",
      data: {}
    }
  ]);

  if (data.resumed_response) {
    renderAgentResponse(data.resumed_response);
  }
});

async function loadStatus() {
  const response = await fetch("/api/services");
  const data = await response.json();
  const infrastructureOk = data.identity && data.commerce && data.knowledge;
  const model = data.model ? "model ready" : "model key missing";
  document.getElementById("services").textContent =
    `${infrastructureOk ? "Services online" : "Service issue"} · ${model}`;
}

loadStatus();
