"""WebSocket bridge for the IUT Hackathon office monitoring server."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import aiohttp


logger = logging.getLogger(__name__)

ROOM_LABELS = {
    "drawing": "Drawing Room",
    "workroom1": "Work Room 1",
    "workroom2": "Work Room 2",
}

ROOM_ALIASES = {
    "drawing": "drawing",
    "drawingroom": "drawing",
    "workroom1": "workroom1",
    "workroom 1": "workroom1",
    "wr1": "workroom1",
    "workroom2": "workroom2",
    "workroom 2": "workroom2",
    "wr2": "workroom2",
}

PRESETS = {
    "office_busy",
    "after_hours",
    "room_stuck",
    "drawing_only",
    "all_off",
}

AlertCallback = Callable[[dict[str, Any]], Awaitable[None]]


class OfficeWebSocketClient:
    """Keeps the latest office snapshot and sends commands over WebSocket."""

    def __init__(self, ws_url: str, reconnect_seconds: int = 5) -> None:
        self.ws_url = ws_url
        self.reconnect_seconds = reconnect_seconds
        self.connected = False
        self.latest_snapshot: dict[str, Any] | None = None
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task[None] | None = None
        self._seen_alert_ids: set[str] = set()
        self._initialized_alerts = False

    def start(self, on_alert: AlertCallback | None = None) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(on_alert))

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()

    async def send_toggle(self, device_id: str) -> bool:
        return await self._send({"type": "toggle", "deviceId": device_id})

    async def send_preset(self, preset: str) -> bool:
        return await self._send({"type": "preset", "preset": preset})

    async def send_autosim(self, enabled: bool) -> bool:
        return await self._send({"type": "setAutoSim", "enabled": enabled})

    async def set_devices_status(
        self,
        target_status: str,
        device_type: str | None = None,
        room_id: str | None = None,
    ) -> list[str]:
        """Toggle matching devices that are not already at the target status."""

        targets = [
            str(device["id"])
            for device in self._devices()
            if device.get("status") != target_status
            and (device_type is None or device.get("type") == device_type)
            and (room_id is None or device.get("room") == room_id)
        ]
        for device_id in targets:
            await self.send_toggle(device_id)
        self._patch_device_statuses(targets, target_status)
        return targets

    async def set_device_status(self, device_id: str, target_status: str) -> bool:
        device = self.device_by_id(device_id)
        if not device:
            return False
        if device.get("status") == target_status:
            return True
        sent = await self.send_toggle(device_id)
        if sent:
            self._patch_device_statuses([device_id], target_status)
        return sent

    def is_ready(self) -> bool:
        return self.connected and self.latest_snapshot is not None

    def device_ids(self) -> list[str]:
        return [str(device["id"]) for device in self._devices()]

    def device_by_id(self, device_id: str) -> dict[str, Any] | None:
        for device in self._devices():
            if device.get("id") == device_id:
                return device
        return None

    def resolve_device_id(
        self,
        room_id: str,
        device_type: str,
        device_number: int,
    ) -> str | None:
        device_id = f"{room_id}-{device_type}-{device_number}"
        return device_id if self.device_by_id(device_id) else None

    def on_device_ids(self, device_type: str | None = None) -> list[str]:
        return self.device_ids_by_status("on", device_type)

    def device_ids_by_status(
        self,
        status: str,
        device_type: str | None = None,
        room_id: str | None = None,
    ) -> list[str]:
        return [
            str(device["id"])
            for device in self._devices()
            if device.get("status") == status
            and (device_type is None or device.get("type") == device_type)
            and (room_id is None or device.get("room") == room_id)
        ]

    def on_devices(self) -> list[dict[str, Any]]:
        return [device for device in self._devices() if device.get("status") == "on"]

    def describe_device(self, device_id: str) -> str:
        device = self.device_by_id(device_id)
        if not device:
            return device_id
        room = ROOM_LABELS.get(str(device.get("room")), str(device.get("room")))
        return f"{room} {device.get('label')} (`{device_id}`)"

    def format_status(self) -> str:
        if not self.latest_snapshot:
            return "The office WebSocket is not connected yet."

        lines = []
        for room_id, room_label in ROOM_LABELS.items():
            devices = [device for device in self._devices() if device.get("room") == room_id]
            lines.append(f"{room_label}: {summarize_room_devices(devices)}")

        alerts = self.latest_snapshot.get("alerts", [])
        alert_text = f"Active alerts: {len(alerts)}"
        return "\n".join([*lines, alert_text])

    def format_room_summary(self, room_id: str | None = None) -> str:
        if not self.latest_snapshot:
            return "The office WebSocket is not connected yet."

        room_ids = [room_id] if room_id else list(ROOM_LABELS)
        lines = []
        for current_room_id in room_ids:
            if current_room_id not in ROOM_LABELS:
                continue
            devices = [
                device
                for device in self._devices()
                if device.get("room") == current_room_id
            ]
            lines.append(
                f"{ROOM_LABELS[current_room_id]}: {summarize_room_devices(devices)}"
            )
        return ". ".join(lines) + "."

    def format_usage(self) -> str:
        if not self.latest_snapshot:
            return "The office WebSocket is not connected yet."

        total = sum(int(device.get("wattage", 0)) for device in self._devices())
        by_room = []
        for room_id, room_label in ROOM_LABELS.items():
            wattage = sum(
                int(device.get("wattage", 0))
                for device in self._devices()
                if device.get("room") == room_id
            )
            by_room.append(f"{room_label}: {wattage}W")

        return f"Total power: {total}W. " + ", ".join(by_room)

    def format_room(self, room_name: str) -> str:
        if not self.latest_snapshot:
            return "The office WebSocket is not connected yet."

        room_id = normalize_room(room_name)
        if not room_id:
            return 'Unknown room. Try "drawing", "workroom1", or "workroom2".'

        devices = [device for device in self._devices() if device.get("room") == room_id]
        lines = [f"{ROOM_LABELS[room_id]}:"]
        for device in devices:
            lines.append(
                f"- {device.get('id')}: {device.get('label')} "
                f"{str(device.get('status', '')).upper()} ({device.get('wattage', 0)}W)"
            )
        return "\n".join(lines)

    def format_alert(self, alert: dict[str, Any]) -> str:
        room = alert.get("room")
        room_label = ROOM_LABELS.get(str(room), "All rooms") if room else "All rooms"
        severity = str(alert.get("severity", "info")).upper()
        return f"{severity}: {alert.get('message', 'Office alert')} ({room_label})"

    def context_for_ai(self) -> str:
        if not self.latest_snapshot:
            return "Office WebSocket is not connected. Live device status is unavailable."

        devices = self._devices()
        on_devices = [device for device in devices if device.get("status") == "on"]
        alerts = self.latest_snapshot.get("alerts", [])

        lines = [
            f"WebSocket: connected to {self.ws_url}",
            f"Auto simulation: {self.latest_snapshot.get('autoSim')}",
            self.format_status(),
            self.format_usage(),
            "On devices: "
            + (
                ", ".join(str(device.get("id")) for device in on_devices)
                if on_devices
                else "none"
            ),
        ]

        if alerts:
            lines.append("Alerts: " + " | ".join(self.format_alert(alert) for alert in alerts[-3:]))
        else:
            lines.append("Alerts: none")

        lines.append("Supported commands: !status, !usage, !room <room>, !toggle <deviceId>, !preset <preset>, !autosim on|off")
        return "\n".join(lines)

    async def _run(self, on_alert: AlertCallback | None) -> None:
        while True:
            try:
                self._session = aiohttp.ClientSession()
                async with self._session.ws_connect(self.ws_url, heartbeat=20) as ws:
                    self._ws = ws
                    self.connected = True
                    logger.info("Connected to office WebSocket: %s", self.ws_url)

                    async for message in ws:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_message(message.data, on_alert)
                        elif message.type in {
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        }:
                            break
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Office WebSocket connection failed")
            finally:
                self.connected = False
                self._ws = None
                if self._session:
                    await self._session.close()
                    self._session = None

            await asyncio.sleep(self.reconnect_seconds)

    async def _handle_message(
        self,
        raw_data: str,
        on_alert: AlertCallback | None,
    ) -> None:
        try:
            message = json.loads(raw_data)
        except json.JSONDecodeError:
            logger.warning("Ignoring invalid office WebSocket payload")
            return

        if message.get("type") != "snapshot":
            return

        self.latest_snapshot = message.get("data") or {}
        alerts = self.latest_snapshot.get("alerts", [])
        if not isinstance(alerts, list):
            return

        current_ids = {str(alert.get("id")) for alert in alerts if alert.get("id")}
        if not self._initialized_alerts:
            self._seen_alert_ids = current_ids
            self._initialized_alerts = True
            return

        new_alerts = [
            alert
            for alert in alerts
            if alert.get("id") and str(alert["id"]) not in self._seen_alert_ids
        ]
        self._seen_alert_ids.update(current_ids)

        if on_alert:
            for alert in new_alerts:
                await on_alert(alert)

    async def _send(self, payload: dict[str, Any]) -> bool:
        if not self._ws or self._ws.closed:
            return False

        await self._ws.send_json(payload)
        return True

    def _devices(self) -> list[dict[str, Any]]:
        if not self.latest_snapshot:
            return []
        devices = self.latest_snapshot.get("devices", [])
        return devices if isinstance(devices, list) else []

    def _patch_device_statuses(self, device_ids: list[str], target_status: str) -> None:
        if not self.latest_snapshot:
            return

        device_id_set = set(device_ids)
        for device in self._devices():
            if device.get("id") not in device_id_set:
                continue

            device["status"] = target_status
            if target_status == "off":
                device["wattage"] = 0
                device["on_since"] = None
            else:
                device["wattage"] = FAN_WATTAGE if device.get("type") == "fan" else LIGHT_WATTAGE
                device["on_since"] = datetime.now().isoformat()
            device["last_changed"] = datetime.now().isoformat()


def normalize_room(room_name: str) -> str | None:
    normalized = " ".join(room_name.lower().strip().split())
    compact = normalized.replace(" ", "")
    return ROOM_ALIASES.get(normalized) or ROOM_ALIASES.get(compact)


def summarize_room_devices(devices: list[dict[str, Any]]) -> str:
    on_fans = sum(
        1
        for device in devices
        if device.get("type") == "fan" and device.get("status") == "on"
    )
    on_lights = sum(
        1
        for device in devices
        if device.get("type") == "light" and device.get("status") == "on"
    )

    parts = []
    if on_fans:
        parts.append(f"{on_fans} fan{'s' if on_fans != 1 else ''} ON")
    if on_lights:
        parts.append(f"{on_lights} light{'s' if on_lights != 1 else ''} ON")

    return ", ".join(parts) if parts else "all off"


def normalize_preset(preset: str) -> str | None:
    normalized = preset.lower().strip().replace("-", "_").replace(" ", "_")
    return normalized if normalized in PRESETS else None


def parse_bool(value: str) -> bool | None:
    normalized = value.lower().strip()
    if normalized in {"on", "true", "yes", "1", "enable", "enabled"}:
        return True
    if normalized in {"off", "false", "no", "0", "disable", "disabled"}:
        return False
    return None


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
