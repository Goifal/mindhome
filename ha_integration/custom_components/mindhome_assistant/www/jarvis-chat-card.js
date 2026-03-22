/**
 * Jarvis Chat Card — Custom Lovelace Card fuer Home Assistant
 *
 * Ermoeglicht Chat mit J.A.R.V.I.S. direkt im HA Dashboard.
 * Features: Textnachrichten, Bild-/Datei-Upload, Verlauf, Typing-Indicator.
 *
 * Kommuniziert mit dem MindHome Add-on (PC 1) ueber dessen Chat-API.
 *
 * Konfiguration:
 *   type: custom:jarvis-chat-card
 *   url: http://192.168.1.100:8099    # MindHome Add-on URL
 *   title: Jarvis                      # Optional (default: "Jarvis")
 *   height: 500                        # Optional, Card-Hoehe in px (default: 500)
 *   person: Max                        # Optional, Benutzername
 *   show_actions: true                 # Optional, zeige ausgefuehrte Aktionen (default: true)
 */

const CARD_VERSION = "1.0.0";

class JarvisChatCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._messages = [];
    this._isLoading = false;
    this._isConnected = false;
    this._connectionChecked = false;
    this._pollingTimer = null;
    this._lastMessageCount = 0;
  }

  static getConfigElement() {
    return document.createElement("jarvis-chat-card-editor");
  }

  static getStubConfig() {
    return {
      url: "http://192.168.1.100:8099",
      title: "Jarvis",
      height: 500,
      person: "",
      show_actions: true,
    };
  }

  setConfig(config) {
    if (!config.url) {
      throw new Error("'url' muss konfiguriert werden (MindHome Add-on URL)");
    }
    this._config = {
      title: "Jarvis",
      height: 500,
      person: "",
      show_actions: true,
      ...config,
    };
    this._config.url = this._config.url.replace(/\/+$/, "");
    this._render();
    this._loadHistory();
    this._checkConnection();
  }

  set hass(hass) {
    this._hass = hass;
  }

  getCardSize() {
    return Math.ceil(this._config.height / 50);
  }

  connectedCallback() {
    this._startPolling();
  }

  disconnectedCallback() {
    this._stopPolling();
  }

  // ------------------------------------------------------------------
  // Polling fuer proaktive Nachrichten / neue Antworten
  // ------------------------------------------------------------------

  _startPolling() {
    this._stopPolling();
    this._pollingTimer = setInterval(() => this._pollNewMessages(), 5000);
  }

  _stopPolling() {
    if (this._pollingTimer) {
      clearInterval(this._pollingTimer);
      this._pollingTimer = null;
    }
  }

  async _pollNewMessages() {
    if (this._isLoading) return;
    try {
      const resp = await fetch(`${this._config.url}/api/chat/history?limit=1`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.total > this._lastMessageCount && this._lastMessageCount > 0) {
        await this._loadHistory();
      }
    } catch (_) {
      // Silently ignore polling errors
    }
  }

  // ------------------------------------------------------------------
  // API Calls
  // ------------------------------------------------------------------

  async _checkConnection() {
    try {
      const resp = await fetch(`${this._config.url}/api/chat/status`, {
        signal: AbortSignal.timeout(5000),
      });
      if (resp.ok) {
        const data = await resp.json();
        this._isConnected = data.connected === true;
      } else {
        this._isConnected = false;
      }
    } catch (_) {
      this._isConnected = false;
    }
    this._connectionChecked = true;
    this._updateStatus();
  }

  async _loadHistory() {
    try {
      const resp = await fetch(`${this._config.url}/api/chat/history?limit=50`);
      if (!resp.ok) return;
      const data = await resp.json();
      this._messages = data.messages || [];
      this._lastMessageCount = data.total || 0;
      this._renderMessages();
      this._scrollToBottom();
    } catch (_) {
      // History load failed silently
    }
  }

  async _sendMessage(text) {
    if (!text.trim() || this._isLoading) return;

    this._addMessage({ role: "user", text, timestamp: new Date().toISOString() });
    this._isLoading = true;
    this._updateInput();
    this._showTyping();

    try {
      const payload = { text };
      if (this._config.person) {
        payload.person = this._config.person;
      }

      const resp = await fetch(`${this._config.url}/api/chat/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      this._hideTyping();

      if (resp.ok) {
        const data = await resp.json();
        this._addMessage({
          role: "assistant",
          text: data.response || "...",
          actions: data.actions || [],
          model_used: data.model_used || "",
          timestamp: data.timestamp || new Date().toISOString(),
        });
        this._lastMessageCount += 2;
      } else {
        const errData = await resp.json().catch(() => ({}));
        this._addMessage({
          role: "error",
          text: errData.error || `Fehler ${resp.status}`,
          timestamp: new Date().toISOString(),
        });
      }
    } catch (err) {
      this._hideTyping();
      this._addMessage({
        role: "error",
        text: "Verbindung fehlgeschlagen. Ist das Add-on erreichbar?",
        timestamp: new Date().toISOString(),
      });
    }

    this._isLoading = false;
    this._updateInput();
  }

  async _uploadFile(file, caption) {
    if (!file || this._isLoading) return;

    const isImage = file.type.startsWith("image/");
    const previewUrl = isImage ? URL.createObjectURL(file) : null;

    this._addMessage({
      role: "user",
      text: caption || file.name,
      timestamp: new Date().toISOString(),
      file: { name: file.name, type: file.type, preview: previewUrl },
    });

    this._isLoading = true;
    this._updateInput();
    this._showTyping();

    try {
      const formData = new FormData();
      formData.append("file", file);
      if (caption) formData.append("caption", caption);
      if (this._config.person) formData.append("person", this._config.person);

      const resp = await fetch(`${this._config.url}/api/chat/upload`, {
        method: "POST",
        body: formData,
      });

      this._hideTyping();

      if (resp.ok) {
        const data = await resp.json();
        this._addMessage({
          role: "assistant",
          text: data.response || "Datei verarbeitet.",
          actions: data.actions || [],
          timestamp: data.timestamp || new Date().toISOString(),
        });
        this._lastMessageCount += 2;
      } else {
        const errData = await resp.json().catch(() => ({}));
        this._addMessage({
          role: "error",
          text: errData.error || `Upload fehlgeschlagen (${resp.status})`,
          timestamp: new Date().toISOString(),
        });
      }
    } catch (err) {
      this._hideTyping();
      this._addMessage({
        role: "error",
        text: "Upload fehlgeschlagen. Ist das Add-on erreichbar?",
        timestamp: new Date().toISOString(),
      });
    }

    this._isLoading = false;
    this._updateInput();
  }

  // ------------------------------------------------------------------
  // Message handling
  // ------------------------------------------------------------------

  _addMessage(msg) {
    this._messages.push(msg);
    this._renderMessages();
    this._scrollToBottom();
  }

  _scrollToBottom() {
    requestAnimationFrame(() => {
      const container = this.shadowRoot.querySelector(".messages");
      if (container) {
        container.scrollTop = container.scrollHeight;
      }
    });
  }

  // ------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------

  _render() {
    const height = this._config.height;
    const title = this._config.title;

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          --jarvis-bg: var(--card-background-color, #1c1c1e);
          --jarvis-text: var(--primary-text-color, #e5e5e7);
          --jarvis-text-secondary: var(--secondary-text-color, #8e8e93);
          --jarvis-user-bg: var(--primary-color, #0a84ff);
          --jarvis-user-text: #ffffff;
          --jarvis-assistant-bg: var(--secondary-background-color, #2c2c2e);
          --jarvis-assistant-text: var(--primary-text-color, #e5e5e7);
          --jarvis-error-bg: #3a1c1c;
          --jarvis-error-text: #ff6b6b;
          --jarvis-border: var(--divider-color, #38383a);
          --jarvis-input-bg: var(--input-fill-color, #2c2c2e);
          --jarvis-radius: 18px;
        }
        ha-card {
          overflow: hidden;
          background: var(--jarvis-bg);
        }
        .header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 16px;
          border-bottom: 1px solid var(--jarvis-border);
        }
        .header-left {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .avatar {
          width: 36px;
          height: 36px;
          border-radius: 50%;
          background: linear-gradient(135deg, #0a84ff, #5e5ce6);
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 16px;
          color: white;
          font-weight: bold;
          flex-shrink: 0;
        }
        .header-info h3 {
          margin: 0;
          font-size: 15px;
          font-weight: 600;
          color: var(--jarvis-text);
        }
        .status {
          font-size: 12px;
          color: var(--jarvis-text-secondary);
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .status-dot {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          background: #48484a;
          transition: background 0.3s;
        }
        .status-dot.online { background: #30d158; }
        .status-dot.offline { background: #ff453a; }
        .messages {
          height: ${height}px;
          overflow-y: auto;
          padding: 12px 16px;
          scroll-behavior: smooth;
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .messages::-webkit-scrollbar {
          width: 4px;
        }
        .messages::-webkit-scrollbar-thumb {
          background: var(--jarvis-border);
          border-radius: 2px;
        }
        .msg-group {
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .msg-group.user { align-items: flex-end; }
        .msg-group.assistant { align-items: flex-start; }
        .msg-group.error { align-items: center; }
        .bubble {
          max-width: 82%;
          padding: 9px 14px;
          border-radius: var(--jarvis-radius);
          font-size: 14px;
          line-height: 1.45;
          word-wrap: break-word;
          white-space: pre-wrap;
        }
        .msg-group.user .bubble {
          background: var(--jarvis-user-bg);
          color: var(--jarvis-user-text);
          border-bottom-right-radius: 6px;
        }
        .msg-group.assistant .bubble {
          background: var(--jarvis-assistant-bg);
          color: var(--jarvis-assistant-text);
          border-bottom-left-radius: 6px;
        }
        .msg-group.error .bubble {
          background: var(--jarvis-error-bg);
          color: var(--jarvis-error-text);
          border-radius: 12px;
          font-size: 13px;
          text-align: center;
        }
        .msg-time {
          font-size: 11px;
          color: var(--jarvis-text-secondary);
          padding: 0 4px;
          margin-top: 1px;
        }
        .msg-actions {
          font-size: 12px;
          color: var(--jarvis-text-secondary);
          padding: 4px 14px 0;
          border-top: 1px solid var(--jarvis-border);
          margin-top: 4px;
        }
        .msg-actions summary {
          cursor: pointer;
          user-select: none;
        }
        .msg-actions .action-item {
          padding: 2px 0;
          font-family: monospace;
          font-size: 11px;
        }
        .file-preview {
          max-width: 240px;
          max-height: 180px;
          border-radius: 12px;
          margin-bottom: 4px;
          object-fit: cover;
        }
        .file-badge {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 4px 10px;
          background: rgba(255,255,255,0.1);
          border-radius: 8px;
          font-size: 12px;
          margin-bottom: 4px;
        }
        .typing {
          display: none;
          align-items: flex-start;
          gap: 2px;
          padding: 4px 0;
        }
        .typing.active { display: flex; }
        .typing .bubble {
          background: var(--jarvis-assistant-bg);
          padding: 12px 18px;
          border-bottom-left-radius: 6px;
        }
        .typing-dots {
          display: flex;
          gap: 4px;
          align-items: center;
        }
        .typing-dots span {
          width: 7px;
          height: 7px;
          border-radius: 50%;
          background: var(--jarvis-text-secondary);
          animation: typing-bounce 1.4s ease-in-out infinite;
        }
        .typing-dots span:nth-child(2) { animation-delay: 0.2s; }
        .typing-dots span:nth-child(3) { animation-delay: 0.4s; }
        @keyframes typing-bounce {
          0%, 60%, 100% { transform: translateY(0); opacity: 0.4; }
          30% { transform: translateY(-4px); opacity: 1; }
        }
        .input-area {
          display: flex;
          align-items: flex-end;
          gap: 8px;
          padding: 10px 12px;
          border-top: 1px solid var(--jarvis-border);
          background: var(--jarvis-bg);
        }
        .input-area textarea {
          flex: 1;
          background: var(--jarvis-input-bg);
          border: 1px solid var(--jarvis-border);
          border-radius: 20px;
          padding: 9px 14px;
          color: var(--jarvis-text);
          font-size: 14px;
          font-family: inherit;
          resize: none;
          outline: none;
          max-height: 120px;
          min-height: 20px;
          line-height: 1.4;
          transition: border-color 0.2s;
        }
        .input-area textarea:focus {
          border-color: var(--jarvis-user-bg);
        }
        .input-area textarea::placeholder {
          color: var(--jarvis-text-secondary);
        }
        .btn {
          width: 38px;
          height: 38px;
          border-radius: 50%;
          border: none;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
          transition: opacity 0.2s, transform 0.1s;
          padding: 0;
        }
        .btn:active { transform: scale(0.9); }
        .btn:disabled {
          opacity: 0.4;
          cursor: not-allowed;
          transform: none;
        }
        .btn-send {
          background: var(--jarvis-user-bg);
          color: white;
        }
        .btn-upload {
          background: transparent;
          color: var(--jarvis-text-secondary);
        }
        .btn-upload:hover { color: var(--jarvis-text); }
        .btn svg {
          width: 20px;
          height: 20px;
          fill: currentColor;
        }
        .empty-state {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          height: 100%;
          color: var(--jarvis-text-secondary);
          gap: 8px;
          padding: 20px;
          text-align: center;
        }
        .empty-state .avatar-large {
          width: 56px;
          height: 56px;
          border-radius: 50%;
          background: linear-gradient(135deg, #0a84ff, #5e5ce6);
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 24px;
          color: white;
          font-weight: bold;
          margin-bottom: 4px;
        }
        .empty-state p {
          margin: 0;
          font-size: 14px;
        }
        input[type="file"] { display: none; }
      </style>

      <ha-card>
        <div class="header">
          <div class="header-left">
            <div class="avatar">J</div>
            <div class="header-info">
              <h3>${this._escapeHtml(title)}</h3>
              <div class="status">
                <span class="status-dot" id="statusDot"></span>
                <span id="statusText">Verbinde...</span>
              </div>
            </div>
          </div>
        </div>

        <div class="messages" id="messages">
          <div class="empty-state" id="emptyState">
            <div class="avatar-large">J</div>
            <p><strong>Hallo, Sir.</strong></p>
            <p>Wie kann ich behilflich sein?</p>
          </div>
        </div>

        <div class="typing" id="typing">
          <div class="bubble">
            <div class="typing-dots">
              <span></span><span></span><span></span>
            </div>
          </div>
        </div>

        <div class="input-area">
          <button class="btn btn-upload" id="btnUpload" title="Datei senden">
            <svg viewBox="0 0 24 24"><path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5a2.5 2.5 0 0 1 5 0v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5a2.5 2.5 0 0 0 5 0V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/></svg>
          </button>
          <textarea id="input" rows="1" placeholder="Nachricht an Jarvis..." autocomplete="off"></textarea>
          <button class="btn btn-send" id="btnSend" title="Senden">
            <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
          </button>
          <input type="file" id="fileInput" accept="image/*,video/*,audio/*,.pdf,.txt,.csv,.json,.xml,.doc,.docx,.xls,.xlsx,.pptx" />
        </div>
      </ha-card>
    `;

    this._bindEvents();
  }

  _bindEvents() {
    const input = this.shadowRoot.getElementById("input");
    const btnSend = this.shadowRoot.getElementById("btnSend");
    const btnUpload = this.shadowRoot.getElementById("btnUpload");
    const fileInput = this.shadowRoot.getElementById("fileInput");

    // Send on Enter (Shift+Enter for newline)
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        this._sendMessage(input.value);
        input.value = "";
        input.style.height = "auto";
      }
    });

    // Auto-resize textarea
    input.addEventListener("input", () => {
      input.style.height = "auto";
      input.style.height = Math.min(input.scrollHeight, 120) + "px";
    });

    // Send button
    btnSend.addEventListener("click", () => {
      this._sendMessage(input.value);
      input.value = "";
      input.style.height = "auto";
    });

    // Upload button
    btnUpload.addEventListener("click", () => {
      fileInput.click();
    });

    // File selected
    fileInput.addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (file) {
        this._uploadFile(file, "");
        fileInput.value = "";
      }
    });
  }

  _renderMessages() {
    const container = this.shadowRoot.getElementById("messages");
    const emptyState = this.shadowRoot.getElementById("emptyState");
    if (!container) return;

    if (this._messages.length === 0) {
      if (emptyState) emptyState.style.display = "flex";
      return;
    }

    if (emptyState) emptyState.style.display = "none";

    // Only render new messages (avoid full re-render)
    const existingBubbles = container.querySelectorAll(".msg-group");
    const startIdx = existingBubbles.length;

    for (let i = startIdx; i < this._messages.length; i++) {
      const msg = this._messages[i];
      container.appendChild(this._createMessageElement(msg));
    }
  }

  _createMessageElement(msg) {
    const group = document.createElement("div");
    group.className = `msg-group ${msg.role}`;

    // File preview (images)
    if (msg.file) {
      if (msg.file.preview || (msg.file.type && msg.file.type.startsWith("image/"))) {
        const img = document.createElement("img");
        img.className = "file-preview";
        img.src = msg.file.preview || msg.file.url || "";
        img.alt = msg.file.name || "Bild";
        img.loading = "lazy";
        group.appendChild(img);
      } else {
        const badge = document.createElement("div");
        badge.className = "file-badge";
        badge.textContent = msg.file.name || "Datei";
        group.appendChild(badge);
      }
    }

    // Message bubble
    if (msg.text) {
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      bubble.textContent = msg.text;
      group.appendChild(bubble);
    }

    // Actions (collapsible)
    if (this._config.show_actions && msg.actions && msg.actions.length > 0) {
      const actionsEl = document.createElement("details");
      actionsEl.className = "msg-actions";
      const summary = document.createElement("summary");
      summary.textContent = `${msg.actions.length} Aktion${msg.actions.length > 1 ? "en" : ""} ausgefuehrt`;
      actionsEl.appendChild(summary);

      for (const action of msg.actions) {
        const item = document.createElement("div");
        item.className = "action-item";
        const func = action.function || action.action || "?";
        const result = action.result?.message || action.result || "";
        item.textContent = `${func}${result ? " → " + result : ""}`;
        actionsEl.appendChild(item);
      }

      group.appendChild(actionsEl);
    }

    // Timestamp
    if (msg.timestamp) {
      const timeEl = document.createElement("div");
      timeEl.className = "msg-time";
      timeEl.textContent = this._formatTime(msg.timestamp);
      group.appendChild(timeEl);
    }

    return group;
  }

  _showTyping() {
    const el = this.shadowRoot.getElementById("typing");
    if (el) el.classList.add("active");
    this._scrollToBottom();
  }

  _hideTyping() {
    const el = this.shadowRoot.getElementById("typing");
    if (el) el.classList.remove("active");
  }

  _updateStatus() {
    const dot = this.shadowRoot.getElementById("statusDot");
    const text = this.shadowRoot.getElementById("statusText");
    if (!dot || !text) return;

    if (!this._connectionChecked) {
      text.textContent = "Verbinde...";
      return;
    }
    if (this._isConnected) {
      dot.className = "status-dot online";
      text.textContent = "Online";
    } else {
      dot.className = "status-dot offline";
      text.textContent = "Nicht erreichbar";
    }
  }

  _updateInput() {
    const input = this.shadowRoot.getElementById("input");
    const btnSend = this.shadowRoot.getElementById("btnSend");
    const btnUpload = this.shadowRoot.getElementById("btnUpload");
    if (input) input.disabled = this._isLoading;
    if (btnSend) btnSend.disabled = this._isLoading;
    if (btnUpload) btnUpload.disabled = this._isLoading;

    // Refocus input after sending
    if (!this._isLoading && input) {
      input.focus();
    }
  }

  // ------------------------------------------------------------------
  // Helpers
  // ------------------------------------------------------------------

  _formatTime(isoString) {
    try {
      const d = new Date(isoString);
      return d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
    } catch (_) {
      return "";
    }
  }

  _escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }
}

// ------------------------------------------------------------------
// Card Editor (Visual Editor in HA UI)
// ------------------------------------------------------------------

class JarvisChatCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
  }

  setConfig(config) {
    this._config = { ...config };
    this._render();
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>
        .editor {
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        label {
          display: flex;
          flex-direction: column;
          gap: 4px;
          font-size: 14px;
          color: var(--primary-text-color);
        }
        input, select {
          padding: 8px 12px;
          border: 1px solid var(--divider-color, #ccc);
          border-radius: 8px;
          background: var(--input-fill-color, #fff);
          color: var(--primary-text-color);
          font-size: 14px;
        }
        .hint {
          font-size: 12px;
          color: var(--secondary-text-color);
        }
      </style>
      <div class="editor">
        <label>
          MindHome Add-on URL *
          <input type="text" id="url" value="${this._config.url || ""}" placeholder="http://192.168.1.100:8099" />
          <span class="hint">Die URL deines MindHome Add-ons (nicht der Assistant-Server)</span>
        </label>
        <label>
          Titel
          <input type="text" id="title" value="${this._config.title || "Jarvis"}" placeholder="Jarvis" />
        </label>
        <label>
          Hoehe (px)
          <input type="number" id="height" value="${this._config.height || 500}" min="200" max="1200" />
        </label>
        <label>
          Person (Benutzername)
          <input type="text" id="person" value="${this._config.person || ""}" placeholder="Optional" />
          <span class="hint">Wird an Jarvis gesendet fuer persoenliche Antworten</span>
        </label>
      </div>
    `;

    for (const field of ["url", "title", "height", "person"]) {
      const el = this.shadowRoot.getElementById(field);
      if (el) {
        el.addEventListener("change", (e) => {
          let value = e.target.value;
          if (field === "height") value = parseInt(value, 10) || 500;
          this._config = { ...this._config, [field]: value };
          this.dispatchEvent(new CustomEvent("config-changed", {
            detail: { config: this._config },
            bubbles: true,
            composed: true,
          }));
        });
      }
    }
  }
}

// ------------------------------------------------------------------
// Register
// ------------------------------------------------------------------

customElements.define("jarvis-chat-card", JarvisChatCard);
customElements.define("jarvis-chat-card-editor", JarvisChatCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "jarvis-chat-card",
  name: "Jarvis Chat",
  description: "Chat-Widget fuer J.A.R.V.I.S. — MindHome KI-Assistent",
  preview: true,
  documentationURL: "https://github.com/Goifal/mindhome",
});

console.info(
  `%c JARVIS-CHAT-CARD %c v${CARD_VERSION} `,
  "color: white; background: #0a84ff; font-weight: bold; padding: 2px 6px; border-radius: 4px 0 0 4px;",
  "color: #0a84ff; background: #e8e8ed; font-weight: bold; padding: 2px 6px; border-radius: 0 4px 4px 0;"
);
