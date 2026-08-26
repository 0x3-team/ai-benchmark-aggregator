"""Fail-closed, policy-bound acquisition for Official source artifacts.

Adapters parse one captured artifact; they do not decide where or how to make
network requests.  A source-revision admission decision supplies the immutable
URL allowlist, and this module validates every request/redirect before a
transport is allowed to see it.

The ordinary runtime remains live-disabled.  An explicitly authorized runner
may supply the peer-pinning HTTPS transport from ``live_transport``; the
validated address set is passed into that transport so it never resolves the
hostname a second time and cannot be redirected by DNS rebinding.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import math
import socket
from typing import TYPE_CHECKING, Callable, Mapping, Protocol, runtime_checkable
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

from app.ingestion.admission import MAX_CERTIFIED_FETCH_BYTES, SourceAdmission
from app.schemas.boundary import OfficialSource, SourceFetchResult

if TYPE_CHECKING:
    from app.runtime.dependencies import Clock, RateLimiter


SAFE_FETCH_POLICY_VERSION = "safe-fetch-v1"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 3
MAX_TIMEOUT_SECONDS = 60.0
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_USER_AGENT = "benchmark-ledger/0.1"
SAFE_RESPONSE_HEADERS = frozenset({"content-type", "content-length", "etag", "last-modified"})
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
SENSITIVE_QUERY_NAMES = frozenset(
    {"access_token", "api_key", "apikey", "authorization", "key", "password", "secret", "signature", "token"}
)


class SafeFetchError(RuntimeError):
    """A stable, non-secret error emitted before a snapshot can be written."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class SafeFetchSettings:
    """Immutable request settings supplied by the runtime composition root."""

    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    user_agent: str = DEFAULT_USER_AGENT

    def __post_init__(self) -> None:
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(float(self.timeout_seconds))
            or not 1.0 <= float(self.timeout_seconds) <= MAX_TIMEOUT_SECONDS
        ):
            raise ValueError(
                f"Safe-fetch timeout must be between 1 and {MAX_TIMEOUT_SECONDS:g} seconds."
            )
        if (
            not isinstance(self.user_agent, str)
            or not self.user_agent.strip()
            or any(character in self.user_agent for character in "\r\n")
        ):
            raise ValueError("Safe-fetch user agent must be one non-empty header value.")


@dataclass(frozen=True)
class FetchPlan:
    """One immutable, admission-bound request plan for a source revision."""

    source_id: str
    source_revision_id: str
    source_revision_decision_id: str
    request_url: str
    approved_urls: frozenset[str]
    accepted_content_types: frozenset[str]
    timeout_seconds: float
    max_bytes: int = DEFAULT_MAX_BYTES
    max_redirects: int = DEFAULT_MAX_REDIRECTS


@dataclass(frozen=True)
class FetchTransportResponse:
    """A transport result with no implicit redirect following or retries."""

    url: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes


@runtime_checkable
class FetchTransport(Protocol):
    """Runner-provided transport contract used after policy/DNS validation."""

    def request(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
        resolved_addresses: tuple[str, ...],
        max_bytes: int,
    ) -> FetchTransportResponse: ...


Resolver = Callable[[str, int], list[str]]


class DisabledNetworkTransport:
    """Default transport: never make an unverified real network request."""

    def request(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        timeout_seconds: float,
        resolved_addresses: tuple[str, ...],
        max_bytes: int,
    ) -> FetchTransportResponse:
        raise SafeFetchError(
            "FETCH_TRANSPORT_UNAVAILABLE",
            "a runner-specific peer-pinning transport and egress policy are required",
        )


def system_resolver(host: str, port: int) -> list[str]:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise SafeFetchError("FETCH_DNS_FAILURE", "hostname resolution failed") from exc
    addresses = sorted({record[4][0] for record in records if record[4]})
    if not addresses:
        raise SafeFetchError("FETCH_DNS_EMPTY", "hostname resolved to no addresses")
    return addresses


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def _safe_response_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        key.lower(): value
        for key, value in headers.items()
        if key.lower() in SAFE_RESPONSE_HEADERS
    }


def _redacted_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _validate_https_url(url: str) -> tuple[str, int]:
    if not isinstance(url, str) or any(
        ord(character) <= 0x20 or ord(character) == 0x7F for character in url
    ):
        raise SafeFetchError("FETCH_URL_FORBIDDEN", "URL contains forbidden characters")
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise SafeFetchError("FETCH_URL_FORBIDDEN", "URL is invalid") from None
    if parsed.scheme != "https" or not parsed.hostname:
        raise SafeFetchError("FETCH_URL_FORBIDDEN", "only absolute HTTPS URLs are permitted")
    if parsed.username or parsed.password or parsed.fragment:
        raise SafeFetchError("FETCH_URL_FORBIDDEN", "credentials and fragments are not permitted")
    if any(
        name.lower() in SENSITIVE_QUERY_NAMES or name.lower().startswith("x-amz-")
        for name, _value in parse_qsl(parsed.query, keep_blank_values=True)
    ):
        raise SafeFetchError("FETCH_URL_FORBIDDEN", "credential-like query parameters are not permitted")
    # A literal address bypasses name ownership/TLS-host review and is not an
    # admissible source endpoint. Hostname resolution is checked below.
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        raise SafeFetchError("FETCH_URL_FORBIDDEN", "IP-literal URLs are not permitted")
    try:
        port = parsed.port
    except ValueError as exc:
        raise SafeFetchError("FETCH_URL_FORBIDDEN", "URL port is invalid") from exc
    return parsed.hostname, port or 443


def _resolve_global_addresses(url: str, resolver: Resolver) -> tuple[str, ...]:
    host, port = _validate_https_url(url)
    addresses = resolver(host, port)
    if not addresses:
        raise SafeFetchError("FETCH_DNS_EMPTY", "hostname resolved to no addresses")
    validated: list[str] = []
    for raw_address in addresses:
        if not isinstance(raw_address, str):
            raise SafeFetchError("FETCH_DNS_INVALID", "resolver returned a non-IP address")
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise SafeFetchError("FETCH_DNS_INVALID", "resolver returned a non-IP address") from exc
        if not address.is_global:
            raise SafeFetchError(
                "FETCH_PRIVATE_NETWORK_FORBIDDEN",
                "the source hostname resolved to a non-public address",
            )
        canonical = str(address)
        if canonical not in validated:
            validated.append(canonical)
    return tuple(validated)


def _content_type_allowed(content_type: str, allowed: frozenset[str]) -> bool:
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime in allowed:
        return True
    return "application/*+json" in allowed and mime.startswith("application/") and mime.endswith("+json")


def build_fetch_plan(
    *,
    source: OfficialSource,
    source_admission: SourceAdmission,
    accepted_content_types: frozenset[str],
    settings: SafeFetchSettings | None = None,
) -> FetchPlan:
    """Bind an adapter's expected MIME types to its certified source revision."""

    if not source_admission.verdict.accepted:
        raise SafeFetchError("FETCH_SOURCE_NOT_ADMITTED", "source revision was not admitted")
    if source.requires_auth:
        raise SafeFetchError(
            "FETCH_AUTH_FORBIDDEN",
            "credentialed source fetches require a separately approved transport policy",
        )
    if not source_admission.source_revision_id or not source_admission.source_revision_decision_id:
        raise SafeFetchError("FETCH_ADMISSION_CONTEXT_INVALID", "immutable revision decision is missing")
    policy = source_admission.policy
    approved_source_urls = policy.get("approved_source_urls")
    approved_final_urls = policy.get("approved_final_urls")
    if (
        not isinstance(approved_source_urls, list)
        or not isinstance(approved_final_urls, list)
        or not all(isinstance(url, str) and url for url in [*approved_source_urls, *approved_final_urls])
    ):
        raise SafeFetchError("FETCH_ADMISSION_CONTEXT_INVALID", "certified URL allowlists are missing")
    if source.source_url not in approved_source_urls:
        raise SafeFetchError("FETCH_SOURCE_URL_NOT_APPROVED", "source URL is not in its certified allowlist")
    fetch_policy = policy.get("fetch")
    max_bytes = fetch_policy.get("max_bytes") if isinstance(fetch_policy, dict) else None
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_CERTIFIED_FETCH_BYTES:
        raise SafeFetchError(
            "FETCH_ADMISSION_CONTEXT_INVALID",
            "certified source policy has no bounded byte limit",
        )
    approved_urls = frozenset([*approved_source_urls, *approved_final_urls])
    for url in approved_urls:
        _validate_https_url(url)
    normalized_content_types = frozenset(content_type.lower() for content_type in accepted_content_types)
    if not normalized_content_types:
        raise SafeFetchError("FETCH_CONTENT_POLICY_INVALID", "adapter declared no accepted content types")
    runtime_settings = settings or SafeFetchSettings()
    if type(runtime_settings) is not SafeFetchSettings:
        raise TypeError("Safe-fetch settings must be a canonical SafeFetchSettings value.")
    return FetchPlan(
        source_id=source.id,
        source_revision_id=source_admission.source_revision_id,
        source_revision_decision_id=source_admission.source_revision_decision_id,
        request_url=source.source_url,
        approved_urls=approved_urls,
        accepted_content_types=normalized_content_types,
        timeout_seconds=float(runtime_settings.timeout_seconds),
        max_bytes=max_bytes,
    )


class SafeFetchClient:
    """Manual-redirect, DNS-checked client with redacted capture metadata."""

    def __init__(
        self,
        *,
        transport: FetchTransport | None = None,
        resolver: Resolver = system_resolver,
        settings: SafeFetchSettings | None = None,
        clock: Clock | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        # Local imports avoid making the protocol module a second fetch truth
        # owner while still giving direct SafeFetchClient callers inert,
        # immutable defaults.
        from app.runtime.dependencies import NoOpRateLimiter, UTCClock

        self._transport = (
            DisabledNetworkTransport() if transport is None else transport
        )
        if not isinstance(self._transport, FetchTransport):
            raise TypeError("Safe-fetch transport does not implement FetchTransport.")
        if not callable(resolver):
            raise TypeError("Safe-fetch resolver must be callable.")
        self._resolver = resolver
        self._settings = SafeFetchSettings() if settings is None else settings
        if type(self._settings) is not SafeFetchSettings:
            raise TypeError("Safe-fetch settings must be a canonical SafeFetchSettings value.")
        self._clock = UTCClock() if clock is None else clock
        self._rate_limiter = NoOpRateLimiter() if rate_limiter is None else rate_limiter

    def fetch(self, plan: FetchPlan) -> SourceFetchResult:
        if type(plan) is not FetchPlan:
            raise TypeError("Safe-fetch plan must be a canonical FetchPlan value.")
        # DNS is network activity too.  The contained default must fail before
        # resolution, clock access, limiter acquisition, or transport dispatch.
        if isinstance(self._transport, DisabledNetworkTransport):
            raise SafeFetchError(
                "FETCH_TRANSPORT_UNAVAILABLE",
                "a runner-specific peer-pinning transport and egress policy are required",
            )
        if (
            isinstance(plan.timeout_seconds, bool)
            or not isinstance(plan.timeout_seconds, (int, float))
            or not math.isfinite(float(plan.timeout_seconds))
            or float(plan.timeout_seconds) != float(self._settings.timeout_seconds)
        ):
            raise SafeFetchError(
                "FETCH_TIMEOUT_POLICY_MISMATCH",
                "fetch plan timeout does not match the injected runtime setting",
            )
        current_url = plan.request_url
        redirects = 0
        request_headers = {
            "Accept": ", ".join(sorted(plan.accepted_content_types)),
            "User-Agent": self._settings.user_agent,
        }

        while True:
            if current_url not in plan.approved_urls:
                raise SafeFetchError(
                    "FETCH_URL_NOT_APPROVED",
                    "request or redirect URL is not in the certified allowlist",
                )
            observed_at = self._clock.now()
            if (
                not isinstance(observed_at, datetime)
                or observed_at.tzinfo is None
                or observed_at.utcoffset() != timezone.utc.utcoffset(observed_at)
            ):
                raise SafeFetchError(
                    "FETCH_CLOCK_INVALID",
                    "rate-limit accounting requires an aware UTC timestamp",
                )
            self._rate_limiter.acquire(
                source_id=plan.source_id,
                url=current_url,
                observed_at=observed_at,
            )
            resolved_addresses = _resolve_global_addresses(current_url, self._resolver)
            response = self._transport.request(
                url=current_url,
                headers=request_headers,
                timeout_seconds=float(self._settings.timeout_seconds),
                resolved_addresses=resolved_addresses,
                max_bytes=plan.max_bytes,
            )
            if response.url != current_url:
                raise SafeFetchError(
                    "FETCH_TRANSPORT_URL_MISMATCH",
                    "transport must not follow or rewrite redirects",
                )
            if len(response.body) > plan.max_bytes:
                raise SafeFetchError("FETCH_RESPONSE_TOO_LARGE", "response exceeded the certified byte limit")

            location = _header_value(response.headers, "location")
            if response.status_code in REDIRECT_STATUSES:
                if not location:
                    raise SafeFetchError("FETCH_REDIRECT_INVALID", "redirect response lacks a location")
                if redirects >= plan.max_redirects:
                    raise SafeFetchError("FETCH_REDIRECT_LIMIT", "redirect limit exceeded")
                current_url = urljoin(current_url, location)
                redirects += 1
                continue
            if not 200 <= response.status_code < 300:
                raise SafeFetchError("FETCH_HTTP_STATUS_INVALID", "source did not return a successful response")

            safe_headers = _safe_response_headers(response.headers)
            content_type = safe_headers.get("content-type")
            if not content_type or not _content_type_allowed(content_type, plan.accepted_content_types):
                raise SafeFetchError(
                    "FETCH_CONTENT_TYPE_FORBIDDEN",
                    "response content type is not approved for this adapter",
                )
            return SourceFetchResult(
                raw_bytes=response.body,
                content_type=content_type,
                http_status=response.status_code,
                etag=safe_headers.get("etag"),
                last_modified_header=safe_headers.get("last-modified"),
                final_url=current_url,
                headers=safe_headers,
                metadata={
                    "verbatim": True,
                    "artifact_count": 1,
                    "mock_used": False,
                    "fallback_used": False,
                    "derived": False,
                    "transformed": False,
                    "assembled": False,
                    "safe_fetch": {
                        "policy_version": SAFE_FETCH_POLICY_VERSION,
                        "source_revision_id": plan.source_revision_id,
                        "source_revision_decision_id": plan.source_revision_decision_id,
                        "request_url": _redacted_url(plan.request_url),
                        "final_url": _redacted_url(current_url),
                        "redirect_count": redirects,
                        "content_length": len(response.body),
                    },
                },
            )
