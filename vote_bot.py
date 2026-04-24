from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from time import monotonic, time
from typing import Dict, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import uvicorn

# =========================
# Configuration
# =========================

ALLOWED_DIRECTIONS = {"forward", "backward", "left", "right"}
COOLDOWN_SECONDS = 1.0
VOTE_INTERVAL_SECONDS = 5.0

# =========================
# Shared async state
# =========================

@asynccontextmanager
async def lifespan(_: FastAPI):
    worker_task = asyncio.create_task(vote_interval_worker())
    try:
        yield
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan)

state_lock = asyncio.Lock()

connected_clients: Set[WebSocket] = set()
robot_clients: Set[WebSocket] = set()
interval_votes: Dict[str, int] = {d: 0 for d in ALLOWED_DIRECTIONS}

last_action = "None"
last_action_at = "Never"
interval_result = "Waiting for first interval..."
next_tally_at_epoch = time() + VOTE_INTERVAL_SECONDS

# =========================
# Time helpers (unchanged)
# =========================

def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> datetime:
    first_day = datetime(year, month, 1, tzinfo=timezone.utc)
    days_until_weekday = (weekday - first_day.weekday()) % 7
    day = 1 + days_until_weekday + (n - 1) * 7
    return datetime(year, month, day, tzinfo=timezone.utc)

def _is_us_eastern_dst(now_utc: datetime) -> bool:
    year = now_utc.year
    march_second_sunday = _nth_weekday_of_month(year, 3, 6, 2)
    dst_start_utc = march_second_sunday.replace(hour=7)
    nov_first_sunday = _nth_weekday_of_month(year, 11, 6, 1)
    dst_end_utc = nov_first_sunday.replace(hour=6)
    return dst_start_utc <= now_utc < dst_end_utc

def _stamp() -> str:
    now_utc = datetime.now(timezone.utc)
    if _is_us_eastern_dst(now_utc):
        edt = timezone(timedelta(hours=-4), name="EDT")
        return now_utc.astimezone(edt).strftime("%Y-%m-%d %H:%M:%S EDT")

    est = timezone(timedelta(hours=-5), name="EST")
    return now_utc.astimezone(est).strftime("%Y-%m-%d %H:%M:%S EST")

# =========================
# State helpers
# =========================

async def state_payload() -> dict:
    async with state_lock:
        return {
            "ok": True,
            "last_action": last_action,
            "last_action_at": last_action_at,
            "active_ws_connections": len(connected_clients),
            "active_robot_connections": len(robot_clients),
            "interval_result": interval_result,
            "next_tally_at_epoch_ms": int(next_tally_at_epoch * 1000),
        }

async def _broadcast_to_clients(payload: dict, clients: Set[WebSocket]) -> None:
    """Optimized async fan-out broadcast for an arbitrary client set."""
    serialized = json.dumps(payload)

    async with state_lock:
        targets = list(clients)

    if not targets:
        return

    coros = []
    dead = []

    for ws in targets:
        coros.append(_safe_send(ws, serialized, dead))

    await asyncio.gather(*coros, return_exceptions=True)

    if dead:
        async with state_lock:
            for ws in dead:
                clients.discard(ws)

async def broadcast_state() -> None:
    await _broadcast_to_clients(await state_payload(), connected_clients)

async def send_robot_command(direction: str, duration_ms: int = 500) -> bool:
    payload = {
        "type": "robot_command",
        "direction": direction,
        "duration_ms": duration_ms,
        "issued_at": _stamp(),
    }

    async with state_lock:
        has_robot_clients = bool(robot_clients)

    if not has_robot_clients:
        return False

    await _broadcast_to_clients(payload, robot_clients)
    return True

async def _safe_send(ws: WebSocket, data: str, dead: list) -> None:
    try:
        await ws.send_text(data)
    except Exception:
        dead.append(ws)

# =========================
# Vote evaluation
# =========================

async def evaluate_interval_votes() -> None:
    global interval_result, next_tally_at_epoch

    async with state_lock:
        snapshot = dict(interval_votes)
        for d in interval_votes:
            interval_votes[d] = 0
        next_tally_at_epoch = time() + VOTE_INTERVAL_SECONDS

    highest = max(snapshot.values(), default=0)
    winning_direction: Optional[str] = None

    if highest == 0:
        interval_result = "No votes this interval. No action can be taken."
    else:
        winners = [k for k, v in snapshot.items() if v == highest]
        if len(winners) > 1:
            interval_result = f"Tie at {highest} vote(s): {', '.join(sorted(winners))}."
        else:
            winning_direction = winners[0]
            interval_result = f"{winning_direction.capitalize()} won with {highest} vote(s)."

    if winning_direction is not None:
        sent = await send_robot_command(winning_direction)
        if sent:
            interval_result += " Command sent to robot."
        else:
            interval_result += " No robot connected; command not delivered."

    await broadcast_state()

async def vote_interval_worker() -> None:
    while True:
        await asyncio.sleep(VOTE_INTERVAL_SECONDS)
        await evaluate_interval_votes()

# =========================
# WebSocket endpoint
# =========================

@app.websocket("/ws")
async def ws_controls(ws: WebSocket):
    global last_action, last_action_at

    await ws.accept()
    cooldown: Dict[str, float] = {}

    async with state_lock:
        connected_clients.add(ws)

    await ws.send_text(json.dumps(await state_payload()))

    try:
        while True:
            message = await ws.receive_text()
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"ok": False, "error": "Invalid JSON"}))
                continue

            if payload.get("type") == "status":
                await ws.send_text(json.dumps(await state_payload()))
                continue

            direction = payload.get("direction")
            if direction not in ALLOWED_DIRECTIONS:
                await ws.send_text(json.dumps({"ok": False, "error": "Invalid direction"}))
                continue

            now = monotonic()
            last_press = cooldown.get(direction, 0.0)
            if now - last_press < COOLDOWN_SECONDS:
                await ws.send_text(json.dumps({"ok": False, "error": "Cooldown"}))
                continue

            async with state_lock:
                last_action = direction.capitalize()
                last_action_at = _stamp()
                interval_votes[direction] += 1

            cooldown[direction] = now

            await broadcast_state()

    except WebSocketDisconnect:
        pass
    finally:
        async with state_lock:
            connected_clients.discard(ws)


@app.websocket("/ws/robot")
async def ws_robot(ws: WebSocket):
    await ws.accept()

    async with state_lock:
        robot_clients.add(ws)

    await ws.send_text(json.dumps({"ok": True, "type": "robot_connected"}))
    await ws.send_text(json.dumps(await state_payload()))

    await broadcast_state()

    try:
        while True:
            message = await ws.receive_text()
            try:
                payload = json.loads(message)
            except json.JSONDecodeError:
                continue

            if payload.get("type") == "status":
                await ws.send_text(json.dumps(await state_payload()))

    except WebSocketDisconnect:
        pass
    finally:
        async with state_lock:
            robot_clients.discard(ws)
        await broadcast_state()

# =========================
# HTTP endpoint
# =========================

@app.get("/")
async def index():
    with open("page.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

# =========================
# Entry point
# =========================

if __name__ == "__main__":
    uvicorn.run(
        "vote_bot:app",
        host="0.0.0.0",
        port=int(os.getenv("VOTEBOT_PORT", "5000")),
        log_level="info",
    )