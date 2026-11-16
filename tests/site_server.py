"""A tiny local website for end-to-end tests."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def page(title: str, body: str, *, head: str = "", desc: str = "A clear description of this page.",
         canonical: str = "") -> str:
    canon = f'<link rel="canonical" href="{canonical}">' if canonical else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{title}</title><meta name=\"description\" content=\"{desc}\">{canon}{head}"
            f"</head><body>{body}</body></html>")


class Site:
    """routes: path -> (status, headers dict, body str)."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.hits: list[str] = []
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                site.hits.append(self.path)
                status, headers, body = site.routes.get(self.path, (404, {}, "not found"))
                data = body.encode() if isinstance(body, str) else body
                self.send_response(status)
                headers = {"Content-Type": "text/html; charset=utf-8", **headers}
                for k, v in headers.items():
                    self.send_header(k, v.replace("{base}", site.base) if isinstance(v, str) else v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
