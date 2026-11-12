"""Exercise the real pipe protocol without a socket or a guest image."""
import json
import os
import threading
import time
import unittest

from nexuslib.core import NexusError
from nexuslib.qemu import QMP


class Peer:
    def __init__(self, mode="normal"):
        client_read, server_write = os.pipe()
        server_read, client_write = os.pipe()
        self.reader = os.fdopen(client_read, "rb", buffering=0)
        self.writer = os.fdopen(client_write, "wb", buffering=0)
        self.server_read = os.fdopen(server_read, "rb", buffering=0)
        self.server_write = os.fdopen(server_write, "wb", buffering=0)
        self.mode = mode
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def send(self, message):
        self.server_write.write(json.dumps(message).encode() + b"\r\n")

    def serve(self):
        try:
            if self.mode == "malformed":
                self.server_write.write(b"not-json\n")
                return
            if self.mode == "bad-greeting":
                self.send({"other": True})
                return
            if self.mode == "eof":
                return
            self.send({"QMP": {"version": "fixture"}})
            for line in self.server_read:
                request = json.loads(line)
                if request["execute"] == "qmp_capabilities":
                    self.send({"return": {}, "id": request["id"]})
                    continue
                if self.mode == "timeout":
                    time.sleep(0.2)
                elif self.mode == "error":
                    self.send({"error": {"class": "CommandNotFound"}, "id": request["id"]})
                else:
                    self.send({"event": "RESUME"})
                    self.send({"return": {"stale": True}, "id": request["id"] - 1})
                    data = json.dumps({"return": {"status": "running"}, "id": request["id"]}).encode() + b"\n"
                    self.server_write.write(data[:6])
                    self.server_write.write(data[6:])
        except (BrokenPipeError, OSError):
            pass
        finally:
            self.server_read.close()
            self.server_write.close()

    def close(self):
        self.reader.close()
        self.writer.close()
        self.thread.join(timeout=1)


class QMPTests(unittest.TestCase):
    def test_events_wrong_ids_and_fragmented_response(self):
        peer = Peer()
        try:
            qmp = QMP(peer.reader, peer.writer)
            self.assertEqual(qmp.command("query-status"), {"status": "running"})
        finally:
            peer.close()

    def test_reported_qmp_error(self):
        peer = Peer("error")
        try:
            qmp = QMP(peer.reader, peer.writer)
            with self.assertRaisesRegex(NexusError, "CommandNotFound"):
                qmp.command("unsupported")
        finally:
            peer.close()

    def test_response_timeout(self):
        peer = Peer("timeout")
        try:
            qmp = QMP(peer.reader, peer.writer)
            with self.assertRaises(TimeoutError):
                qmp.command("query-status", timeout=0.03)
        finally:
            peer.close()

    def test_invalid_greeting_and_eof(self):
        for mode in ("malformed", "bad-greeting", "eof"):
            peer = Peer(mode)
            try:
                with self.subTest(mode=mode), self.assertRaises(NexusError):
                    QMP(peer.reader, peer.writer)
            finally:
                peer.close()
