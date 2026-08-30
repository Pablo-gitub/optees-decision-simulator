"""Streaming HTTPS acquisition transport adapter with strict security boundaries."""

from __future__ import annotations

import hashlib
import http.client
import io
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Protocol

from simulator.application.ports.acquisition_transport import (
    AcquisitionArtifactRequest,
    AcquisitionArtifactResponse,
    AcquisitionTransportPort,
)
from simulator.domain.errors import AcquisitionTransportError

ALLOWED_HOSTS: Final[frozenset[str]] = frozenset({"data.binance.vision"})
ALLOWED_PORT: Final[int] = 443
ALLOWED_PATH_PREFIXES: Final[tuple[str, ...]] = (
    "/data/spot/daily/klines/",
    "/data/spot/monthly/klines/",
)
CHUNK_SIZE: Final[int] = 64 * 1024  # 64 KB streaming chunk

SAFE_FILENAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-zA-Z0-9_.-]+$")


class StreamingHttpResponse(Protocol):
    """Protocol for streaming HTTP responses."""

    @property
    def status_code(self) -> int: ...

    @property
    def headers(self) -> dict[str, str]: ...

    def read_chunk(self, size: int) -> bytes: ...

    def close(self) -> None: ...


class HttpEngine(Protocol):
    """Protocol for abstract HTTP execution engines enabling deterministic testing."""

    def open_request(
        self,
        url: str,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
    ) -> StreamingHttpResponse: ...


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler that blocks automatic redirect following."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: io.BufferedIOBase,
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        # Returning None prevents following redirects and returns the 3xx response to caller
        return None


class StandardHttpEngine(HttpEngine):
    """Production HTTP engine using standard library urllib with redirect-blocking."""

    def __init__(self) -> None:
        opener = urllib.request.build_opener(_NoRedirectHandler)
        self._opener = opener

    def open_request(
        self,
        url: str,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
    ) -> StreamingHttpResponse:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "OpteesDecisionSimulator/1.0",
                "Accept-Encoding": "identity",
            },
        )
        try:
            resp = self._opener.open(req, timeout=connect_timeout_seconds)
            _set_response_read_timeout(resp, read_timeout_seconds)
            return _StandardStreamingResponse(resp)
        except urllib.error.HTTPError as exc:
            # Return HTTP error response for status code evaluation
            _set_response_read_timeout(exc, read_timeout_seconds)
            return _StandardStreamingResponse(exc)


class _StandardStreamingResponse(StreamingHttpResponse):
    """Wraps urllib HTTPResponse into StreamingHttpResponse."""

    def __init__(self, raw_resp: urllib.response.addinfourl | urllib.error.HTTPError) -> None:
        self._resp = raw_resp

    @property
    def status_code(self) -> int:
        return getattr(self._resp, "status", getattr(self._resp, "code", 0))

    @property
    def headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if hasattr(self._resp, "headers") and self._resp.headers:
            for k, v in self._resp.headers.items():
                headers[k.lower()] = v
        return headers

    def read_chunk(self, size: int) -> bytes:
        return self._resp.read(size)

    def close(self) -> None:
        self._resp.close()


@dataclass(frozen=True)
class TransportTimeouts:
    """Configurable timeout boundaries for HTTPS transport."""

    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 30.0
    total_timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        for value in (
            self.connect_timeout_seconds,
            self.read_timeout_seconds,
            self.total_timeout_seconds,
        ):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError("transport timeouts must be finite positive numbers")


class HttpsAcquisitionTransport(AcquisitionTransportPort):
    """Streaming HTTPS acquisition transport adapter enforcing strict allowlists and boundaries."""

    def __init__(
        self,
        engine: HttpEngine | None = None,
        timeouts: TransportTimeouts | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._engine = engine if engine is not None else StandardHttpEngine()
        self._timeouts = timeouts if timeouts is not None else TransportTimeouts()
        self._monotonic = monotonic

    def _validate_request_uri(self, uri: str, expected_filename: str) -> urllib.parse.ParseResult:
        """Enforce URL allowlists, schema, port, path prefix, basename, and forbidden parameters."""
        try:
            parsed = urllib.parse.urlsplit(uri)
        except ValueError as exc:
            raise AcquisitionTransportError(
                "Malformed request URI",
                code="INVALID_URL",
            ) from exc

        if parsed.scheme != "https":
            raise AcquisitionTransportError(
                "Transport only allows https scheme",
                code="INVALID_URL",
            )

        if not parsed.hostname or parsed.hostname.lower() not in ALLOWED_HOSTS:
            raise AcquisitionTransportError(
                "Request host is not allowlisted",
                code="DISALLOWED_HOST",
            )

        try:
            port = parsed.port
        except ValueError as exc:
            raise AcquisitionTransportError(
                "Request port is invalid",
                code="INVALID_URL",
            ) from exc
        if port is not None and port != ALLOWED_PORT:
            raise AcquisitionTransportError(
                "Request port is not allowed",
                code="DISALLOWED_PORT",
            )

        if parsed.username is not None or parsed.password is not None:
            raise AcquisitionTransportError(
                "User credentials in URI are forbidden",
                code="INVALID_URL",
            )

        if parsed.query:
            raise AcquisitionTransportError(
                "Query parameters in URI are forbidden",
                code="INVALID_URL",
            )

        if parsed.fragment:
            raise AcquisitionTransportError(
                "Fragment identifier in URI is forbidden",
                code="INVALID_URL",
            )

        path = urllib.parse.unquote(parsed.path)
        if any(c in path for c in ("..", "\\", "\x00", ":")):
            raise AcquisitionTransportError(
                "Illegal path traversal or separator characters in URI path",
                code="DISALLOWED_PATH",
            )

        if not any(path.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES):
            raise AcquisitionTransportError(
                "Request path prefix is not allowed",
                code="DISALLOWED_PATH",
            )

        basename = path.rsplit("/", 1)[-1]
        if not SAFE_FILENAME_PATTERN.match(basename) or basename != expected_filename:
            raise AcquisitionTransportError(
                "Request basename does not match the expected artifact",
                code="DISALLOWED_PATH",
            )

        return parsed

    def fetch_artifact(self, request: AcquisitionArtifactRequest) -> AcquisitionArtifactResponse:
        """Fetch and validate a single remote data artifact over streaming HTTPS."""
        self._validate_request_uri(request.uri, request.expected_filename)

        started_at = self._monotonic()
        try:
            resp = self._engine.open_request(
                url=request.uri,
                connect_timeout_seconds=min(
                    self._timeouts.connect_timeout_seconds,
                    self._timeouts.total_timeout_seconds,
                ),
                read_timeout_seconds=min(
                    self._timeouts.read_timeout_seconds,
                    self._timeouts.total_timeout_seconds,
                ),
            )
        except urllib.error.URLError as exc:
            reason = str(exc.reason).lower()
            if "timed out" in reason or "timeout" in reason:
                raise AcquisitionTransportError(
                    "Connection or read timed out",
                    code="TIMEOUT",
                ) from exc
            raise AcquisitionTransportError(
                "HTTPS transport connection or TLS failure",
                code="CONNECTION_ERROR",
            ) from exc
        except TimeoutError as exc:
            raise AcquisitionTransportError(
                "Request timed out",
                code="TIMEOUT",
            ) from exc
        except Exception as exc:
            if isinstance(exc, AcquisitionTransportError):
                raise
            raise AcquisitionTransportError(
                "Unexpected transport error during request initialization",
                code="CONNECTION_ERROR",
            ) from exc

        try:
            self._require_total_time_remaining(started_at)
            status = resp.status_code

            # 1. Reject Redirects (3xx)
            if 300 <= status < 400:
                raise AcquisitionTransportError(
                    f"HTTP redirect encountered ({status}); redirects are strictly forbidden",
                    code="REDIRECT_REJECTED",
                )

            # 2. Require HTTP 200 OK
            if status != 200:
                raise AcquisitionTransportError(
                    f"HTTP status error: {status}",
                    code="HTTP_STATUS_ERROR",
                )

            headers = resp.headers

            # 3. Validate Content-Type
            raw_content_type = headers.get("content-type", "")
            # Clean content type (strip charset/boundary)
            clean_content_type = raw_content_type.split(";")[0].strip().lower()
            if not clean_content_type or not any(
                clean_content_type == allowed.lower() for allowed in request.allowed_content_types
            ):
                raise AcquisitionTransportError(
                    "Response Content-Type is not allowed",
                    code="CONTENT_TYPE_MISMATCH",
                )

            # 4. Check declared Content-Length
            declared_len: int | None = None
            if "content-length" in headers:
                raw_len = headers["content-length"].strip()
                try:
                    declared_len = int(raw_len)
                    if declared_len < 0:
                        raise ValueError
                except ValueError as exc:
                    raise AcquisitionTransportError(
                        "Response Content-Length is invalid",
                        code="CONTENT_LENGTH_MISMATCH",
                    ) from exc

                if declared_len > request.max_bytes:
                    raise AcquisitionTransportError(
                        f"Declared Content-Length ({declared_len}) "
                        f"exceeds max_bytes limit ({request.max_bytes})",
                        code="SIZE_LIMIT_EXCEEDED",
                    )

            # 5. Stream response payload with chunked size bounds
            buffer = io.BytesIO()
            total_read = 0

            while True:
                self._require_total_time_remaining(started_at)
                chunk = resp.read_chunk(CHUNK_SIZE)
                self._require_total_time_remaining(started_at)
                if not chunk:
                    break
                total_read += len(chunk)
                if total_read > request.max_bytes:
                    raise AcquisitionTransportError(
                        f"Streamed byte size ({total_read}) "
                        f"exceeds max_bytes limit ({request.max_bytes})",
                        code="SIZE_LIMIT_EXCEEDED",
                    )
                buffer.write(chunk)

            # 6. Verify stream completeness vs declared Content-Length
            if declared_len is not None:
                if total_read < declared_len:
                    raise AcquisitionTransportError(
                        f"Response stream truncated: received {total_read} of {declared_len} bytes",
                        code="RESPONSE_TRUNCATED",
                    )
                if total_read > declared_len:
                    raise AcquisitionTransportError(
                        f"Stream length ({total_read}) "
                        f"exceeded declared Content-Length ({declared_len})",
                        code="CONTENT_LENGTH_MISMATCH",
                    )

            payload_bytes = buffer.getvalue()
            digest = f"sha256:{hashlib.sha256(payload_bytes).hexdigest()}"

            return AcquisitionArtifactResponse(
                content=payload_bytes,
                content_type=clean_content_type,
                byte_size=len(payload_bytes),
                sha256_digest=digest,
            )

        finally:
            resp.close()

    def _require_total_time_remaining(self, started_at: float) -> None:
        if self._monotonic() - started_at > self._timeouts.total_timeout_seconds:
            raise AcquisitionTransportError(
                "Request exceeded total timeout",
                code="TIMEOUT",
            )


def _set_response_read_timeout(response: object, timeout_seconds: float) -> None:
    """Apply the read timeout to urllib's underlying socket when available."""
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    sock = getattr(raw, "_sock", None)
    if sock is not None:
        sock.settimeout(timeout_seconds)
