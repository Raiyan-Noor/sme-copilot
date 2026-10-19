"""A minimal HTTPS client for connected services, over the standard library.

One small seam (`Transport`) so tests replace the network entirely (CI never calls Google). Responses are parsed as
JSON when they are JSON; nothing here logs request bodies or headers, because they carry tokens and secrets.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

TIMEOUT_S = 20.0


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
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as res:
                return Response(res.status, _parse(res.read()))
        except urllib.error.HTTPError as exc:
            return Response(exc.code, _parse(exc.read()))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(type(exc).__name__) from None


def _parse(raw: bytes) -> Any:
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return text
