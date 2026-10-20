"""A minimal HTTPS client for connected services, over the standard library.

One small seam (`Transport`) so tests replace the network entirely (CI never calls Google). Responses are parsed as
JSON when they are JSON; nothing here logs request bodies or headers, because they carry tokens and secrets.

Connections try IPv4 addresses before IPv6, each with a short connect timeout: on networks where IPv6 is advertised
but does not route, the standard library would wait out the full timeout on every request before falling back.
"""

import http.client
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

TIMEOUT_S = 20.0
CONNECT_TIMEOUT_S = 5.0  # per address, so one unreachable address family costs seconds, not the whole timeout


class TransportError(RuntimeError):
    """The service could not be reached (DNS, TLS, timeout, connection reset)."""


@dataclass(frozen=True)
class Response:
    status: int
    body: Any  # parsed JSON, or the raw text when the body is not JSON

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def error_code(self) -> str:
        """Google's error identifier (`invalid_grant`, `rateLimitExceeded`, ...) or the HTTP status."""
        b = self.body
        if isinstance(b, dict):
            err = b.get("error")
            if isinstance(err, str):
                return err
            if isinstance(err, dict):
                reasons = [e.get("reason") for e in err.get("errors", []) if isinstance(e, dict)]
                return next((r for r in reasons if r), None) or str(err.get("status") or self.status)
        return str(self.status)


class Transport(Protocol):
    def request(self, method: str, url: str, *, headers: dict[str, str] | None = None,
                form: dict[str, str] | None = None, json_body: Any = None) -> Response: ...


class UrllibTransport:
    def request(self, method: str, url: str, *, headers: dict[str, str] | None = None,
                form: dict[str, str] | None = None, json_body: Any = None) -> Response:
        hdrs = dict(headers or {})
        data = None
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        elif json_body is not None:
            data = json.dumps(json_body).encode()
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with _OPENER.open(req, timeout=TIMEOUT_S) as res:
                return Response(res.status, _parse(res.read()))
        except urllib.error.HTTPError as exc:
            return Response(exc.code, _parse(exc.read()))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(type(exc).__name__) from None


def connect_ipv4_first(address: tuple[str, int], timeout: Any = None,
                       source_address: tuple[str, int] | None = None) -> socket.socket:
    """Open a TCP connection, trying every IPv4 address before any IPv6 one. Each attempt gets at most
    CONNECT_TIMEOUT_S; the returned socket uses `timeout` for reads."""
    host, port = address
    timeout = timeout if isinstance(timeout, (int, float)) else None
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    infos.sort(key=lambda info: info[0] != socket.AF_INET)  # stable: keeps the resolver's order within a family
    last: OSError | None = None
    for family, kind, proto, _, addr in infos:
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(CONNECT_TIMEOUT_S if timeout is None else min(CONNECT_TIMEOUT_S, timeout))
            if source_address:
                sock.bind(source_address)
            sock.connect(addr)
            sock.settimeout(timeout)
            return sock
        except OSError as exc:
            last = exc
            sock.close()
    raise last or OSError(f"no addresses for {host}")


class _HTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = connect_ipv4_first


class _HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = connect_ipv4_first


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(_HTTPConnection, req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req: urllib.request.Request) -> Any:
        return self.do_open(_HTTPSConnection, req, context=self._context)


_OPENER = urllib.request.build_opener(_HTTPHandler(), _HTTPSHandler())


def _parse(raw: bytes) -> Any:
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return text
