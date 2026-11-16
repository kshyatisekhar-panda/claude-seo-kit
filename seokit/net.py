"""Safe HTTP fetching.

Every request target is resolved once, every resolved address must be a public
unicast address, and the TCP connection is opened to exactly the address that
was checked. That closes the gap where a hostname passes the check and then
resolves somewhere else (DNS rebinding). Redirects are followed by hand so
each hop gets the same check.

Local development servers are allowed only when the user names them in
SEOKIT_ALLOW_HOSTS, e.g. "localhost:3000,127.0.0.1:4321".
"""

from __future__ import annotations

import ipaddress
import os
import socket
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection, HTTPSConnection
from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool
from urllib3.exceptions import NewConnectionError
from urllib3.util.connection import create_connection

from . import __version__

USER_AGENT = f"ClaudeSEOKit/{__version__} (+https://github.com/kshyatisekhar-panda/claude-seo-kit)"
MAX_BYTES = 5_000_000
REDIRECT_CODES = {301, 302, 303, 307, 308}


class BlockedURL(ValueError):
    """The URL points somewhere this tool must not connect to."""


# ---------------------------------------------------------------- validation

def _allowed_local() -> set[tuple[str, Optional[int]]]:
    out = set()
    for item in os.environ.get("SEOKIT_ALLOW_HOSTS", "").split(","):
        item = item.strip().lower()
        if not item:
            continue
        host, _, port = item.rpartition(":") if item.count(":") == 1 else (item, "", "")
        try:
            out.add((host, int(port)) if port else (item, None))
        except ValueError:
            continue
    return out


def is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value.split("%", 1)[0])
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.version == 6 and ip.sixtofour:
        ip = ip.sixtofour
    return ip.is_global and not ip.is_multicast


def check_url(url: str) -> tuple[str, int, str]:
    """Validate a URL and return (host, port, ip) to connect to."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise BlockedURL(f"malformed URL: {exc}") from None
    if parts.scheme not in ("http", "https"):
        raise BlockedURL(f"only http and https are allowed, not {parts.scheme or 'none'}")
    if parts.username or parts.password:
        raise BlockedURL("URLs with credentials are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise BlockedURL("URL has no host")
    port = port or (443 if parts.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise BlockedURL(f"cannot resolve {host}: {exc}") from None
    ips = list(dict.fromkeys(info[4][0] for info in infos))
    if not ips:
        raise BlockedURL(f"{host} has no addresses")
    allowed = _allowed_local()
    if (host, port) in allowed or (host, None) in allowed:
        return host, port, ips[0]
    bad = [ip for ip in ips if not is_public_ip(ip)]
    if bad:
        raise BlockedURL(f"{host} resolves to a non-public address ({bad[0]})")
    return host, port, ips[0]


# ---------------------------------------------------------------- pinned transport

class _PinnedAdapter(HTTPAdapter):
    """Opens each connection to the IP address that check_url approved."""

    def __init__(self) -> None:
        self.pins: dict[tuple[str, int], str] = {}
        super().__init__(max_retries=0)

    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        pins = self.pins

        def pinned(base):
            class Conn(base):
                def _new_conn(self):  # noqa: D401
                    key = (self._dns_host.rstrip(".").lower(), self.port)
                    ip = pins.get(key)
                    if ip is None:
                        raise NewConnectionError(self, f"connection to unchecked host {key[0]}")
                    try:
                        return create_connection((ip, self.port), self.timeout,
                                                 source_address=self.source_address,
                                                 socket_options=self.socket_options)
                    except OSError as exc:
                        raise NewConnectionError(self, f"failed to connect: {exc}") from exc
            return Conn

        http_conn, https_conn = pinned(HTTPConnection), pinned(HTTPSConnection)

        class HttpPool(HTTPConnectionPool):
            ConnectionCls = http_conn

        class HttpsPool(HTTPSConnectionPool):
            ConnectionCls = https_conn

        self.poolmanager.pool_classes_by_scheme = {"http": HttpPool, "https": HttpsPool}
        self.poolmanager.key_fn_by_scheme = dict(self.poolmanager.key_fn_by_scheme)


def new_session() -> tuple[requests.Session, _PinnedAdapter]:
    s = requests.Session()
    s.trust_env = False  # a proxy would bypass the address pin
    adapter = _PinnedAdapter()
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en,*;q=0.5"})
    return s, adapter


# ---------------------------------------------------------------- fetch

@dataclass
class Response:
    url: str
    final_url: str = ""
    status: Optional[int] = None
    headers: dict = field(default_factory=dict)
    body: bytes = b""
    text: str = ""
    redirects: list = field(default_factory=list)  # [(url, status)]
    elapsed_ms: int = 0
    truncated: bool = False
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status is not None and 200 <= self.status < 300

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")


def _decode(body: bytes, content_type: str) -> str:
    charset = None
    for part in content_type.split(";")[1:]:
        k, _, v = part.strip().partition("=")
        if k.lower() == "charset":
            charset = v.strip("\"' ")
    for enc in (charset, "utf-8"):
        if enc:
            try:
                return body.decode(enc)
            except (LookupError, UnicodeDecodeError):
                continue
    return body.decode("latin-1", errors="replace")


def fetch(url: str, *, timeout: float = 20, max_redirects: int = 5, max_bytes: int = MAX_BYTES,
          method: str = "GET", user_agent: Optional[str] = None,
          session: Optional[tuple[requests.Session, _PinnedAdapter]] = None) -> Response:
    """Fetch a URL safely. Never raises for network problems; see Response.error."""
    sess, adapter = session or new_session()
    res = Response(url=url)
    current = url
    started = time.monotonic()
    headers = {"User-Agent": user_agent} if user_agent else {}
    try:
        for _ in range(max_redirects + 1):
            host, port, ip = check_url(current)
            adapter.pins[(host, port)] = ip
            r = sess.request(method, current, headers=headers, timeout=timeout,
                             allow_redirects=False, stream=True)
            if r.status_code in REDIRECT_CODES and r.headers.get("Location"):
                res.redirects.append((current, r.status_code))
                r.close()
                current = urljoin(current, r.headers["Location"])
                continue
            chunks, size = [], 0
            if method != "HEAD":
                for chunk in r.iter_content(65536):
                    size += len(chunk)
                    if size > max_bytes:
                        res.truncated = True
                        chunks.append(chunk[: max_bytes - (size - len(chunk))])
                        break
                    chunks.append(chunk)
            r.close()
            res.final_url = current
            res.status = r.status_code
            res.headers = {k.lower(): v for k, v in r.headers.items()}
            res.body = b"".join(chunks)
            res.text = _decode(res.body, res.header("content-type"))
            break
        else:
            res.final_url = current
            res.error = f"more than {max_redirects} redirects"
    except BlockedURL as exc:
        res.error = f"blocked: {exc}"
    except requests.RequestException as exc:
        res.error = f"{type(exc).__name__}: {exc}"
    res.elapsed_ms = int((time.monotonic() - started) * 1000)
    return res
