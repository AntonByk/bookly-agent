let sessionId = localStorage.getItem("bookly_session_id");
let challengeId = null;

const messages = document.getElementById("messages");
const actions = document.getElementById("actions");
const trace = document.getElementById("trace");
const dialog = document.getElementById("auth-dialog");

function addMessage(role, text) {
  const el = document.createElement("div");
  el.className = `message ${role}`;
  el.textContent = text;
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
}

function addTrace(events = []) {
  for (const event of events) {
    const el = document.createElement("div");
    el.className = "trace-event";
    el.innerHTML = `<strong>${event.type}</strong><br>${event.message}`;
    trace.prepend(el);
  }
}

function renderActions(uiActions = []) {
  actions.innerHTML = "";
  for (const action of uiActions) {
    const button = document.createElement("button");
    button.textContent = action.label;
    button.onclick = () => {
      if (action.type === "verify_email") dialog.showModal();
    };
    actions.appendChild(button);
  }
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
  addMessage("assistant", data.message);
  addTrace(data.trace);
  renderActions(data.ui_actions);
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
  document.getElementById("auth-message").textContent = data.message;
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
    {type: "verification_completed", message: "Identity verified the customer; token stored server-side."},
    {type: "pending_intent_resumed", message: data.pending_intent ? `Ready to resume: ${data.pending_intent}` : "No pending request."}
  ]);
  addMessage("assistant", "Thanks — you're verified. The next milestone will automatically resume your pending request here.");
  actions.innerHTML = "";
};

async function loadStatus() {
  const response = await fetch("/api/services");
  const data = await response.json();
  const ok = Object.values(data).every(Boolean);
  document.getElementById("services").textContent = ok ? "All systems online" : "Service issue";
}

loadStatus();
