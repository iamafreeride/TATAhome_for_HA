"""Live TATAHome cloud session.

The vendor cloud keeps an authenticated session bound to one TCP connection:
a fresh connection cannot reuse only the session id.  This class therefore owns
one socket per browser session and serialises requests on it.

Wire facts verified against the real account and server:
  * login:        ctype=2, flow=0, cid=0, did=0, seq=0, opcode 0x0BB9
  * device list:  cid=0, did=0, seq=0, opcode 0x0BCB
  * status:       cid=uid, did=devid, seq=0, opcode 0x1009
  * start:        cid=uid, did=devid, seq=0, opcode 0x106D, ctrlValue=1, cleanType=2
  * pause/stop:   cid=uid, did=devid, seq=0, opcode 0x106D, ctrlValue=0, cleanType=2
  * dock/charge:  cid=uid, did=devid, seq=0, opcode 0x1069, enable=0
"""

from __future__ import annotations

import contextlib
import gzip
import socket
import threading
import time
import zlib
from dataclasses import dataclass
from typing import Any

from .protocol import (
    DEFAULT_MFRS_ID,
    OP_USER_LOGIN_REQ,
    OP_USER_LOGIN_RSP,
    CloudLoginResult,
    Packet,
    ProtocolError,
    _as_int,
    _as_text,
    _field_bytes,
    _field_str,
    _field_uint,
    _parse_fields,
    build_login_payload,
    parse_login_result,
    parse_packet,
)

OP_DEVICE_LIST_REQ = 0x0BCB
OP_DEVICE_STATUS_REQ = 0x1009
OP_DEVICE_AUTO_CLEAN_REQ = 0x106D
OP_DEVICE_CHARGE_REQ = 0x1069
OP_DEVICE_CONSUMABLES_REQ = 0x1113
OP_DEVICE_SETTINGS_REQ = 0x1459
OP_QUIET_GET_REQ = 0x146B
OP_QUIET_SET_REQ = 0x146D

CLOUD_HOST = "fas.haier.3irobotix.net"
CLOUD_PORT = 4020


class CloudError(Exception):
    pass


@dataclass
class CloudDevice:
    devid: int
    serial: str
    alias: str
    firmware: str
    online: bool
    status: int = 0
    modetype: int = 0
    power: int = 0
    ctrlversion: int = 0

    def public(self) -> dict[str, Any]:
        return {
            "id": str(self.devid),
            "devid": self.devid,
            "serial": self.serial,
            "name": self.alias or self.serial,
            "model": self.alias or "TATAHome",
            "firmware": self.firmware or "-",
            "online": self.online,
        }


class CloudSession:
    def __init__(self, host: str = CLOUD_HOST, port: int = CLOUD_PORT, timeout: float = 10.0,
                 heartbeat_seconds: int = 120) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self.uid = 0
        self.sessionid = ""
        self.email = ""
        self.local_mode = False
        self.devices: list[CloudDevice] = []
        self._lock = threading.RLock()
        self._last_status: dict[int, dict[str, Any]] = {}
        self._consumables_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
        self.default_mode = "auto"
        self.default_suction: str | None = None
        self.default_water: str | None = None
        self.history_map = True
        self.breakpoint_resume = True
        self.carpet_turbo = False
        self.voice_enabled = True
        self.volume = 50
        self._quiet_cache: dict[int, tuple[float, dict[str, Any]]] = {}
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self.heartbeat_seconds = max(30, int(heartbeat_seconds))

    # ------------------------------------------------------------------ socket
    def _recv_packet(self, sock: socket.socket) -> Packet:
        head = b""
        while len(head) < 4:
            chunk = sock.recv(4 - len(head))
            if not chunk:
                raise CloudError("Cloud closed the connection")
            head += chunk
        total = int.from_bytes(head, "little")
        if total < 24 or total > 1024 * 1024:
            raise CloudError(f"Invalid response length {total}")
        body = b""
        while len(body) < total - 4:
            chunk = sock.recv(total - 4 - len(body))
            if not chunk:
                raise CloudError("Cloud closed the connection mid-packet")
            body += chunk
        return parse_packet(head + body)

    def _send(self, sock: socket.socket, opcode: int, payload: bytes = b"",
              cid: int = 0, did: int = 0, seq: int = 0) -> Packet:
        sock.sendall(self._packet(opcode, payload, cid, did, seq))
        return self._recv_packet(sock)

    @staticmethod
    def _packet(opcode: int, payload: bytes, cid: int, did: int, seq: int) -> bytes:
        import struct
        return (
            struct.pack("<I", 24 + len(payload))
            + bytes([2, 0])
            + struct.pack("<I", cid)
            + struct.pack("<I", did)
            + struct.pack("<Q", seq)
            + struct.pack("<H", opcode)
            + payload
        )

    # ------------------------------------------------------------------ login
    def login(self, email: str, password: str) -> CloudLoginResult:
        self.close()
        self.local_mode = False
        self.host = CLOUD_HOST
        self.port = CLOUD_PORT
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            sock.settimeout(self.timeout)
            payload = build_login_payload(email, password, mfrs_id=DEFAULT_MFRS_ID)
            pkt = self._send(sock, OP_USER_LOGIN_REQ, payload, 0, 0, 0)
            if pkt.opcode != OP_USER_LOGIN_RSP:
                raise CloudError(f"Unexpected login opcode 0x{pkt.opcode:04X}")
            result = parse_login_result(pkt.payload)
        except (OSError, ProtocolError) as exc:
            self.close()
            raise CloudError(str(exc)) from exc

        attrs = result["attrs"]
        if result["errcode"] != 0:
            self.close()
            return CloudLoginResult(
                ok=False,
                errcode=result["errcode"],
                errstr=result["errstr"],
                raw=pkt.payload,
            )

        self.sock = sock
        self.uid = int(attrs.get("uid", 0))
        self.sessionid = str(attrs.get("sessionid", ""))
        self.email = email
        try:
            self.devices = self._fetch_devices()
        except (OSError, ProtocolError, CloudError) as exc:
            self.close()
            raise CloudError(f"Device list failed: {exc}") from exc
        if not self.devices:
            # Some accounts return only dftDevid; keep a usable placeholder.
            dft = int(attrs.get("dftDevid", 0))
            if dft:
                self.devices = [CloudDevice(devid=dft, serial=str(dft), alias="TATAHome", firmware="-", online=False)]
        self.start_heartbeat()
        return CloudLoginResult(
            ok=True,
            errcode=0,
            errstr="",
            uid=self.uid,
            sessionid=self.sessionid,
            nickname=str(attrs.get("nickname", "")),
            dft_devid=int(attrs.get("dftDevid", 0)),
            raw=pkt.payload,
        )

    def get_wlan_info(self) -> dict[str, Any]:
        """Ask the cloud for the robot's LAN address (opcode 0x100B)."""
        if not self.sock:
            raise CloudError("Not connected to TATAHome cloud")
        device = self.select(None)
        pkt = self._request(0x100B, b"", self.uid, device.devid)
        outer = _parse_fields(self._unpack(pkt.payload))
        if _as_int(outer.get(1, [0])[-1]) != 0:
            raise CloudError(_as_text(outer.get(2, [b"WLAN info unavailable"])[-1]))
        attrs = _parse_fields(outer[3][-1])
        return {
            "ip": _as_text(attrs.get(1, [b""])[-1]),
            "ssid": _as_text(attrs.get(2, [b""])[-1]),
            "port": _as_int(attrs.get(3, [0])[-1]),
            "mask": _as_text(attrs.get(4, [b""])[-1]),
            "mac": _as_text(attrs.get(5, [b""])[-1]),
        }

    def connect_local(self, host: str, port: int, uid: int, device: CloudDevice) -> None:
        """Connect directly to the robot's LAN TCP server.

        The local server speaks the same 24-byte RN envelope, but there is no
        login/sessionid step; cid=uid, did=devid is enough.
        """
        self.close()
        sock = socket.create_connection((host, port), timeout=self.timeout)
        sock.settimeout(self.timeout)
        self.host = host
        self.port = port
        self.sock = sock
        self.uid = int(uid)
        self.sessionid = ""
        self.local_mode = True
        self.devices = [
            CloudDevice(
                devid=device.devid,
                serial=device.serial,
                alias=device.alias,
                firmware=device.firmware,
                online=True,
            )
        ]
        self._last_status.clear()
        self.start_heartbeat()

    def start_heartbeat(self) -> None:
        """Keep the vendor TCP session warm without flooding the server."""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
        self._heartbeat_stop.clear()

        def loop() -> None:
            while not self._heartbeat_stop.wait(self.heartbeat_seconds):
                with self._lock:
                    if not self.sock:
                        return
                    try:
                        device = self.devices[0] if self.devices else None
                        did = device.devid if device else 0
                        self._send(self.sock, 0x07D5, b"", self.uid, did, 0)
                    except (OSError, ProtocolError, CloudError):
                        self.close()
                        return

        self._heartbeat_thread = threading.Thread(target=loop, daemon=True)
        self._heartbeat_thread.start()

    def _fetch_devices(self) -> list[CloudDevice]:
        if not self.sock:
            return []
        payload = _field_uint(1, self.uid) + _field_str(2, self.sessionid) + _field_uint(3, 0)
        last_error: Exception | None = None
        outer: dict[int, list[Any]] = {}
        for _attempt in range(3):
            try:
                pkt = self._send(self.sock, OP_DEVICE_LIST_REQ, payload, 0, 0, 0)
                outer = _parse_fields(self._unpack(pkt.payload))
                break
            except (OSError, ProtocolError) as exc:
                last_error = exc
                time.sleep(0.4)
        else:
            raise CloudError(f"Unreadable device-list response from cloud: {last_error}")
        if _as_int(outer.get(1, [0])[-1]) != 0:
            raise CloudError(_as_text(outer.get(2, [b"device list failed"])[-1]))
        if 3 not in outer:
            return []
        device_list = _parse_fields(outer[3][-1])
        devices: list[CloudDevice] = []
        for raw in device_list.get(1, []):
            fields = _parse_fields(raw)
            devices.append(CloudDevice(
                devid=_as_int(fields.get(2, [0])[-1]),
                serial=_as_text(fields.get(1, [b""])[-1]),
                alias=_as_text(fields.get(5, [b""])[-1]),
                firmware=_as_text(fields.get(7, [b""])[-1]),
                online=_as_int(fields.get(4, [0])[-1]) == 1,
                status=_as_int(fields.get(4, [0])[-1]),
                modetype=_as_int(fields.get(9, [0])[-1]),
                power=_as_int(fields.get(10, [0])[-1]),
                ctrlversion=_as_int(fields.get(11, [0])[-1]),
            ))
        return devices

    # ------------------------------------------------------------------ requests
    def _request(self, opcode: int, payload: bytes = b"", cid: int = 0, did: int = 0) -> Packet:
        with self._lock:
            if not self.sock:
                raise CloudError("Not connected to TATAHome cloud")
            try:
                return self._send(self.sock, opcode, payload, cid, did, 0)
            except CloudError:
                self.close()
                raise
            except (OSError, ProtocolError) as exc:
                self.close()
                raise CloudError(str(exc)) from exc

    @staticmethod
    def _unpack(payload: bytes) -> bytes:
        if payload[:2] == b"\x1f\x8b":
            try:
                return gzip.decompress(payload)
            except OSError:
                return payload
        if payload[:1] == b"\x78":
            try:
                return zlib.decompress(payload)
            except zlib.error:
                return payload
        return payload

    def _consumables(self, device: CloudDevice) -> list[dict[str, Any]]:
        cached = self._consumables_cache.get(device.devid)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        try:
            pkt = self._request(OP_DEVICE_CONSUMABLES_REQ, b"", self.uid, device.devid)
            if pkt.opcode != 0x1114:
                return []
            fields = _parse_fields(self._unpack(pkt.payload))
        except (CloudError, ProtocolError):
            return []
        if 2 in fields and isinstance(fields[2][-1], (bytes, bytearray)):
            return []
        # DeviceConsumablesParam: mainBrush=1, sideBrush=2, filter=3, dishcloth=4.
        names = {
            1: "主刷",
            2: "邊刷",
            3: "濾網",
            4: "抹布",
        }
        items = []
        for number, name in names.items():
            remaining = _as_int(fields.get(number, [0])[-1])
            # The vendor reports remaining life in days (0..180 observed).
            percent = max(0, min(100, round(remaining / 180 * 100)))
            items.append({
                "key": str(number),
                "name": name,
                "remaining": remaining,
                "percent": percent,
                "display": f"{remaining} 天",
            })
        self._consumables_cache[device.devid] = (time.time(), items)
        return items

    def _status(self, device: CloudDevice) -> dict[str, Any]:
        pkt = self._request(OP_DEVICE_STATUS_REQ, b"", self.uid, device.devid)
        try:
            fields = _parse_fields(self._unpack(pkt.payload))
        except ProtocolError as exc:
            raise CloudError("Unreadable status response from cloud") from exc
        # Error shape: {1: errcode, 2: errstr(string), 3: opcode}
        if 2 in fields and isinstance(fields[2][-1], (bytes, bytearray)):
            raise CloudError(_as_text(fields[2][-1]))

        working = _as_int(fields.get(3, [0])[-1])
        charge = _as_int(fields.get(5, [0])[-1])
        if working == 1:
            state = "cleaning"
        elif working == 2:
            state = "returning"
        elif charge == 1:
            state = "docked"
        else:
            state = "paused"

        raw_battery = _as_int(fields.get(4, [0])[-1])
        battery = raw_battery / 10 if raw_battery > 100 else raw_battery
        battery = max(0, min(100, int(round(battery))))

        status = {
            "online": True,
            "battery": battery,
            "state": state,
            "workingMode": working,
            "chargeState": charge,
            "faultType": _as_int(fields.get(6, [0])[-1]),
            "faultCode": _as_int(fields.get(7, [0])[-1]),
            "cleanPreference": _as_int(fields.get(8, [0])[-1]),
            "cleanTime": _as_int(fields.get(10, [0])[-1]),
            "cleanSize": _as_int(fields.get(11, [0])[-1]),
            "waterLevel": _as_int(fields.get(12, [0])[-1]),
            "mapHeadId": _as_int(fields.get(1, [0])[-1]),
            "hasHistoryMap": _as_int(fields.get(2, [0])[-1]),
            "updatedAt": int(time.time() * 1000),
        }
        self._last_status[device.devid] = status
        return status

    # ------------------------------------------------------------------ public
    def public_devices(self) -> list[dict[str, Any]]:
        return [d.public() for d in self.devices]

    def select(self, device_id: str | int | None) -> CloudDevice:
        if not self.devices:
            raise CloudError("No device on this account")
        if device_id is None:
            return self.devices[0]
        wanted = str(device_id)
        for device in self.devices:
            if str(device.devid) == wanted or device.serial == wanted:
                return device
        raise CloudError("Device not found")

    def clean_records(self, device: CloudDevice, limit: int = 20) -> list[dict[str, Any]]:
        payload = (_field_str(1, self.sessionid) + _field_uint(2, device.devid)
                   + _field_uint(3, 0) + _field_uint(4, int(time.time())))
        try:
            pkt = self._request(0x1389, payload, self.uid, device.devid)
            top = _parse_fields(self._unpack(pkt.payload))
            blob = top[3][-1]
            if not isinstance(blob, (bytes, bytearray)):
                return []
            rows = _parse_fields(blob)
        except (CloudError, ProtocolError, KeyError, IndexError, TypeError):
            return []
        result: list[dict[str, Any]] = []
        for value in rows.get(1, []):
            if not isinstance(value, (bytes, bytearray)):
                continue
            try:
                record = _parse_fields(value)
            except ProtocolError:
                continue
            started = _as_int(record.get(1, [0])[-1])
            result.append({
                "started": started,
                "duration": _as_int(record.get(4, [0])[-1]),
                "mapId": _as_int(record.get(9, [0])[-1]),
                "mapName": _as_text(record.get(10, [b""])[-1]),
            })
            if len(result) >= limit:
                break
        return result

    def latest_map(self, device: CloudDevice) -> dict[str, Any]:
        """Return the latest finished clean-task map, if the vendor stored one."""
        payload = (_field_str(1, self.sessionid) + _field_uint(2, device.devid)
                   + _field_uint(3, 0) + _field_uint(4, int(time.time())))
        try:
            pkt = self._request(0x1389, payload, self.uid, device.devid)
            top = _parse_fields(self._unpack(pkt.payload))
            blob = top[3][-1]
            if not isinstance(blob, (bytes, bytearray)):
                return {"available": False, "task": None}
            records = [v for v in _parse_fields(blob).get(1, []) if isinstance(v, (bytes, bytearray))]
            if not records:
                return {"available": False, "task": None}
            record = _parse_fields(records[0])
            task = _as_int(record.get(1, [0])[-1])
            pkt = self._request(0x1391, _field_uint(1, device.devid) + _field_uint(2, task), self.uid, device.devid)
            fields = _parse_fields(self._unpack(pkt.payload))
            data = fields.get(4, [b""])[-1]
            if isinstance(data, (bytes, bytearray)) and data:
                return {"available": True, "task": task, "bytes": len(data), "data": bytes(data)}
            return {"available": False, "task": task, "bytes": 0}
        except (CloudError, ProtocolError, KeyError, IndexError, TypeError):
            return {"available": False, "task": None}

    def snapshot(self, device_id: str | int | None = None) -> dict[str, Any]:
        device = self.select(device_id)
        status: dict[str, Any]
        try:
            status = self._status(device)
            device.online = True
        except CloudError:
            # A single transient cloud timeout is common right after a command;
            # retry once before showing an error to the browser.
            time.sleep(0.5)
            try:
                status = self._status(device)
                device.online = True
            except CloudError as exc:
                status = dict(self._last_status.get(device.devid, {}))
                status["online"] = False
                status["error"] = str(exc)
                device.online = False

        battery = int(status.get("battery", 0))
        state = str(status.get("state", "paused"))
        if not status.get("online", False):
            state = "error" if status.get("error") else state
        clean_seconds = int(status.get("cleanTime", 0))
        clean_size = int(status.get("cleanSize", 0))
        preference = int(status.get("cleanPreference", 2))
        suction = self.default_suction or {0: "quiet", 1: "quiet", 2: "standard", 3: "strong", 4: "max"}.get(preference, "standard")
        water_raw = int(status.get("waterLevel", 12))
        if water_raw <= 0:
            water = "off"
        elif water_raw < 8:
            water = "low"
        elif water_raw <= 14:
            water = "medium"
        else:
            water = "high"
        water = self.default_water or water

        return {
            "device": {
                "id": str(device.devid),
                "devid": device.devid,
                "serial": device.serial,
                "name": device.alias or device.serial,
                "model": device.alias or "TATAHome",
                "firmware": device.firmware or "-",
                "online": bool(status.get("online", False)),
                "battery": battery,
                "state": state,
                "mode": self.default_mode,
                "progress": 0,
                "area": round(clean_size / 100, 1),
                "cleanSeconds": clean_seconds,
                "suction": suction,
                "water": water,
                "error": status.get("error") or None,
                "position": {"x": 0, "y": 0, "heading": 0},
                "updatedAt": int(status.get("updatedAt", time.time() * 1000)),
                "mapAvailable": False,
            },
            "map": {
                "width": 18,
                "height": 12,
                "cleaned": [],
                "path": [],
                "robot": {"x": 0, "y": 0, "heading": 0},
                "available": False,
            },
            "schedule": [],
            "consumables": self._consumables(device) if status.get("online") else [],
            "settings": self._settings(device),
        }

    def set_setting(self, device_id: str | int | None, key: str, value: str) -> dict[str, Any]:
        device = self.select(device_id)
        raw_value = value
        key = key.lower()
        value = value.lower()
        if key in {"nickname", "alias", "name"}:
            alias = raw_value.strip()
            if not alias:
                raise CloudError("Nickname cannot be empty")
            payload = (_field_uint(1, self.uid) + _field_str(2, self.sessionid)
                       + _field_uint(3, device.devid) + _field_str(4, alias))
            pkt = self._request(0x0BD1, payload, self.uid, device.devid)
            fields = _parse_fields(self._unpack(pkt.payload))
            if 2 in fields and isinstance(fields[2][-1], (bytes, bytearray)):
                raise CloudError(_as_text(fields[2][-1]))
            device.alias = alias
            return self._settings(device)
        if key in {"history_map", "memory_map"}:
            field, number = 5, 1 if value in {"1", "true", "on", "yes"} else 0
            self.history_map = bool(number)
            self._write_pref(device, field, number)
            return self._settings(device)
        if key in {"breakpoint", "breakpoint_resume"}:
            field, number = 3, 1 if value in {"1", "true", "on", "yes"} else 0
            self.breakpoint_resume = bool(number)
            self._write_pref(device, field, number)
            return self._settings(device)
        if key in {"carpet_turbo"}:
            field, number = 4, 1 if value in {"1", "true", "on", "yes"} else 0
            self.carpet_turbo = bool(number)
            self._write_pref(device, field, number)
            return self._settings(device)
        if key in {"voice", "voice_mode"}:
            number = 1 if value in {"1", "true", "on", "yes"} else 0
            self.voice_enabled = bool(number)
            self._write_ctrl(device, 1, number)
            return self._settings(device)
        if key == "volume":
            try:
                number = max(0, min(100, int(value)))
            except ValueError as exc:
                raise CloudError("Unsupported volume") from exc
            self.volume = number
            self._write_ctrl(device, 2, number)
            return self._settings(device)
        if key == "mode":
            if value not in {"auto", "spot", "edge", "room"}:
                raise CloudError("Unsupported cleaning mode")
            # The cloud has no persistent "preset mode" field in the tested
            # firmware; carry it into the next start command instead.
            self.default_mode = value
            return self._settings(device)
        if key == "suction":
            values = {"quiet": 0, "standard": 2, "strong": 3, "max": 4}
            if value not in values:
                raise CloudError("Unsupported suction level")
            field, number = 1, values[value]
            self.default_suction = value
        elif key == "water":
            values = {"off": 0, "low": 6, "medium": 12, "high": 18}
            if value not in values:
                raise CloudError("Unsupported water level")
            field, number = 6, values[value]
            self.default_water = value
        else:
            raise CloudError("Unknown setting")

        self._write_pref(device, field, number)
        return self._settings(device)

    def _write_pref(self, device: CloudDevice, field: int, number: int) -> None:
        pref = _field_uint(field, number)
        payload = _field_str(1, self.sessionid) + _field_uint(2, device.devid) + _field_bytes(3, pref)
        pkt = self._request(OP_DEVICE_SETTINGS_REQ, payload, self.uid, device.devid)
        try:
            fields = _parse_fields(self._unpack(pkt.payload))
        except ProtocolError as exc:
            raise CloudError("Unreadable settings response from cloud") from exc
        if 2 in fields and isinstance(fields[2][-1], (bytes, bytearray)):
            raise CloudError(_as_text(fields[2][-1]))
        if 1 in fields and _as_int(fields[1][-1]) not in (0,) and _as_int(fields[1][-1]) < 1000:
            raise CloudError(f"Setting rejected (errcode {_as_int(fields[1][-1])})")

    def _write_ctrl(self, device: CloudDevice, field: int, number: int) -> None:
        inner = _field_uint(field, number)
        payload = _field_str(1, self.sessionid) + _field_uint(2, device.devid) + _field_bytes(3, inner)
        pkt = self._request(0x145D, payload, self.uid, device.devid)
        fields = _parse_fields(self._unpack(pkt.payload))
        if 2 in fields and isinstance(fields[2][-1], (bytes, bytearray)):
            raise CloudError(_as_text(fields[2][-1]))

    def _settings(self, device: CloudDevice) -> dict[str, Any]:
        status = self._last_status.get(device.devid, {})
        quiet = self.quiet_hours(device)
        preference = int(status.get("cleanPreference", 2))
        suction = self.default_suction or {0: "quiet", 1: "quiet", 2: "standard", 3: "strong", 4: "max"}.get(preference, "standard")
        water_raw = int(status.get("waterLevel", 12))
        if water_raw <= 0:
            water = "off"
        elif water_raw < 8:
            water = "low"
        elif water_raw <= 14:
            water = "medium"
        else:
            water = "high"
        return {
            "suction": suction,
            "water": self.default_water or water,
            "mode": self.default_mode,
            "doNotDisturb": bool(quiet.get("enabled")),
            "quietStart": quiet.get("start", "22:00"),
            "quietEnd": quiet.get("end", "07:00"),
            "historyMap": self.history_map,
            "breakpointResume": self.breakpoint_resume,
            "carpetTurbo": self.carpet_turbo,
            "voice": self.voice_enabled,
            "volume": self.volume,
        }

    def quiet_hours(self, device: CloudDevice) -> dict[str, Any]:
        cached = self._quiet_cache.get(device.devid)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        if self.local_mode:
            # The local firmware does not answer the cloud quiet-hours read;
            # use the value written through HA (or a neutral default).
            return {"enabled": False, "start": "22:00", "end": "07:00"}
        payload = _field_str(1, self.sessionid) + _field_uint(2, device.devid)
        try:
            pkt = self._request(OP_QUIET_GET_REQ, payload, self.uid, device.devid)
            outer = _parse_fields(self._unpack(pkt.payload))
            inner = _parse_fields(outer[3][-1])
        except (CloudError, ProtocolError, KeyError, IndexError, TypeError):
            return {"enabled": False, "start": "22:00", "end": "07:00"}
        begin = _as_int(inner.get(2, [1320])[-1])
        end = _as_int(inner.get(3, [420])[-1])
        if not (0 <= begin < 1440 and 0 <= end < 1440):
            return {"enabled": False, "start": "22:00", "end": "07:00"}
        result = {
            "enabled": _as_int(inner.get(1, [0])[-1]) == 1,
            "start": f"{begin // 60:02d}:{begin % 60:02d}",
            "end": f"{end // 60:02d}:{end % 60:02d}",
        }
        self._quiet_cache[device.devid] = (time.time(), result)
        return result

    def set_quiet_hours(self, device_id: str | int | None, enabled: bool,
                        start: str, end: str) -> dict[str, Any]:
        device = self.select(device_id)
        try:
            start_parts = [int(x) for x in start.split(":", 1)]
            end_parts = [int(x) for x in end.split(":", 1)]
            begin = start_parts[0] * 60 + start_parts[1]
            finish = end_parts[0] * 60 + end_parts[1]
        except (ValueError, IndexError) as exc:
            raise CloudError("時間格式需為 HH:MM") from exc
        inner = _field_uint(1, 1 if enabled else 0) + _field_uint(2, begin) + _field_uint(3, finish)
        payload = _field_str(1, self.sessionid) + _field_uint(2, device.devid) + _field_bytes(3, inner)
        pkt = self._request(OP_QUIET_SET_REQ, payload, self.uid, device.devid)
        fields = _parse_fields(self._unpack(pkt.payload))
        if 2 in fields and isinstance(fields[2][-1], (bytes, bytearray)):
            raise CloudError(_as_text(fields[2][-1]))
        quiet = {"enabled": bool(enabled), "start": start, "end": end}
        self._quiet_cache[device.devid] = (time.time(), quiet)
        return quiet

    def command(self, device_id: str | int | None, action: str, mode: str | None = None) -> dict[str, Any]:
        device = self.select(device_id)
        action = action.lower()
        if action in {"start", "clean", "resume"}:
            selected_mode = mode if mode in {"auto", "spot", "edge", "room"} else self.default_mode
            clean_type = {"auto": 2, "spot": 1, "edge": 3, "room": 4}.get(selected_mode, 2)
            payload = _field_uint(1, 1) + _field_uint(2, clean_type)
            pkt = self._request(OP_DEVICE_AUTO_CLEAN_REQ, payload, self.uid, device.devid)
        elif action == "edge":
            pkt = self._request(0x107F, _field_uint(1, 1), self.uid, device.devid)
        elif action == "spot":
            pkt = self._request(0x1073, _field_uint(1, 1), self.uid, device.devid)
        elif action == "mop":
            pkt = self._request(0x107D, _field_uint(1, 1), self.uid, device.devid)
        elif action == "area":
            pkt = self._request(0x106B, _field_uint(1, 1), self.uid, device.devid)
        elif action == "two_pass":
            # repeatClean is CleanPerferenceParams field 2; set it, then start.
            pref = _field_uint(2, 1)
            self._request(OP_DEVICE_SETTINGS_REQ,
                          _field_str(1, self.sessionid) + _field_uint(2, device.devid) + _field_bytes(3, pref),
                          self.uid, device.devid)
            payload = _field_uint(1, 1) + _field_uint(2, 2)
            pkt = self._request(OP_DEVICE_AUTO_CLEAN_REQ, payload, self.uid, device.devid)
        elif action in {"pause", "stop"}:
            payload = _field_uint(1, 0) + _field_uint(2, 2)
            pkt = self._request(OP_DEVICE_AUTO_CLEAN_REQ, payload, self.uid, device.devid)
        elif action in {"dock", "charge", "return"}:
            # App calls DeviceBackCharge(devid, false); the wire field is
            # DeviceChargeParams.enable = 0 for "return to dock".
            payload = _field_uint(1, 0)
            pkt = self._request(OP_DEVICE_CHARGE_REQ, payload, self.uid, device.devid)
        else:
            raise CloudError(f"Unsupported command: {action}")

        fields: dict[int, list[Any]]
        try:
            fields = _parse_fields(self._unpack(pkt.payload))
        except ProtocolError:
            # Some command acknowledgements are short/opaque. The write reached
            # the cloud; let the next status poll determine the device state.
            return {"ok": True, "action": action, "device": device.public()}
        if 2 in fields and isinstance(fields[2][-1], (bytes, bytearray)):
            raise CloudError(_as_text(fields[2][-1]))
        if 1 in fields and _as_int(fields[1][-1]) not in (0,):
            # Command ack uses {1: 0}; status-shaped responses have a large field 1.
            errcode = _as_int(fields[1][-1])
            if errcode < 1000:
                raise CloudError(f"Command rejected (errcode {errcode})")
        return {"ok": True, "action": action, "device": device.public()}

    def close(self) -> None:
        self._heartbeat_stop.set()
        with self._lock:
            if self.sock:
                with contextlib.suppress(OSError):
                    self.sock.close()
            self.sock = None
