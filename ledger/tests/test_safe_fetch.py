from __future__ import annotations

from dataclasses import replace
import inspect
from pathlib import Path

import pytest

from app.ingestion.adapters.generic_json import GenericJSONAdapter
from app.ingestion.adapters import ADAPTERS
from app.ingestion.adapters.base import SourceAdapter
from app.ingestion.safe_fetch import (
    FetchPlan,
    FetchTransportResponse,
    SafeFetchClient,
    SafeFetchError,
    build_fetch_plan,
)
from app.ingestion.admission import AdmissionVerdict, SourceAdmission
from app.schemas.boundary import OfficialSource


URL = "https://official.example/results.json?public=1"
REDIRECT_URL = "https://official.example/current.json"


class ScriptedTransport:
    def __init__(self, responses: dict[str, FetchTransportResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    def request(
        self,
        *,
        url: str,
        headers,
        timeout_seconds: float,
        resolved_addresses: tuple[str, ...],
        max_bytes: int,
    ) -> FetchTransportResponse:  # type: ignore[no-untyped-def]
        _ = timeout_seconds, resolved_addresses, max_bytes
        self.calls.append((url, dict(headers)))
        return self.responses[url]


def public_resolver(_host: str, _port: int) -> list[str]:
    return ["8.8.8.8"]


def plan(**changes) -> FetchPlan:  # type: ignore[no-untyped-def]
    base = FetchPlan(
        source_id="safe-fetch-fixture",
        source_revision_id="revision-1",
        source_revision_decision_id="decision-1",
        request_url=URL,
        approved_urls=frozenset({URL, REDIRECT_URL}),
        accepted_content_types=frozenset({"application/json", "application/*+json"}),
        timeout_seconds=30,
    )
    return replace(base, **changes)


def response(
    url: str,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    body: bytes = b'{"results":[]}',
) -> FetchTransportResponse:
    return FetchTransportResponse(
        url=url,
        status_code=status,
        headers=headers or {"content-type": "application/json"},
        body=body,
    )


def test_safe_fetch_rejects_private_resolution_before_transport() -> None:
    transport = ScriptedTransport({})
    client = SafeFetchClient(transport=transport, resolver=lambda _host, _port: ["127.0.0.1"])

    with pytest.raises(SafeFetchError) as raised:
        client.fetch(plan())

    assert raised.value.code == "FETCH_PRIVATE_NETWORK_FORBIDDEN"
    assert transport.calls == []


def test_safe_fetch_rejects_an_empty_resolution_before_transport() -> None:
    transport = ScriptedTransport({})
    client = SafeFetchClient(transport=transport, resolver=lambda _host, _port: [])

    with pytest.raises(SafeFetchError) as raised:
        client.fetch(plan())

    assert raised.value.code == "FETCH_DNS_EMPTY"
    assert transport.calls == []


def test_safe_fetch_validates_each_redirect_against_the_certified_allowlist() -> None:
    transport = ScriptedTransport(
        {
            URL: response(
                URL,
                status=302,
                headers={"location": "https://unapproved.example/score.json"},
            )
        }
    )
    client = SafeFetchClient(transport=transport, resolver=public_resolver)

    with pytest.raises(SafeFetchError) as raised:
        client.fetch(plan())

    assert raised.value.code == "FETCH_URL_NOT_APPROVED"
    assert [call[0] for call in transport.calls] == [URL]


def test_safe_fetch_rejects_oversize_and_unexpected_content_before_snapshot() -> None:
    too_large = ScriptedTransport({URL: response(URL, body=b"12345")})
    with pytest.raises(SafeFetchError) as raised:
        SafeFetchClient(transport=too_large, resolver=public_resolver).fetch(plan(max_bytes=4))
    assert raised.value.code == "FETCH_RESPONSE_TOO_LARGE"

    wrong_type = ScriptedTransport({URL: response(URL, headers={"content-type": "text/html"})})
    with pytest.raises(SafeFetchError) as raised:
        SafeFetchClient(transport=wrong_type, resolver=public_resolver).fetch(plan())
    assert raised.value.code == "FETCH_CONTENT_TYPE_FORBIDDEN"


def test_safe_fetch_records_only_safe_headers_and_redacted_telemetry() -> None:
    transport = ScriptedTransport(
        {
            URL: response(
                URL,
                headers={
                    "content-type": "application/json; charset=utf-8",
                    "etag": "fixture-etag",
                    "set-cookie": "session=do-not-store",
                    "x-internal-token": "do-not-store",
                },
            )
        }
    )

    result = SafeFetchClient(transport=transport, resolver=public_resolver).fetch(plan())

    assert result.headers == {
        "content-type": "application/json; charset=utf-8",
        "etag": "fixture-etag",
    }
    assert result.metadata["verbatim"] is True
    assert result.metadata["safe_fetch"]["request_url"] == "https://official.example/results.json"
    assert "Authorization" not in transport.calls[0][1]
    assert "public=1" not in result.metadata["safe_fetch"]["request_url"]


def test_fetch_plan_requires_admitted_exact_source_and_refuses_auth() -> None:
    source = OfficialSource(
        id="safe-fetch-fixture",
        source_name="Safe fetch fixture",
        source_url=URL,
        source_type="static_json",
        officialness_level="O5",
        machine_readable=True,
        parser_name="generic_json",
    )
    admission = SourceAdmission(
        AdmissionVerdict("admit"),
        source_revision_id="revision-1",
        source_revision_decision_id="decision-1",
        policy={
            "approved_source_urls": [URL],
            "approved_final_urls": [URL],
            "fetch": {"max_bytes": 5 * 1024 * 1024},
        },
    )
    built = build_fetch_plan(
        source=source,
        source_admission=admission,
        accepted_content_types=GenericJSONAdapter.accepted_content_types,
    )
    assert built.request_url == URL

    with pytest.raises(SafeFetchError) as raised:
        build_fetch_plan(
            source=source.model_copy(update={"requires_auth": True}),
            source_admission=admission,
            accepted_content_types=GenericJSONAdapter.accepted_content_types,
        )
    assert raised.value.code == "FETCH_AUTH_FORBIDDEN"

    with pytest.raises(SafeFetchError) as raised:
        build_fetch_plan(
            source=source.model_copy(update={"source_url": "https://official.example/results.json?token=nope"}),
            source_admission=SourceAdmission(
                AdmissionVerdict("admit"),
                source_revision_id="revision-1",
                source_revision_decision_id="decision-1",
                policy={
                    "approved_source_urls": ["https://official.example/results.json?token=nope"],
                    "approved_final_urls": ["https://official.example/results.json?token=nope"],
                    "fetch": {"max_bytes": 5 * 1024 * 1024},
                },
            ),
            accepted_content_types=GenericJSONAdapter.accepted_content_types,
        )
    assert raised.value.code == "FETCH_URL_FORBIDDEN"

    invalid_port_url = "https://official.example:not-a-port/results.json"
    with pytest.raises(SafeFetchError) as raised:
        build_fetch_plan(
            source=source.model_copy(update={"source_url": invalid_port_url}),
            source_admission=SourceAdmission(
                AdmissionVerdict("admit"),
                source_revision_id="revision-1",
                source_revision_decision_id="decision-1",
                policy={
                    "approved_source_urls": [invalid_port_url],
                    "approved_final_urls": [invalid_port_url],
                    "fetch": {"max_bytes": 5 * 1024 * 1024},
                },
            ),
            accepted_content_types=GenericJSONAdapter.accepted_content_types,
        )
    assert raised.value.code == "FETCH_URL_FORBIDDEN"


def test_fetch_plan_uses_a_source_specific_bounded_byte_limit() -> None:
    source = OfficialSource(
        id="swe-size-fixture",
        source_name="SWE size fixture",
        source_url=URL,
        source_type="static_json",
        officialness_level="O5",
        machine_readable=True,
        parser_name="swe_bench_adapter",
    )
    admission = SourceAdmission(
        AdmissionVerdict("admit"),
        source_revision_id="revision-1",
        source_revision_decision_id="decision-1",
        policy={
            "approved_source_urls": [URL],
            "approved_final_urls": [URL],
            "fetch": {"max_bytes": 8 * 1024 * 1024},
        },
    )

    plan_with_size = build_fetch_plan(
        source=source,
        source_admission=admission,
        accepted_content_types=GenericJSONAdapter.accepted_content_types,
    )

    assert plan_with_size.max_bytes == 8 * 1024 * 1024


def test_network_adapter_cannot_fetch_without_the_runner_bound_plan() -> None:
    source = OfficialSource(
        id="safe-fetch-fixture",
        source_name="Safe fetch fixture",
        source_url=URL,
        source_type="static_json",
        officialness_level="O5",
    )

    with pytest.raises(SafeFetchError) as raised:
        GenericJSONAdapter().fetch(source)

    assert raised.value.code == "FETCH_PLAN_REQUIRED"


def test_registered_network_adapters_have_no_adapter_owned_http_path() -> None:
    for adapter_class in set(ADAPTERS.values()):
        if not adapter_class.requires_central_fetch:
            continue
        implementation = adapter_class.fetch
        assert implementation is SourceAdapter.fetch or "super().fetch(source)" in inspect.getsource(implementation)

    adapters_dir = Path(__file__).parents[1] / "app" / "ingestion" / "adapters"
    for adapter_file in adapters_dir.glob("*.py"):
        text = adapter_file.read_text(encoding="utf-8")
        assert "httpx.Client" not in text
        assert "follow_redirects" not in text
