"""HTTP entry point. Every route and page is registered in ROUTES (ADR-0001)."""
from __future__ import annotations

import argparse
import json
import re
import socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from app import pages, returns

Response = tuple[int, str, str]


def error(status: int, code: str, message: str) -> Response:
    return status, "application/json", json.dumps({"error": {"code": code, "message": message}})


def get_returns(order_id: str) -> Response:
    rows = returns.returns_for(order_id)
    if rows is None:
        return error(404, "not_found", f"order {order_id} not found")
    return 200, "application/json", json.dumps({"order_id": order_id, "returns": rows})


def get_order_page(order_id: str) -> Response:
    body = pages.render_order(order_id)
    if body is None:
        return 404, "text/html", "<h1>Not found</h1>"
    return 200, "text/html", body


# (kind, method, path pattern, handler). kind "api" routes are reported to the gate.
ROUTES: list[tuple[str, str, str, Callable[..., Response]]] = [
    ("api", "GET", "/api/orders/{id}/returns", get_returns),
    ("page", "GET", "/orders/{id}", get_order_page),
]


def dispatch(method: str, path: str) -> Response:
    for _, m, pattern, handler in ROUTES:
        rx = "^" + re.sub(r"\{[^}]+\}", r"([^/]+)", pattern) + "$"
        match = re.match(rx, path.split("?", 1)[0])
        if match:
            if m != method:
                return error(405, "method_not_allowed", f"{method} not allowed")
            return handler(*match.groups())
    if path.startswith("/api/"):
        return error(404, "not_found", "no such route")
    return 404, "text/html", "<h1>Not found</h1>"


class Handler(BaseHTTPRequestHandler):
    def _serve(self) -> None:
        if self.path == "/":
            status, ctype, body = 200, "text/plain", "ok"
        else:
            status, ctype, body = dispatch(self.command, self.path)
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve

    def log_message(self, fmt: str, *args: object) -> None:
        pass


class Server(ThreadingHTTPServer):
    """ThreadingHTTPServer without the reverse-DNS lookup in server_bind (~35 s per start on macOS)."""

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    port = ap.parse_args().port
    Server(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
