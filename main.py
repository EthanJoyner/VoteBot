from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from threading import Lock
from time import monotonic

from flask import Flask, render_template_string
from flask_sock import Sock

app = Flask(__name__)
sock = Sock(app)

ALLOWED_DIRECTIONS = {"forward", "backward", "left", "right"}
COOLDOWN_SECONDS = 1.0
last_action = "None"
last_action_at = "Never"
active_ws_connections = 0
state_lock = Lock()

PAGE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>VoteBot Controls</title>
  <style>
    :root {
      --bg-a: #f9f7f1;
      --bg-b: #e8f1ea;
      --ink: #223127;
      --muted: #516357;
      --accent: #1f8a4c;
      --accent-2: #1a6c3d;
      --card: rgba(255, 255, 255, 0.9);
      --ring: rgba(31, 138, 76, 0.35);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: "Segoe UI", "Trebuchet MS", Tahoma, sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 15% 10%, rgba(31, 138, 76, 0.16), transparent 40%),
        radial-gradient(circle at 85% 90%, rgba(250, 154, 27, 0.20), transparent 45%),
        linear-gradient(135deg, var(--bg-a), var(--bg-b));
      padding: 24px;
    }

    .panel {
      width: min(560px, 100%);
      background: var(--card);
      border: 1px solid rgba(255, 255, 255, 0.75);
      border-radius: 24px;
      box-shadow: 0 16px 40px rgba(35, 55, 42, 0.15);
      backdrop-filter: blur(6px);
      padding: 24px;
      animation: rise 420ms ease-out;
    }

    h1 {
      margin: 0 0 8px;
      font-size: clamp(1.5rem, 4vw, 2rem);
      letter-spacing: 0.02em;
    }

    .status {
      margin: 0 0 18px;
      color: var(--muted);
      font-size: 0.98rem;
    }

    .status strong { color: var(--ink); }

    .controls {
      display: grid;
      grid-template-columns: repeat(3, minmax(84px, 1fr));
      gap: 14px;
      align-items: center;
      justify-items: center;
      margin-top: 12px;
    }

    .ghost {
      visibility: hidden;
      width: 100%;
      height: 52px;
    }

    button {
      width: 100%;
      height: 52px;
      border: 0;
      border-radius: 14px;
      cursor: pointer;
      font-size: 1rem;
      font-weight: 700;
      letter-spacing: 0.01em;
      color: #ffffff;
      background: linear-gradient(180deg, var(--accent), var(--accent-2));
      box-shadow: 0 10px 18px rgba(31, 138, 76, 0.25);
      transition: transform 120ms ease, box-shadow 120ms ease, filter 120ms ease;
      outline: none;
    }

    button:hover {
      transform: translateY(-2px);
      box-shadow: 0 14px 24px rgba(31, 138, 76, 0.30);
      filter: saturate(1.05);
    }

    button:active {
      transform: translateY(0);
      box-shadow: 0 6px 12px rgba(31, 138, 76, 0.20);
    }

    button:focus-visible {
      box-shadow: 0 0 0 4px var(--ring), 0 10px 18px rgba(31, 138, 76, 0.25);
    }

    .hint {
      margin-top: 14px;
      color: var(--muted);
      font-size: 0.9rem;
    }

    .status-chip {
      margin-top: 10px;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(31, 138, 76, 0.12);
      color: #1d5b38;
      font-size: 0.88rem;
      font-weight: 600;
    }

    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #2a9d59;
      box-shadow: 0 0 0 4px rgba(42, 157, 89, 0.16);
    }

    @keyframes rise {
      from { opacity: 0; transform: translateY(12px) scale(0.99); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }

    @media (max-width: 430px) {
      .panel { padding: 18px; border-radius: 18px; }
      .controls { gap: 10px; }
      button { height: 48px; font-size: 0.95rem; }
    }
  </style>
</head>
<body>
  <main class="panel">
    <h1>VoteBot Direction Controls</h1>
    <p class="status">
      Last action: <strong>{{ last_action }}</strong>
      <br>
      Time: <strong>{{ last_action_at }}</strong>
      <br>
      Total concurrent WS connections: <strong id="ws-count">{{ active_ws_connections }}</strong>
    </p>

    <section class="controls" aria-label="Directional controls">
      <div class="ghost" aria-hidden="true"></div>
      <button type="button" data-direction="forward">Forward</button>
      <div class="ghost" aria-hidden="true"></div>

      <button type="button" data-direction="left">Left</button>
      <div class="ghost" aria-hidden="true"></div>
      <button type="button" data-direction="right">Right</button>

      <div class="ghost" aria-hidden="true"></div>
      <button type="button" data-direction="backward">Backward</button>
      <div class="ghost" aria-hidden="true"></div>
    </section>

    <p class="hint">Each button sends a direction command over WebSocket.</p>
    <div class="status-chip" id="ws-status"><span class="dot" aria-hidden="true"></span><span>Connecting...</span></div>
  </main>

  <script>
    const statusText = document.querySelector("#ws-status span:last-child");
    const wsProtocol = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${wsProtocol}://${window.location.host}/ws`);

    function setStatus(message) {
      statusText.textContent = message;
    }

    ws.addEventListener("open", () => setStatus("Connected"));
    ws.addEventListener("close", () => setStatus("Disconnected"));
    ws.addEventListener("error", () => setStatus("Connection error"));

    ws.addEventListener("message", (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.ok) {
          const actionEl = document.querySelector(".status strong:first-of-type");
          const timeEl = document.querySelector(".status strong:nth-of-type(2)");
          const countEl = document.querySelector("#ws-count");
          actionEl.textContent = payload.last_action;
          timeEl.textContent = payload.last_action_at;
          if (typeof payload.active_ws_connections === "number") {
            countEl.textContent = payload.active_ws_connections;
          }
        } else if (payload.error) {
          setStatus(payload.error);
        }
      } catch {
        // Ignore malformed payloads from development changes.
      }
    });

    setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "status" }));
      }
    }, 1000);

    document.querySelectorAll("button[data-direction]").forEach((button) => {
      button.addEventListener("click", () => {
        if (ws.readyState !== WebSocket.OPEN) {
          setStatus("Not connected");
          return;
        }

        button.disabled = true;
        setTimeout(() => {
          button.disabled = false;
        }, 1000);

        ws.send(JSON.stringify({ direction: button.dataset.direction }));
      });
    });
  </script>
</body>
</html>
"""


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


@app.get("/")
def index() -> str:
    return render_template_string(
        PAGE_TEMPLATE,
        last_action=last_action,
        last_action_at=last_action_at,
    active_ws_connections=active_ws_connections,
    )


def _apply_direction(direction: str) -> tuple[bool, str]:
    global last_action, last_action_at

    normalized = direction.lower()
    if normalized not in ALLOWED_DIRECTIONS:
        return False, "Invalid direction"

    with state_lock:
        last_action = normalized.capitalize()
        last_action_at = _stamp()

    print(f"Move command: {normalized}")
    return True, ""


def _state_payload() -> dict[str, object]:
    with state_lock:
        return {
            "ok": True,
            "last_action": last_action,
            "last_action_at": last_action_at,
            "active_ws_connections": active_ws_connections,
        }


@sock.route("/ws")
def ws_controls(ws) -> None:
  global active_ws_connections
  cooldown_by_direction: dict[str, float] = {}

  with state_lock:
    active_ws_connections += 1
  ws.send(json.dumps(_state_payload()))

  try:
    while True:
      message = ws.receive()
      if message is None:
        break

      try:
        payload = json.loads(message)
      except json.JSONDecodeError:
        ws.send(json.dumps({"ok": False, "error": "Invalid JSON"}))
        continue

      if payload.get("type") == "status":
        ws.send(json.dumps(_state_payload()))
        continue

      direction = str(payload.get("direction", ""))
      if direction in ALLOWED_DIRECTIONS:
        now = monotonic()
        last_press = cooldown_by_direction.get(direction, 0.0)
        elapsed = now - last_press
        if elapsed < COOLDOWN_SECONDS:
          ws.send(
            json.dumps(
              {
                "ok": False,
                "error": (
                  f"{direction.capitalize()} is on cooldown. "
                  f"Try again in {COOLDOWN_SECONDS - elapsed:.2f}s"
                ),
              }
            )
          )
          continue

      ok, error = _apply_direction(direction)
      if not ok:
        ws.send(json.dumps({"ok": False, "error": error}))
        continue

      cooldown_by_direction[direction] = monotonic()
      ws.send(json.dumps(_state_payload()))
  finally:
    with state_lock:
      active_ws_connections = max(0, active_ws_connections - 1)


if __name__ == "__main__":
    host = os.getenv("VOTEBOT_HOST", "0.0.0.0")
    port = int(os.getenv("VOTEBOT_PORT", "5000"))
    app.run(host=host, port=port, debug=False)
