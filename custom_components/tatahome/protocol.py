"""TATAHome RN protocol primitives.

Recovered from the x86 build of libNetworkJni.so (Ghidra):

    header 24 bytes, little-endian
    offset 0  uint32  total length (header + payload)
    offset 4  uint8   client type (Android = 2)
    offset 5  9 bytes zero
    offset 14 uint64  user id (0 before login)
    offset 22 uint16  opcode

    USER_LOGIN_REQ = 0x0BB9  (3001)
    USER_LOGIN_RSP = 0x0BBA  (3002)

    UserLoginParams:   1 username string, 2 password string,
                       3 address string,  4 mfrsId uint32
    UserLoginResult:   1 errcode uint32, 2 errstr string, 3 attrs message
    UserLoginAttrs:    1 uid uint32, 2 sessionid string, 3 hasPwd uint32,
                       4 nickname string, 5 dftDevid uint32, 6 mfrsLang string

This module is intentionally dependency-free and never persists credentials.
"""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass
from typing import Any

HEADER_SIZE = 24
CLIENT_TYPE_ANDROID = 2
OP_USER_LOGIN_REQ = 0x0BB9
OP_USER_LOGIN_RSP = 0x0BBA
DEFAULT_MFRS_ID = 1001


class ProtocolError(Exception):
    """Raised when a packet cannot be encoded, decoded, or is rejected."""


def _varint(value: int) -> bytes:
    if value < 0:
        raise ProtocolError("varint cannot encode a negative value")
    out = bytearray()
    while True:
        chunk = value & 0x7F
        value >>= 7
        if value:
            out.append(chunk | 0x80)
        else:
            out.append(chunk)
            return bytes(out)


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ProtocolError("truncated varint")
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, offset
        shift += 7
        if shift > 63:
            raise ProtocolError("varint too long")


def _field_str(number: int, value: str) -> bytes:
    raw = value.encode("utf-8")
    return _field_bytes(number, raw)


def _field_bytes(number: int, raw: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(raw)) + raw


def _field_uint(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _parse_fields(data: bytes) -> dict[int, list[Any]]:
    fields: dict[int, list[Any]] = {}
    offset = 0
    while offset < len(data):
        key, offset = _read_varint(data, offset)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, offset = _read_varint(data, offset)
        elif wire == 2:
            length, offset = _read_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ProtocolError("truncated length-delimited field")
            value = data[offset:end]
            offset = end
        elif wire == 1:
            value = data[offset:offset + 8]
            offset += 8
        elif wire == 5:
            value = data[offset:offset + 4]
            offset += 4
        else:
            raise ProtocolError(f"unsupported protobuf wire type {wire}")
        fields.setdefault(number, []).append(value)
    return fields


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _as_int(value: Any) -> int:
    return int(value) if not isinstance(value, bytes) else int.from_bytes(value, "little")


def build_login_payload(
    username: str,
    password: str,
    *,
    address: str = "",
    mfrs_id: int = DEFAULT_MFRS_ID,
) -> bytes:
    """Serialize UserLoginParams without the packet header."""
    return (
        _field_str(1, username)
        + _field_str(2, password)
        + _field_str(3, address)
        + _field_uint(4, mfrs_id)
    )


def build_packet(opcode: int, payload: bytes, *, uid: int = 0,
                 client_type: int = CLIENT_TYPE_ANDROID) -> bytes:
    """Build the 24-byte RN envelope followed by *payload*."""
    if not 0 <= opcode <= 0xFFFF:
        raise ProtocolError("opcode out of range")
    if not 0 <= client_type <= 0xFF:
        raise ProtocolError("client type out of range")
    if uid < 0 or uid > 0xFFFFFFFFFFFFFFFF:
        raise ProtocolError("uid out of range")
    header = (
        struct.pack("<I", HEADER_SIZE + len(payload))
        + bytes([client_type])
        + b"\x00" * 9
        + struct.pack("<Q", uid)
        + struct.pack("<H", opcode)
    )
    return header + payload


@dataclass(frozen=True)
class Packet:
    total_length: int
    client_type: int
    uid: int
    opcode: int
    payload: bytes


def parse_packet(data: bytes) -> Packet:
    if len(data) < HEADER_SIZE:
        raise ProtocolError("packet shorter than 24-byte header")
    total, client_type, _reserved, uid, opcode = struct.unpack("<IB9sQH", data[:HEADER_SIZE])
    if total < HEADER_SIZE:
        raise ProtocolError("invalid total length")
    if total > len(data):
        raise ProtocolError("packet shorter than declared length")
    return Packet(total, client_type, uid, opcode, data[HEADER_SIZE:total])


def parse_login_result(payload: bytes) -> dict[str, Any]:
    fields = _parse_fields(payload)
    result: dict[str, Any] = {
        "errcode": _as_int(fields.get(1, [0])[-1]),
        "errstr": _as_text(fields.get(2, [b""])[-1]),
        "attrs": {},
    }
    if 3 in fields:
        attrs = _parse_fields(fields[3][-1])
        result["attrs"] = {
            "uid": _as_int(attrs.get(1, [0])[-1]),
            "sessionid": _as_text(attrs.get(2, [b""])[-1]),
            "hasPwd": _as_int(attrs.get(3, [0])[-1]),
            "nickname": _as_text(attrs.get(4, [b""])[-1]),
            "dftDevid": _as_int(attrs.get(5, [0])[-1]),
            "mfrsLang": _as_text(attrs.get(6, [b""])[-1]),
        }
    return result


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise ProtocolError("connection closed before a full packet was read")
        chunks.extend(chunk)
    return bytes(chunks)


@dataclass
class CloudLoginResult:
    ok: bool
    errcode: int = -1
    errstr: str = ""
    uid: int = 0
    sessionid: str = ""
    nickname: str = ""
    dft_devid: int = 0
    raw: bytes = b""

    def public(self) -> dict[str, Any]:
        # Never include the session id in API responses by default.
        return {
            "ok": self.ok,
            "errcode": self.errcode,
            "errstr": self.errstr,
            "uid": self.uid,
            "nickname": self.nickname,
            "dftDevid": self.dft_devid,
        }


class CloudClient:
    """Minimal login-only client for the vendor cloud.

    The vendor endpoints accepted TCP connections from the development host but
    never answered application packets, so this class is deliberately
    conservative: one attempt, no retries, short timeout, no credential logs.
    """

    def __init__(self, host: str, port: int = 4020, timeout: float = 8.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def login(self, username: str, password: str, *, mfrs_id: int = DEFAULT_MFRS_ID) -> CloudLoginResult:
        payload = build_login_payload(username, password, mfrs_id=mfrs_id)
        packet = build_packet(OP_USER_LOGIN_REQ, payload)
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.settimeout(self.timeout)
                sock.sendall(packet)
                header = _recv_exact(sock, 4)
                total = struct.unpack("<I", header)[0]
                if total < HEADER_SIZE or total > 1024 * 1024:
                    raise ProtocolError(f"unexpected response length {total}")
                rest = _recv_exact(sock, total - 4)
        except (OSError, ProtocolError) as exc:
            return CloudLoginResult(ok=False, errcode=-1, errstr=str(exc))

        raw = header + rest
        try:
            parsed = parse_packet(raw)
            if parsed.opcode != OP_USER_LOGIN_RSP:
                return CloudLoginResult(
                    ok=False, errcode=-1,
                    errstr=f"unexpected opcode 0x{parsed.opcode:04X}", raw=raw,
                )
            result = parse_login_result(parsed.payload)
        except ProtocolError as exc:
            return CloudLoginResult(ok=False, errcode=-1, errstr=str(exc), raw=raw)

        attrs = result["attrs"]
        return CloudLoginResult(
            ok=result["errcode"] == 0,
            errcode=result["errcode"],
            errstr=result["errstr"],
            uid=attrs.get("uid", 0),
            sessionid=attrs.get("sessionid", ""),
            nickname=attrs.get("nickname", ""),
            dft_devid=attrs.get("dftDevid", 0),
            raw=raw,
        )
