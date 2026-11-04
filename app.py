"""Python CRUD REST API - Hands-On Praktikum CI/CD (Jenkins, GitHub, Docker, ngrok).

Endpoint:
    GET    /health               status service
    GET    /messages             daftar pesan (opsional filter ?q=kata)
    GET    /messages/{id}        satu pesan berdasarkan id
    POST   /messages             tambah pesan, body JSON {"message": "..."}
    DELETE /messages?index=X     hapus pesan pada index X

Data disimpan di file JSON pada direktori yang dipasang ke Docker named volume.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import json
import os
import threading

DATA_FILE = Path(os.getenv(
    "DATA_FILE", "/var/lib/backend_data/messages.json"
))
PORT = int(os.getenv("PORT", "5000"))
APP_VERSION = os.getenv("APP_VERSION", "dev")
MAX_MESSAGE_LENGTH = 500

LOCK = threading.Lock()


def read_messages():
    if not DATA_FILE.exists():
        return []
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def write_messages(messages):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = DATA_FILE.with_suffix(".tmp")
    tmp_file.write_text(
        json.dumps(messages, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    tmp_file.replace(DATA_FILE)


def next_id(messages):
    return max((m.get("id", 0) for m in messages), default=0) + 1


def save_message(message):
    with LOCK:
        messages = read_messages()
        item = {
            "id": next_id(messages),
            "message": message,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        messages.append(item)
        write_messages(messages)
    return item


class APIHandler(BaseHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def route(self):
        parsed = urlparse(self.path)
        return parsed.path.rstrip("/") or "/", parse_qs(parsed.query)

    def do_OPTIONS(self):
        self.send_json(200, {"status": "ok"})

    def do_GET(self):
        path, query = self.route()
        if path in ("/", "/health"):
            return self.send_json(200, {
                "status": "active", "service": "Backend API",
                "version": APP_VERSION
            })
        if path == "/messages":
            messages = read_messages()
            keyword = query.get("q", [""])[0].strip().lower()
            if keyword:
                messages = [m for m in messages
                            if keyword in str(m.get("message", "")).lower()]
            return self.send_json(200, {
                "messages": messages, "total": len(messages)
            })
        if path.startswith("/messages/"):
            raw_id = path[len("/messages/"):]
            try:
                message_id = int(raw_id)
            except ValueError:
                return self.send_json(400, {"error": "id must be an integer"})
            for item in read_messages():
                if item.get("id") == message_id:
                    return self.send_json(200, item)
            return self.send_json(404, {"error": "Message not found"})
        return self.send_json(404, {"error": "Endpoint not found"})

    def do_POST(self):
        path, _ = self.route()
        if path != "/messages":
            return self.send_json(404, {"error": "Endpoint not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                return self.send_json(400, {"error": "Request body must be a JSON object"})
            message = str(payload.get("message", "")).strip()
            if not message:
                return self.send_json(400, {"error": "message must not be empty"})
            if len(message) > MAX_MESSAGE_LENGTH:
                return self.send_json(400, {
                    "error": "message must be 500 characters or fewer"
                })
            return self.send_json(201, {
                "status": "created", "message": save_message(message)
            })
        except (ValueError, UnicodeDecodeError):
            return self.send_json(400, {"error": "Invalid JSON request body"})

    def do_DELETE(self):
        path, query = self.route()
        if path != "/messages":
            return self.send_json(404, {"error": "Endpoint not found"})
        if "index" not in query:
            return self.send_json(400, {"error": "Missing index parameter"})
        try:
            index = int(query["index"][0])
        except ValueError:
            return self.send_json(400, {"error": "Index must be an integer"})
        with LOCK:
            messages = read_messages()
            if index < 0 or index >= len(messages):
                return self.send_json(404, {"error": "Message not found"})
            removed = messages.pop(index)
            write_messages(messages)
        return self.send_json(200, {"status": "deleted", "removed": removed})

    def log_message(self, fmt, *args):
        print(f"[{self.log_date_time_string()}] {fmt % args}", flush=True)


if __name__ == "__main__":
    print(f"Backend API {APP_VERSION} listening on 0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), APIHandler).serve_forever()
