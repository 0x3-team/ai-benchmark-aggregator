"""Strict JSON and embedded-script helpers for immutable evidence records.

The standard JSON decoder turns numeric tokens into Python numbers. That loses
source spelling such as 1.2300 or 1e-3 before admission can compare an adapter
claim with the captured bytes. These helpers retain number tokens as a distinct
string subtype and reject duplicate keys and non-standard constants.

They intentionally do not turn arbitrary JSON values into strings. A source
field is admissible only when its JSON type is appropriate for that field.
"""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import json
import re
from typing import Any


class JsonLexemeError(ValueError):
    """A JSON document cannot be used as exact source evidence."""


class JsonNumberLexeme(str):
    """The exact text of one JSON number token."""


_PATH_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")


def _reject_json_constant(value: str) -> None:
    raise JsonLexemeError(f"JSON constant {value!r} is not permitted")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise JsonLexemeError(f"duplicate JSON object key {key!r}")
        value[key] = item
    return value


def decode_json_bytes(raw_bytes: bytes) -> Any:
    """Decode UTF-8 JSON while retaining numeric lexical spelling exactly."""

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise JsonLexemeError("JSON evidence is not UTF-8") from exc
    try:
        return json.loads(
            text,
            parse_int=JsonNumberLexeme,
            parse_float=JsonNumberLexeme,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_object,
        )
    except (json.JSONDecodeError, JsonLexemeError, RecursionError) as exc:
        raise JsonLexemeError("JSON evidence is malformed or ambiguous") from exc


def parse_json_path(path: object) -> list[str | int] | None:
    """Parse the deliberately small JSONPath subset used by v1 locators."""

    if not isinstance(path, str) or not path.startswith("$"):
        return None
    tokens: list[str | int] = []
    index = 1
    while index < len(path):
        if path[index] == ".":
            index += 1
            match = _PATH_IDENTIFIER.match(path, index)
            if match is None:
                return None
            tokens.append(match.group(0))
            index = match.end()
            continue
        if path[index] == "[":
            end = path.find("]", index + 1)
            if end == -1 or not path[index + 1 : end].isdigit():
                return None
            tokens.append(int(path[index + 1 : end]))
            index = end + 1
            continue
        return None
    return tokens


def canonical_config_json_path(value: object) -> str | None:
    """Convert a configured dotted collection path into the locator syntax."""

    if not isinstance(value, str) or not value:
        return None
    path = value if value.startswith("$") else "$." + value.lstrip(".")
    return path if parse_json_path(path) is not None else None


def resolve_json_path(value: Any, path: object) -> tuple[Any | None, str | None]:
    """Resolve one JSONPath and return a stable evidence-style error."""

    tokens = parse_json_path(path)
    if tokens is None:
        return None, "EVIDENCE_LOCATOR_INVALID"
    current: Any = value
    for token in tokens:
        if isinstance(token, str) and isinstance(current, dict) and token in current:
            current = current[token]
        elif isinstance(token, int) and isinstance(current, list) and 0 <= token < len(current):
            current = current[token]
        else:
            return None, "EVIDENCE_NOT_FOUND"
    return current, None


def source_text(value: object) -> str | None:
    """Return a JSON string, never a number token or another JSON type."""

    if isinstance(value, str) and not isinstance(value, JsonNumberLexeme):
        return value
    return None


def source_score_lexeme(value: object) -> str | None:
    """Return an exact JSON string or retained JSON number token."""

    return value if isinstance(value, str) else None


@dataclass(frozen=True)
class _ScriptElement:
    element_id: str | None
    script_type: str | None
    has_src: bool
    duplicate_attributes: bool
    content: str


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.scripts: list[_ScriptElement] = []
        self.id_counts: dict[str, int] = {}
        self._current: dict[str, Any] | None = None

    def _record_element_id(self, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name.lower() == "id" and isinstance(value, str):
                self.id_counts[value] = self.id_counts.get(value, 0) + 1
                return

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record_element_id(attrs)
        if tag.lower() != "script":
            return
        names = [name.lower() for name, _value in attrs]
        values = {name.lower(): value for name, value in attrs}
        self._current = {
            "element_id": values.get("id"),
            "script_type": values.get("type"),
            "has_src": "src" in values,
            "duplicate_attributes": len(names) != len(set(names)),
            "content": [],
        }

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record_element_id(attrs)

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current["content"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or self._current is None:
            return
        self.scripts.append(
            _ScriptElement(
                element_id=self._current["element_id"],
                script_type=self._current["script_type"],
                has_src=self._current["has_src"],
                duplicate_attributes=self._current["duplicate_attributes"],
                content="".join(self._current["content"]),
            )
        )
        self._current = None


def decode_exact_json_script(
    raw_bytes: bytes, *, script_id: object, script_type: object
) -> tuple[Any | None, str | None]:
    """Resolve exactly one inline JSON script without first-match behavior."""

    if not isinstance(script_id, str) or not script_id:
        return None, "EVIDENCE_LOCATOR_INVALID"
    if script_type is not None and not isinstance(script_type, str):
        return None, "EVIDENCE_LOCATOR_INVALID"
    try:
        document = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None, "EVIDENCE_LOCATOR_INVALID"
    collector = _ScriptCollector()
    try:
        collector.feed(document)
        collector.close()
    except Exception:
        return None, "EVIDENCE_LOCATOR_INVALID"
    candidates = [element for element in collector.scripts if element.element_id == script_id]
    if collector.id_counts.get(script_id, 0) > 1:
        return None, "EVIDENCE_SCRIPT_AMBIGUOUS"
    if not candidates:
        return None, "EVIDENCE_NOT_FOUND"
    if len(candidates) != 1:
        return None, "EVIDENCE_SCRIPT_AMBIGUOUS"
    script = candidates[0]
    if script.has_src or script.duplicate_attributes or script.script_type != script_type:
        return None, "EVIDENCE_LOCATOR_INVALID"
    try:
        return decode_json_bytes(script.content.encode("utf-8")), None
    except JsonLexemeError:
        return None, "EVIDENCE_LOCATOR_INVALID"
