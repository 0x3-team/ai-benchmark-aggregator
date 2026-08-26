from __future__ import annotations

from dataclasses import replace
import ssl
from typing import Callable

import pytest

from app.config import Settings
from app.ingestion import live_transport, safe_fetch
from app.ingestion.live_transport import (
    PinnedHTTPSFetchTransport,
    _PinnedHTTPSConnection,
    _RequestDeadline,
)
from app.ingestion.safe_fetch import (
    DisabledNetworkTransport,
    FetchPlan,
    SafeFetchClient,
    SafeFetchError,
)
from app.runtime.dependencies import (
    RuntimeCapability,
    RuntimeDependencies,
    RuntimeDependencyError,
    contained_runtime_dependencies,
)


URL = "https://official.example/results.json"
REQUEST_HEADERS = {"Accept": "application/json", "User-Agent": "transport-test/1"}


class ScriptedResponse:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: list[tuple[str, str]] | None = None,
        max_chunk_bytes: int | None = None,
        on_read: Callable[[], None] | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or [("content-type", "application/json")]
        self.body = body
        self.offset = 0
        self.read_sizes: list[int] = []
        self.closed = False
        self.max_chunk_bytes = max_chunk_bytes
        self.on_read = on_read

    def getheaders(self) -> list[tuple[str, str]]:
        return self.headers

    def read(self, amount: int) -> bytes:
        self.read_sizes.append(amount)
        if self.on_read is not None:
            self.on_read()
        if self.max_chunk_bytes is not None:
            amount = min(amount, self.max_chunk_bytes)
        chunk = self.body[self.offset : self.offset + amount]
        self.offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


class ScriptedSocket:
    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)


class ScriptedConnection:
    def __init__(
        self,
        response: ScriptedResponse,
        *,
        on_connect: Callable[[], None] | None = None,
        on_request: Callable[[], None] | None = None,
        on_headers: Callable[[], None] | None = None,
    ) -> None:
        self.response = response
        self.initialized_with: tuple[object, ...] | None = None
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.closed = False
        self.sock = ScriptedSocket()
        self.deadline: _RequestDeadline | None = None
        self.on_connect = on_connect
        self.on_request = on_request
        self.on_headers = on_headers

    def initialize(
        self,
        host: str,
        port: int,
        *,
        pinned_address: str,
        timeout: float,
        context: ssl.SSLContext,
        deadline: _RequestDeadline,
    ) -> ScriptedConnection:
        self.initialized_with = (host, port, pinned_address, timeout, context, deadline)
        self.deadline = deadline
        return self

    def connect(self) -> None:
        assert self.deadline is not None
        self.sock.settimeout(self.deadline.remaining())
        if self.on_connect is not None:
            self.on_connect()

    def request(self, method: str, target: str, *, headers) -> None:  # type: ignore[no-untyped-def]
        self.requests.append((method, target, dict(headers)))
        if self.on_request is not None:
            self.on_request()

    def getresponse(self) -> ScriptedResponse:
        if self.on_headers is not None:
            self.on_headers()
        return self.response

    def close(self) -> None:
        self.closed = True


class ExplodingRateLimiter:
    def acquire(self, *, source_id, url, observed_at) -> None:  # type: ignore[no-untyped-def]
        raise AssertionError("capability denial reached the rate limiter")


class FakeMonotonic:
    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def _install_connection(
    monkeypatch: pytest.MonkeyPatch,
    response: ScriptedResponse,
    **callbacks: Callable[[], None],
) -> ScriptedConnection:
    connection = ScriptedConnection(response, **callbacks)
    monkeypatch.setattr(live_transport, "_PinnedHTTPSConnection", connection.initialize)
    return connection


def _request(
    transport: PinnedHTTPSFetchTransport,
    *,
    addresses: tuple[str, ...] = ("8.8.8.8",),
    max_bytes: int = 1024,
    timeout_seconds: float = 7.0,
):  # type: ignore[no-untyped-def]
    return transport.request(
        url=URL,
        headers=REQUEST_HEADERS,
        timeout_seconds=timeout_seconds,
        resolved_addresses=addresses,
        max_bytes=max_bytes,
    )


def _plan(**changes: object) -> FetchPlan:
    return replace(
        FetchPlan(
            source_id="live-transport-fixture",
            source_revision_id="revision-1",
            source_revision_decision_id="decision-1",
            request_url=URL,
            approved_urls=frozenset({URL}),
            accepted_content_types=frozenset({"application/json"}),
            timeout_seconds=30.0,
            max_bytes=1024,
        ),
        **changes,
    )


def test_dns_is_resolved_once_and_the_selected_address_reaches_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _install_connection(monkeypatch, ScriptedResponse(b"{}"))
    resolutions: list[tuple[str, int]] = []

    def rebinding_resolver(host: str, port: int) -> list[str]:
        resolutions.append((host, port))
        return ["8.8.8.8"] if len(resolutions) == 1 else ["127.0.0.1"]

    result = SafeFetchClient(
        transport=PinnedHTTPSFetchTransport(),
        resolver=rebinding_resolver,
    ).fetch(_plan())

    assert result.raw_bytes == b"{}"
    assert resolutions == [("official.example", 443)]
    assert connection.initialized_with is not None
    assert connection.initialized_with[:4] == ("official.example", 443, "8.8.8.8", 30.0)


def test_pinned_connection_uses_address_without_dns_and_tls_uses_original_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[object, ...]] = []
    clock = FakeMonotonic()

    class RawSocket:
        def settimeout(self, timeout: object) -> None:
            events.append(("timeout", timeout))

        def connect(self, peer: tuple[object, ...]) -> None:
            events.append(("connect", *peer))
            clock.advance(2.0)

        def setsockopt(self, *args: object) -> None:
            events.append(("setsockopt", *args))

        def close(self) -> None:
            events.append(("close",))

    class RecordingContext:
        verify_mode = ssl.CERT_REQUIRED
        check_hostname = True

        def wrap_socket(self, raw_socket: RawSocket, *, server_hostname: str) -> RawSocket:
            events.append(("tls", server_hostname))
            clock.advance(2.0)
            return raw_socket

    raw_socket = RawSocket()
    monkeypatch.setattr(live_transport.time, "monotonic", clock)
    monkeypatch.setattr(live_transport.socket, "socket", lambda *_args: raw_socket)
    monkeypatch.setattr(
        live_transport.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: pytest.fail("pinned connect performed a second resolution"),
    )
    connection = _PinnedHTTPSConnection(
        "official.example",
        443,
        pinned_address="8.8.8.8",
        timeout=7.0,
        context=RecordingContext(),  # type: ignore[arg-type]
        deadline=_RequestDeadline.start(7.0),
    )

    connection.connect()

    assert ("connect", "8.8.8.8", 443) in events
    assert ("tls", "official.example") in events
    assert ("timeout", 7.0) in events
    assert ("timeout", 5.0) in events


def test_transport_returns_redirect_without_following_it(monkeypatch: pytest.MonkeyPatch) -> None:
    response = ScriptedResponse(
        b"",
        status=302,
        headers=[("location", "https://redirected.example/secret")],
    )
    connection = _install_connection(monkeypatch, response)

    result = _request(PinnedHTTPSFetchTransport())

    assert result.status_code == 302
    assert result.url == URL
    assert connection.requests == [("GET", "/results.json", REQUEST_HEADERS)]


def test_oversized_body_is_stopped_during_bounded_stream_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = ScriptedResponse(b"12345")
    connection = _install_connection(monkeypatch, response)

    with pytest.raises(SafeFetchError) as raised:
        _request(PinnedHTTPSFetchTransport(), max_bytes=4)

    assert raised.value.code == "FETCH_RESPONSE_TOO_LARGE"
    assert response.read_sizes == [5]
    assert response.closed is True
    assert connection.closed is True


def test_cumulative_slow_body_progress_cannot_extend_total_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeMonotonic()
    response = ScriptedResponse(
        b"abcdef",
        max_chunk_bytes=1,
        on_read=lambda: clock.advance(2.0),
    )
    connection = _install_connection(monkeypatch, response)
    monkeypatch.setattr(live_transport.time, "monotonic", clock)

    with pytest.raises(SafeFetchError) as raised:
        _request(PinnedHTTPSFetchTransport(), max_bytes=10, timeout_seconds=5.0)

    assert raised.value.code == "FETCH_TIMEOUT"
    assert raised.value.detail == "HTTPS request exceeded the total timeout"
    assert response.offset == 3
    assert connection.sock.timeouts == [5.0, 5.0, 5.0, 5.0, 3.0, 1.0]


def test_connect_headers_and_body_share_one_deadline_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeMonotonic()
    response = ScriptedResponse(b"x", on_read=lambda: clock.advance(3.0))
    connection = _install_connection(
        monkeypatch,
        response,
        on_connect=lambda: clock.advance(2.0),
        on_request=lambda: clock.advance(3.0),
        on_headers=lambda: clock.advance(3.0),
    )
    monkeypatch.setattr(live_transport.time, "monotonic", clock)

    with pytest.raises(SafeFetchError) as raised:
        _request(PinnedHTTPSFetchTransport(), timeout_seconds=10.0)

    assert raised.value.code == "FETCH_TIMEOUT"
    assert "official.example" not in str(raised.value)
    assert connection.sock.timeouts == [10.0, 8.0, 5.0, 2.0]


def test_transport_rejects_every_non_global_address_before_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        live_transport,
        "_PinnedHTTPSConnection",
        lambda *_args, **_kwargs: pytest.fail("non-global address reached connect"),
    )

    with pytest.raises(SafeFetchError) as raised:
        _request(PinnedHTTPSFetchTransport(), addresses=("8.8.8.8", "127.0.0.1"))

    assert raised.value.code == "FETCH_PRIVATE_NETWORK_FORBIDDEN"


def test_tls_hostname_mismatch_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    class MismatchedTLSConnection:
        def __init__(self) -> None:
            self.sock = ScriptedSocket()

        def connect(self) -> None:
            pass

        def request(self, *_args, **_kwargs) -> None:  # type: ignore[no-untyped-def]
            raise ssl.SSLCertVerificationError(
                "hostname mismatch for official.example at 8.8.8.8?token=do-not-report"
            )

        def close(self) -> None:
            pass

    monkeypatch.setattr(
        live_transport,
        "_PinnedHTTPSConnection",
        lambda *_args, **_kwargs: MismatchedTLSConnection(),
    )

    with pytest.raises(SafeFetchError) as raised:
        _request(PinnedHTTPSFetchTransport())

    assert raised.value.code == "FETCH_TLS_VERIFICATION_FAILED"
    assert raised.value.detail == "TLS certificate verification failed for the approved hostname"
    assert "official.example" not in str(raised.value)
    assert "8.8.8.8" not in str(raised.value)
    assert "do-not-report" not in str(raised.value)


def test_live_transport_requires_capability_and_contained_runtime_performs_no_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(RuntimeDependencyError, match="NETWORK_FETCH"):
        RuntimeDependencies(
            fetch_transport=PinnedHTTPSFetchTransport(),
            rate_limiter=ExplodingRateLimiter(),
            capabilities=frozenset(),
        )

    monkeypatch.setattr(
        safe_fetch.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: pytest.fail("contained runtime performed DNS"),
    )
    monkeypatch.setattr(
        live_transport.socket,
        "socket",
        lambda *_args, **_kwargs: pytest.fail("contained runtime opened a socket"),
    )
    dependencies = contained_runtime_dependencies(Settings(_env_file=None))
    assert dependencies.capabilities == frozenset()
    assert isinstance(dependencies.fetch_transport, DisabledNetworkTransport)

    with pytest.raises(SafeFetchError) as raised:
        dependencies.create_fetch_client().fetch(_plan())

    assert raised.value.code == "FETCH_TRANSPORT_UNAVAILABLE"


def test_live_transport_is_admitted_only_with_explicit_network_capability() -> None:
    dependencies = RuntimeDependencies(
        fetch_transport=PinnedHTTPSFetchTransport(),
        rate_limiter=ExplodingRateLimiter(),
        capabilities=frozenset({RuntimeCapability.NETWORK_FETCH}),
    )

    assert isinstance(dependencies.fetch_transport, PinnedHTTPSFetchTransport)
