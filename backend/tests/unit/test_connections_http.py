"""The connected-services HTTP client: IPv4 is tried before IPv6, and a dead address costs one short connect timeout."""

import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.connections import http as http_mod
from app.connections.http import TransportError, UrllibTransport, connect_ipv4_first

V6 = (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2001:db8::1", 443, 0, 0))
V4 = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))


class FakeSocket:
    def __init__(self, log: list, dead: set, family: int, *_: object) -> None:
        self.log, self.dead, self.family, self.timeouts, self.closed = log, dead, family, [], False

    def settimeout(self, t: float | None) -> None:
        self.timeouts.append(t)

    def bind(self, _: object) -> None:
        pass

    def connect(self, addr: tuple) -> None:
        self.log.append(addr[0])
        if addr[0] in self.dead:
            raise TimeoutError("timed out")

    def close(self) -> None:
        self.closed = True


def _patch(monkeypatch: pytest.MonkeyPatch, infos: list, dead: set) -> list:
    log: list = []
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: list(infos))
    monkeypatch.setattr(socket, "socket", lambda family, *rest: FakeSocket(log, dead, family, *rest))
    return log


def test_ipv4_is_tried_before_ipv6(monkeypatch: pytest.MonkeyPatch) -> None:
    log = _patch(monkeypatch, [V6, V4], dead=set())
    sock = connect_ipv4_first(("example.test", 443), 20.0)
    assert log == ["192.0.2.1"]
    assert sock.family == socket.AF_INET
    assert sock.timeouts == [http_mod.CONNECT_TIMEOUT_S, 20.0]  # short connect, full timeout for reads


def test_falls_back_to_ipv6_when_ipv4_is_dead(monkeypatch: pytest.MonkeyPatch) -> None:
    log = _patch(monkeypatch, [V6, V4], dead={"192.0.2.1"})
    sock = connect_ipv4_first(("example.test", 443), 20.0)
    assert log == ["192.0.2.1", "2001:db8::1"]
    assert sock.family == socket.AF_INET6


def test_all_addresses_dead_raises_the_last_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, [V6, V4], dead={"192.0.2.1", "2001:db8::1"})
    with pytest.raises(TimeoutError):
        connect_ipv4_first(("example.test", 443), 20.0)


def test_transport_round_trip_through_the_ipv4_first_opener() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        res = UrllibTransport().request("GET", f"http://localhost:{server.server_port}/")  # localhost may list ::1 first
        assert res.ok and res.body == {"ok": True}
    finally:
        server.shutdown()
        server.server_close()


def test_unreachable_service_is_a_transport_error() -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # nothing listens here once the socket closes
    with pytest.raises(TransportError):
        UrllibTransport().request("GET", f"http://127.0.0.1:{port}/")
