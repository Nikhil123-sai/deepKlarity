import json
import os
import sqlite3
import threading
from urllib.parse import urlparse
from wsgiref.util import setup_testing_defaults

from tillpoint import db
from tillpoint.api import App

DB_PATH = os.environ.get("TILLPOINT_DB_PATH", ":memory:")
_lock = threading.Lock()
_conn = None
_app = None


def get_app():
    global _conn, _app
    with _lock:
        if _conn is None:
            _conn = db.connect(DB_PATH)
            if DB_PATH == ":memory:":
                _conn.close()
                _conn = sqlite3.connect(":memory:", check_same_thread=False)
                _conn.row_factory = sqlite3.Row
                db.init_schema(_conn)
        if _app is None:
            _app = App(_conn)
    return _app


def wsgi_app(environ, start_response):
    setup_testing_defaults(environ)
    method = environ["REQUEST_METHOD"].upper()
    path = environ.get("PATH_INFO", "/")
    query_string = environ.get("QUERY_STRING", "")
    full_path = f"{path}?{query_string}" if query_string else path

    length = int(environ.get("CONTENT_LENGTH") or 0)
    raw_body = environ["wsgi.input"].read(length).decode("utf-8") if length > 0 else ""

    if path == "/" and method == "GET":
        payload = json.dumps({
            "service": "tillpoint-order-desk",
            "status": "ok",
            "platform": "render",
            "endpoints": ["/health", "/orders", "/products", "/webhooks/payments", "/reports/daily"],
        }).encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(payload))),
        ])
        return [payload]

    if path == "/health" and method == "GET":
        payload = json.dumps({"status": "healthy"}).encode("utf-8")
        start_response("200 OK", [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(payload))),
        ])
        return [payload]

    body = None
    if raw_body:
        try:
            body = json.loads(raw_body)
        except json.JSONDecodeError:
            body = raw_body

    with _lock:
        app = get_app()
        parsed = urlparse(full_path)
        status_code, data = app.handle(method, parsed.path, body=body)

    payload = json.dumps(data if data is not None else {}).encode("utf-8")
    status_map = {
        200: "200 OK",
        201: "201 Created",
        400: "400 Bad Request",
        404: "404 Not Found",
        409: "409 Conflict",
        422: "422 Unprocessable Entity",
        500: "500 Internal Server Error",
    }
    status_text = status_map.get(status_code, f"{status_code} OK")
    start_response(status_text, [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(payload))),
    ])
    return [payload]


if __name__ == "__main__":
    from wsgiref.simple_server import make_server

    port = int(os.environ.get("PORT", "8000"))
    print(f"Serving Tillpoint on http://127.0.0.1:{port}")
    with make_server("0.0.0.0", port, wsgi_app) as httpd:
        httpd.serve_forever()
