"""Unit tests for HttpsAcquisitionTransport adapter (DS-02C3 / Gate DS-D2C)."""

from __future__ import annotations

import io
import urllib.error

import pytest

from simulator.application.ports.acquisition_transport import AcquisitionArtifactRequest
from simulator.domain.errors import AcquisitionTransportError
from simulator.infrastructure.adapters.https_acquisition_transport import (
    HttpsAcquisitionTransport,
    StreamingHttpResponse,
)


class FakeStreamingResponse(StreamingHttpResponse):
    """Deterministic fake streaming HTTP response."""

    def __init__(
        self,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        body: bytes = b"",
        chunk_size: int = 64 * 1024,
    ) -> None:
        self._status_code = status_code
        self._headers = headers or {}
        self._stream = io.BytesIO(body)
        self._chunk_size = chunk_size
        self.closed = False

    @property
    def status_code(self) -> int:
        return self._status_code

    @property
    def headers(self) -> dict[str, str]:
        return self._headers

    def read_chunk(self, size: int) -> bytes:
        return self._stream.read(size)

    def close(self) -> None:
        self.closed = True


class FakeHttpEngine:
    """Deterministic in-memory HTTP engine stub."""

    def __init__(
        self,
        response_factory: FakeStreamingResponse | Exception | None = None,
    ) -> None:
        self.response_factory = response_factory
        self.requested_urls: list[str] = []

    def open_request(
        self,
        url: str,
        timeout_seconds: float,
    ) -> StreamingHttpResponse:
        self.requested_urls.append(url)
        if isinstance(self.response_factory, Exception):
            raise self.response_factory
        if self.response_factory is None:
            return FakeStreamingResponse(status_code=200, body=b"OK")
        return self.response_factory


def test_successful_fetch_zip_artifact() -> None:
    body = b"PK\x03\x04VALID_ZIP_BYTES"
    headers = {
        "content-type": "application/zip",
        "content-length": str(len(body)),
    }
    engine = FakeHttpEngine(FakeStreamingResponse(200, headers, body))
    transport = HttpsAcquisitionTransport(engine=engine)

    req = AcquisitionArtifactRequest(
        uri="https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip",
        expected_filename="BTCUSDT-1d-2024-01-01.zip",
        max_bytes=1024,
        allowed_content_types=("application/zip",),
    )

    resp = transport.fetch_artifact(req)
    assert resp.content == body
    assert resp.byte_size == len(body)
    assert resp.content_type == "application/zip"
    assert resp.sha256_digest.startswith("sha256:")
    assert engine.requested_urls == [req.uri]


def test_url_validation_rejections() -> None:
    transport = HttpsAcquisitionTransport(engine=FakeHttpEngine())

    # 1. Scheme not https
    with pytest.raises(AcquisitionTransportError) as exc1:
        transport.fetch_artifact(
            AcquisitionArtifactRequest(
                uri="http://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip",
                expected_filename="BTCUSDT-1d-2024-01-01.zip",
                max_bytes=1024,
                allowed_content_types=("application/zip",),
            )
        )
    assert exc1.value.code == "INVALID_URL"

    # 2. Host not in allowlist
    with pytest.raises(AcquisitionTransportError) as exc2:
        transport.fetch_artifact(
            AcquisitionArtifactRequest(
                uri="https://evil.com/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip",
                expected_filename="BTCUSDT-1d-2024-01-01.zip",
                max_bytes=1024,
                allowed_content_types=("application/zip",),
            )
        )
    assert exc2.value.code == "DISALLOWED_HOST"

    # 3. Disallowed port
    with pytest.raises(AcquisitionTransportError) as exc3:
        transport.fetch_artifact(
            AcquisitionArtifactRequest(
                uri="https://data.binance.vision:8080/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip",
                expected_filename="BTCUSDT-1d-2024-01-01.zip",
                max_bytes=1024,
                allowed_content_types=("application/zip",),
            )
        )
    assert exc3.value.code == "DISALLOWED_PORT"

    # 4. User credentials in URI
    with pytest.raises(AcquisitionTransportError) as exc4:
        transport.fetch_artifact(
            AcquisitionArtifactRequest(
                uri="https://user:pass@data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip",
                expected_filename="BTCUSDT-1d-2024-01-01.zip",
                max_bytes=1024,
                allowed_content_types=("application/zip",),
            )
        )
    assert exc4.value.code == "INVALID_URL"

    # 5. Query params in URI
    with pytest.raises(AcquisitionTransportError) as exc5:
        transport.fetch_artifact(
            AcquisitionArtifactRequest(
                uri="https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip?key=123",
                expected_filename="BTCUSDT-1d-2024-01-01.zip",
                max_bytes=1024,
                allowed_content_types=("application/zip",),
            )
        )
    assert exc5.value.code == "INVALID_URL"

    # 6. Fragment in URI
    with pytest.raises(AcquisitionTransportError) as exc6:
        transport.fetch_artifact(
            AcquisitionArtifactRequest(
                uri="https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip#frag",
                expected_filename="BTCUSDT-1d-2024-01-01.zip",
                max_bytes=1024,
                allowed_content_types=("application/zip",),
            )
        )
    assert exc6.value.code == "INVALID_URL"

    # 7. Path traversal
    with pytest.raises(AcquisitionTransportError) as exc7:
        transport.fetch_artifact(
            AcquisitionArtifactRequest(
                uri="https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/../BTCUSDT-1d-2024-01-01.zip",
                expected_filename="BTCUSDT-1d-2024-01-01.zip",
                max_bytes=1024,
                allowed_content_types=("application/zip",),
            )
        )
    assert exc7.value.code == "DISALLOWED_PATH"

    # 8. Disallowed path prefix
    with pytest.raises(AcquisitionTransportError) as exc8:
        transport.fetch_artifact(
            AcquisitionArtifactRequest(
                uri="https://data.binance.vision/api/v3/klines/BTCUSDT-1d-2024-01-01.zip",
                expected_filename="BTCUSDT-1d-2024-01-01.zip",
                max_bytes=1024,
                allowed_content_types=("application/zip",),
            )
        )
    assert exc8.value.code == "DISALLOWED_PATH"

    # 9. Basename mismatch
    with pytest.raises(AcquisitionTransportError) as exc9:
        transport.fetch_artifact(
            AcquisitionArtifactRequest(
                uri="https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/OTHER-1d-2024-01-01.zip",
                expected_filename="BTCUSDT-1d-2024-01-01.zip",
                max_bytes=1024,
                allowed_content_types=("application/zip",),
            )
        )
    assert exc9.value.code == "DISALLOWED_PATH"


def test_redirect_rejected() -> None:
    headers = {"location": "https://data.binance.vision/redirected.zip"}
    engine = FakeHttpEngine(FakeStreamingResponse(302, headers, b""))
    transport = HttpsAcquisitionTransport(engine=engine)

    req = AcquisitionArtifactRequest(
        uri="https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip",
        expected_filename="BTCUSDT-1d-2024-01-01.zip",
        max_bytes=1024,
        allowed_content_types=("application/zip",),
    )

    with pytest.raises(AcquisitionTransportError) as exc_info:
        transport.fetch_artifact(req)
    assert exc_info.value.code == "REDIRECT_REJECTED"


def test_http_status_error() -> None:
    engine = FakeHttpEngine(FakeStreamingResponse(404, {}, b"Not Found"))
    transport = HttpsAcquisitionTransport(engine=engine)

    req = AcquisitionArtifactRequest(
        uri="https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip",
        expected_filename="BTCUSDT-1d-2024-01-01.zip",
        max_bytes=1024,
        allowed_content_types=("application/zip",),
    )

    with pytest.raises(AcquisitionTransportError) as exc_info:
        transport.fetch_artifact(req)
    assert exc_info.value.code == "HTTP_STATUS_ERROR"


def test_content_type_mismatch() -> None:
    headers = {"content-type": "text/html"}
    engine = FakeHttpEngine(FakeStreamingResponse(200, headers, b"<html></html>"))
    transport = HttpsAcquisitionTransport(engine=engine)

    req = AcquisitionArtifactRequest(
        uri="https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip",
        expected_filename="BTCUSDT-1d-2024-01-01.zip",
        max_bytes=1024,
        allowed_content_types=("application/zip",),
    )

    with pytest.raises(AcquisitionTransportError) as exc_info:
        transport.fetch_artifact(req)
    assert exc_info.value.code == "CONTENT_TYPE_MISMATCH"


def test_size_limit_exceeded_declared_content_length() -> None:
    headers = {
        "content-type": "application/zip",
        "content-length": "2048",
    }
    engine = FakeHttpEngine(FakeStreamingResponse(200, headers, b"a" * 2048))
    transport = HttpsAcquisitionTransport(engine=engine)

    req = AcquisitionArtifactRequest(
        uri="https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip",
        expected_filename="BTCUSDT-1d-2024-01-01.zip",
        max_bytes=1024,  # limit is 1024 < 2048
        allowed_content_types=("application/zip",),
    )

    with pytest.raises(AcquisitionTransportError) as exc_info:
        transport.fetch_artifact(req)
    assert exc_info.value.code == "SIZE_LIMIT_EXCEEDED"


def test_size_limit_exceeded_during_streaming() -> None:
    # No Content-Length header, but streamed body exceeds limit
    headers = {"content-type": "application/zip"}
    engine = FakeHttpEngine(FakeStreamingResponse(200, headers, b"x" * 2000))
    transport = HttpsAcquisitionTransport(engine=engine)

    req = AcquisitionArtifactRequest(
        uri="https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip",
        expected_filename="BTCUSDT-1d-2024-01-01.zip",
        max_bytes=1000,
        allowed_content_types=("application/zip",),
    )

    with pytest.raises(AcquisitionTransportError) as exc_info:
        transport.fetch_artifact(req)
    assert exc_info.value.code == "SIZE_LIMIT_EXCEEDED"


def test_response_truncated_vs_declared_content_length() -> None:
    headers = {
        "content-type": "application/zip",
        "content-length": "500",
    }
    # Body is only 200 bytes while declared is 500
    engine = FakeHttpEngine(FakeStreamingResponse(200, headers, b"x" * 200))
    transport = HttpsAcquisitionTransport(engine=engine)

    req = AcquisitionArtifactRequest(
        uri="https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip",
        expected_filename="BTCUSDT-1d-2024-01-01.zip",
        max_bytes=1000,
        allowed_content_types=("application/zip",),
    )

    with pytest.raises(AcquisitionTransportError) as exc_info:
        transport.fetch_artifact(req)
    assert exc_info.value.code == "RESPONSE_TRUNCATED"


def test_connection_error_and_timeout() -> None:
    # 1. Timeout error
    engine_timeout = FakeHttpEngine(TimeoutError("timed out"))
    transport_timeout = HttpsAcquisitionTransport(engine=engine_timeout)

    req = AcquisitionArtifactRequest(
        uri="https://data.binance.vision/data/spot/daily/klines/BTCUSDT/1d/BTCUSDT-1d-2024-01-01.zip",
        expected_filename="BTCUSDT-1d-2024-01-01.zip",
        max_bytes=1000,
        allowed_content_types=("application/zip",),
    )

    with pytest.raises(AcquisitionTransportError) as exc1:
        transport_timeout.fetch_artifact(req)
    assert exc1.value.code == "TIMEOUT"

    # 2. URLError (TLS / connection reset)
    engine_conn = FakeHttpEngine(urllib.error.URLError("Connection refused"))
    transport_conn = HttpsAcquisitionTransport(engine=engine_conn)

    with pytest.raises(AcquisitionTransportError) as exc2:
        transport_conn.fetch_artifact(req)
    assert exc2.value.code == "CONNECTION_ERROR"
