"""Test otomatis untuk health check, validasi POST, dan CRUD.

Jalankan: python3 -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

os.environ["DATA_FILE"] = os.path.join(tempfile.mkdtemp(), "messages.json")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app  # noqa: E402


class APITest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.APIHandler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        app.write_messages([])

    def request(self, method, path, body=None, raw=None):
        data = raw if raw is not None else (
            json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    def test_health(self):
        status, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "active")

    def test_post_validation(self):
        self.assertEqual(self.request("POST", "/messages", {"message": ""})[0], 400)
        self.assertEqual(self.request("POST", "/messages", {"message": "   "})[0], 400)
        self.assertEqual(self.request("POST", "/messages", {"message": "x" * 501})[0], 400)
        self.assertEqual(self.request("POST", "/messages", raw=b"{not json")[0], 400)
        self.assertEqual(self.request("POST", "/messages", ["list"])[0], 400)

    def test_crud_flow(self):
        status, body = self.request("POST", "/messages", {"message": "Pesan pertama"})
        self.assertEqual(status, 201)
        self.assertIn("created_at", body["message"])
        self.request("POST", "/messages", {"message": "Pesan kedua"})

        status, body = self.request("GET", "/messages")
        self.assertEqual((status, body["total"]), (200, 2))

        status, body = self.request("DELETE", "/messages?index=0")
        self.assertEqual(status, 200)
        self.assertEqual(body["removed"]["message"], "Pesan pertama")
        self.assertEqual(self.request("DELETE", "/messages?index=999")[0], 404)
        self.assertEqual(self.request("DELETE", "/messages")[0], 400)
        self.assertEqual(self.request("DELETE", "/messages?index=abc")[0], 400)

    def test_get_by_id_and_filter(self):
        self.request("POST", "/messages", {"message": "Halo Jenkins"})
        _, created = self.request("POST", "/messages", {"message": "Halo Docker"})
        message_id = created["message"]["id"]

        status, body = self.request("GET", f"/messages/{message_id}")
        self.assertEqual((status, body["message"]), (200, "Halo Docker"))
        self.assertEqual(self.request("GET", "/messages/999")[0], 404)
        self.assertEqual(self.request("GET", "/messages/abc")[0], 400)

        _, body = self.request("GET", "/messages?q=docker")
        self.assertEqual(body["total"], 1)

    def test_unknown_endpoint(self):
        self.assertEqual(self.request("GET", "/unknown")[0], 404)


if __name__ == "__main__":
    unittest.main()
