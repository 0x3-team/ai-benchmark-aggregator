"""Explicitly authorized HTTPS transport with DNS-to-peer pinning."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
import errno
import http.client
import io
import ipaddress
import math
import socket
import ssl
import sys
import time
from typing import Any
from urllib.parse import urlsplit

from app.ingestion.admission import MAX_CERTIFIED_FETCH_BYTES
from app.ingestion.safe_fetch import (
    FetchTransportResponse,
    MAX_TIMEOUT_SECONDS,
    SafeFetchError,
    _is_global_unicast_address,
    _validate_https_url,
)


_READ_CHUNK_BYTES = 64 * 1024
_REQUEST_HEADER_NAMES = frozenset({"accept", "user-agent"})


@dataclass(frozen=True, slots=True)
class _RequestDeadline:
    expires_at: float

    @classmethod
    def start(cls, timeout_seconds: float) -> _RequestDeadline:
        return cls(expires_at=time.monotonic() + timeout_seconds)

    def remaining(self) -> float:
        remaining = self.expires_at - time.monotonic()
        if remaining <= 0:
            raise SafeFetchError(
                "FETCH_TIMEOUT",
                "HTTPS request exceeded the total timeout",
            )
        return remaining


class _DeadlineRawReader(io.RawIOBase):
    def __init__(
        self,
        raw: io.RawIOBase,
        network_socket: socket.socket,
        deadline: _RequestDeadline,
    ) -> None:
        self._raw = raw
        self.network_socket = network_socket
        self._deadline = deadline

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray | memoryview) -> int | None:
        self.network_socket.settimeout(self._deadline.remaining())
        read = self._raw.readinto(buffer)
        self._deadline.remaining()
        return read

    def close(self) -> None:
        try:
            self._raw.close()
        finally:
            super().close()


class _DeadlineResponseSocket:
    def __init__(
        self,
        network_socket: socket.socket,
        deadline: _RequestDeadline,
    ) -> None:
        self._network_socket = network_socket
        self._deadline = deadline

    def makefile(self, mode: str) -> io.BufferedReader:
        if mode != "rb":
            raise ValueError("deadline response socket supports binary reads only")
        raw = self._network_socket.makefile(mode, buffering=0)
        return io.BufferedReader(
            _DeadlineRawReader(raw, self._network_socket, self._deadline)
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(
        self,
        host: str,
        port: int,
        *,
        pinned_address: str,
        timeout: float,
        context: ssl.SSLContext,
        deadline: _RequestDeadline,
    ) -> None:
        self._pinned_address = pinned_address
        self._deadline = deadline
        super().__init__(host, port, timeout=timeout, context=context)
        self.response_class = self._create_deadline_response

    def _open_pinned_socket(
        self,
        timeout: float,
        source_address: tuple[Any, ...] | None = None,
    ) -> socket.socket:
        address = ipaddress.ip_address(self._pinned_address)
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        peer = (str(address), self.port, 0, 0) if address.version == 6 else (str(address), self.port)
        connected_socket = socket.socket(family, socket.SOCK_STREAM)
        try:
            connected_socket.settimeout(timeout)
            if source_address:
                connected_socket.bind(source_address)
            connected_socket.connect(peer)
        except OSError:
            connected_socket.close()
            raise
        return connected_socket

    def connect(self) -> None:
        sys.audit("http.client.connect", self, self.host, self.port)
        connected_socket = self._open_pinned_socket(
            self._deadline.remaining(),
            self.source_address,
        )
        try:
            try:
                connected_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError as exc:
                if exc.errno != errno.ENOPROTOOPT:
                    raise
            connected_socket.settimeout(self._deadline.remaining())
            self.sock = self._context.wrap_socket(
                connected_socket,
                server_hostname=self.host,
                suppress_ragged_eofs=False,
            )
        except (OSError, SafeFetchError, ValueError):
            connected_socket.close()
            self.sock = None
            raise

    def send(self, data: bytes | bytearray | memoryview) -> None:
        if self.sock is None:
            raise http.client.NotConnected()
        sys.audit("http.client.send", self, data)
        view = memoryview(data).cast("B")
        sent = 0
        while sent < len(view):
            self.sock.settimeout(self._deadline.remaining())
            written = self.sock.send(view[sent:])
            self._deadline.remaining()
            if written <= 0:
                raise OSError("TLS socket made no write progress")
            sent += written

    def _create_deadline_response(
        self,
        network_socket: socket.socket,
        debuglevel: int = 0,
        method: str | None = None,
        url: str | None = None,
    ) -> http.client.HTTPResponse:
        return http.client.HTTPResponse(
            _DeadlineResponseSocket(network_socket, self._deadline),
            debuglevel=debuglevel,
            method=method,
            url=url,
        )


def _validated_global_addresses(resolved_addresses: tuple[str, ...]) -> tuple[str, ...]:
    if type(resolved_addresses) is not tuple or not resolved_addresses:
        raise SafeFetchError("FETCH_DNS_INVALID", "transport received no validated address set")
    validated: list[str] = []
    for raw_address in resolved_addresses:
        if not isinstance(raw_address, str):
            raise SafeFetchError("FETCH_DNS_INVALID", "transport received an invalid address")
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError:
            raise SafeFetchError("FETCH_DNS_INVALID", "transport received an invalid address") from None
        if not _is_global_unicast_address(address):
            raise SafeFetchError(
                "FETCH_PRIVATE_NETWORK_FORBIDDEN",
                "transport refused a non-public or non-unicast peer address",
            )
        canonical = str(address)
        if canonical not in validated:
            validated.append(canonical)
    return tuple(sorted(validated))


def _validated_request_headers(headers: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(headers, Mapping):
        raise SafeFetchError("FETCH_REQUEST_INVALID", "request headers are invalid")
    validated: dict[str, str] = {}
    observed_names: set[str] = set()
    for name, value in headers.items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise SafeFetchError("FETCH_REQUEST_INVALID", "request headers are invalid")
        normalized = name.lower()
        if normalized not in _REQUEST_HEADER_NAMES or normalized in observed_names:
            raise SafeFetchError("FETCH_REQUEST_INVALID", "request headers are not permitted")
        if not value or any(character in value for character in "\r\n"):
            raise SafeFetchError("FETCH_REQUEST_INVALID", "request headers are invalid")
        observed_names.add(normalized)
        validated[name] = value
    if observed_names != _REQUEST_HEADER_NAMES:
        raise SafeFetchError("FETCH_REQUEST_INVALID", "required request headers are missing")
    return validated


def _set_socket_timeout(
    connection: http.client.HTTPSConnection,
    deadline: _RequestDeadline,
) -> None:
    if connection.sock is None:
        raise SafeFetchError("FETCH_PROTOCOL_FAILURE", "HTTPS connection was unavailable")
    connection.sock.settimeout(deadline.remaining())


def _set_body_socket_timeout(
    response: http.client.HTTPResponse,
    connection: http.client.HTTPSConnection,
    deadline: _RequestDeadline,
) -> None:
    network_socket = connection.sock
    if network_socket is None:
        buffered_reader = response.fp
        raw_reader = getattr(buffered_reader, "raw", None)
        network_socket = getattr(raw_reader, "network_socket", None)
    if network_socket is None or not callable(getattr(network_socket, "settimeout", None)):
        raise SafeFetchError("FETCH_PROTOCOL_FAILURE", "HTTPS response socket was unavailable")
    network_socket.settimeout(deadline.remaining())


def _read_bounded_body(
    response: http.client.HTTPResponse,
    max_bytes: int,
    *,
    connection: http.client.HTTPSConnection,
    deadline: _RequestDeadline,
) -> bytes:
    def framing_complete() -> bool:
        if not hasattr(response, "fp"):
            return False
        length = getattr(response, "length", None)
        if length == 0:
            return True
        if response.fp is not None:
            return False
        if getattr(response, "chunked", False):
            if getattr(response, "chunk_left", None) is None:
                return True
            raise SafeFetchError(
                "FETCH_PROTOCOL_FAILURE",
                "HTTPS response ended before chunk framing completed",
            )
        if length is not None:
            raise SafeFetchError(
                "FETCH_PROTOCOL_FAILURE",
                "HTTPS response ended before its declared length",
            )
        return True

    body = bytearray()
    while True:
        if framing_complete():
            return bytes(body)
        remaining = max_bytes + 1 - len(body)
        if remaining <= 0:
            raise SafeFetchError(
                "FETCH_RESPONSE_TOO_LARGE",
                "response exceeded the certified byte limit",
            )
        _set_body_socket_timeout(response, connection, deadline)
        try:
            chunk = response.read(min(_READ_CHUNK_BYTES, remaining))
        except http.client.IncompleteRead:
            raise SafeFetchError(
                "FETCH_PROTOCOL_FAILURE",
                "HTTPS response ended before framing completed",
            ) from None
        deadline.remaining()
        if not isinstance(chunk, bytes):
            raise SafeFetchError("FETCH_PROTOCOL_FAILURE", "response body stream was invalid")
        if not chunk:
            if hasattr(response, "fp"):
                if framing_complete():
                    return bytes(body)
                raise SafeFetchError(
                    "FETCH_PROTOCOL_FAILURE",
                    "HTTPS response ended before framing completed",
                )
            return bytes(body)
        if len(chunk) > remaining:
            raise SafeFetchError(
                "FETCH_RESPONSE_TOO_LARGE",
                "response exceeded the certified byte limit",
            )
        body.extend(chunk)
        if len(body) > max_bytes:
            raise SafeFetchError(
                "FETCH_RESPONSE_TOO_LARGE",
                "response exceeded the certified byte limit",
            )


@dataclass(frozen=True, slots=True)
class PinnedHTTPSFetchTransport:
    """One-shot GET transport; authority comes from ``RuntimeDependencies``."""

    def request(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
        resolved_addresses: tuple[str, ...],
        max_bytes: int,
    ) -> FetchTransportResponse:
        host, port = _validate_https_url(url)
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= MAX_TIMEOUT_SECONDS
        ):
            raise SafeFetchError("FETCH_REQUEST_INVALID", "request timeout is invalid")
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_CERTIFIED_FETCH_BYTES:
            raise SafeFetchError("FETCH_REQUEST_INVALID", "request byte limit is invalid")
        addresses = _validated_global_addresses(resolved_addresses)
        request_headers = _validated_request_headers(headers)
        parsed = urlsplit(url)
        target = parsed.path or "/"
        if parsed.query:
            target = f"{target}?{parsed.query}"

        deadline = _RequestDeadline.start(float(timeout_seconds))
        try:
            context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
        except (OSError, ValueError):
            raise SafeFetchError(
                "FETCH_TLS_POLICY_INVALID",
                "TLS verification policy is unavailable",
            ) from None
        if not context.check_hostname or context.verify_mode != ssl.CERT_REQUIRED:
            raise SafeFetchError("FETCH_TLS_POLICY_INVALID", "TLS verification policy is unavailable")
        connection: http.client.HTTPSConnection | None = None
        response: http.client.HTTPResponse | None = None
        try:
            for address in addresses:
                candidate = _PinnedHTTPSConnection(
                    host,
                    port,
                    pinned_address=address,
                    timeout=deadline.remaining(),
                    context=context,
                    deadline=deadline,
                )
                try:
                    candidate.connect()
                    _set_socket_timeout(candidate, deadline)
                except ssl.SSLCertVerificationError:
                    with suppress(Exception):
                        candidate.close()
                    raise
                except TimeoutError:
                    with suppress(Exception):
                        candidate.close()
                    deadline.remaining()
                    continue
                except ssl.SSLError:
                    with suppress(Exception):
                        candidate.close()
                    raise
                except OSError:
                    with suppress(Exception):
                        candidate.close()
                    deadline.remaining()
                    continue
                except (SafeFetchError, ValueError):
                    with suppress(Exception):
                        candidate.close()
                    raise
                connection = candidate
                break
            if connection is None:
                raise SafeFetchError("FETCH_NETWORK_FAILURE", "HTTPS connection failed")
            connection.request("GET", target, headers=request_headers)
            _set_socket_timeout(connection, deadline)
            response = connection.getresponse()
            response_headers: dict[str, str] = {}
            for name, value in response.getheaders():
                normalized = name.lower()
                if normalized in response_headers:
                    response_headers[normalized] = f"{response_headers[normalized]}, {value}"
                else:
                    response_headers[normalized] = value
            body = (
                _read_bounded_body(
                    response,
                    max_bytes,
                    connection=connection,
                    deadline=deadline,
                )
                if 200 <= response.status < 300
                else b""
            )
            return FetchTransportResponse(
                url=url,
                status_code=response.status,
                headers=response_headers,
                body=body,
            )
        except SafeFetchError:
            raise
        except ssl.SSLCertVerificationError:
            raise SafeFetchError(
                "FETCH_TLS_VERIFICATION_FAILED",
                "TLS certificate verification failed for the approved hostname",
            ) from None
        except TimeoutError:
            raise SafeFetchError(
                "FETCH_TIMEOUT",
                "HTTPS request exceeded the total timeout",
            ) from None
        except (http.client.HTTPException, ValueError, TypeError):
            raise SafeFetchError("FETCH_PROTOCOL_FAILURE", "HTTPS response was invalid") from None
        except OSError:
            raise SafeFetchError("FETCH_NETWORK_FAILURE", "HTTPS request failed") from None
        finally:
            if response is not None:
                with suppress(Exception):
                    response.close()
            if connection is not None:
                with suppress(Exception):
                    connection.close()
