from __future__ import annotations

import socket
import struct
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "tatahome"))
import protocol  # noqa: E402


class ProtocolTests(unittest.TestCase):
    def test_packet_round_trip(self):
        payload = protocol.build_login_payload("user@example.com", "secret", mfrs_id=1001)
        packet = protocol.build_packet(protocol.OP_USER_LOGIN_REQ, payload, uid=0)
        self.assertEqual(len(packet), 24 + len(payload))
        parsed = protocol.parse_packet(packet)
        self.assertEqual(parsed.client_type, 2)
        self.assertEqual(parsed.uid, 0)
        self.assertEqual(parsed.opcode, protocol.OP_USER_LOGIN_REQ)
        self.assertEqual(parsed.payload, payload)

    def test_login_payload_fields(self):
        payload = protocol.build_login_payload("u@example.com", "pw", address="x", mfrs_id=1001)
        fields = protocol._parse_fields(payload)
        self.assertEqual(fields[1][-1], b"u@example.com")
        self.assertEqual(fields[2][-1], b"pw")
        self.assertEqual(fields[3][-1], b"x")
        self.assertEqual(fields[4][-1], 1001)

    def test_login_result_decode(self):
        attrs = (
            protocol._field_uint(1, 42)
            + protocol._field_str(2, "session-token")
            + protocol._field_uint(3, 1)
            + protocol._field_str(4, "Tester")
            + protocol._field_uint(5, 7)
            + protocol._field_str(6, "zh")
        )
        result_payload = (
            protocol._field_uint(1, 0)
            + protocol._field_str(2, "OK")
            + protocol._field_bytes(3, attrs)
        )
        result = protocol.parse_login_result(result_payload)
        self.assertEqual(result["errcode"], 0)
        self.assertEqual(result["errstr"], "OK")
        self.assertEqual(result["attrs"]["uid"], 42)
        self.assertEqual(result["attrs"]["sessionid"], "session-token")
        self.assertEqual(result["attrs"]["nickname"], "Tester")
        self.assertEqual(result["attrs"]["dftDevid"], 7)

    def test_cloud_client_against_local_server(self):
        attrs = protocol._field_uint(1, 42) + protocol._field_str(2, "s") + protocol._field_str(4, "Tester")
        result_payload = protocol._field_uint(1, 0) + protocol._field_str(2, "OK") + protocol._field_bytes(3, attrs)
        response = protocol.build_packet(protocol.OP_USER_LOGIN_RSP, result_payload)

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        seen = {}

        def serve():
            conn, _ = server.accept()
            with conn:
                head = conn.recv(4)
                total = struct.unpack("<I", head)[0]
                body = b""
                while len(body) < total - 4:
                    body += conn.recv(total - 4 - len(body))
                seen["packet"] = head + body
                conn.sendall(response)
            server.close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        result = protocol.CloudClient("127.0.0.1", port, timeout=3).login("u@example.com", "pw")
        thread.join(timeout=3)

        self.assertTrue(result.ok)
        self.assertEqual(result.uid, 42)
        parsed = protocol.parse_packet(seen["packet"])
        self.assertEqual(parsed.opcode, protocol.OP_USER_LOGIN_REQ)
        self.assertEqual(parsed.client_type, 2)


if __name__ == "__main__":
    unittest.main()

