"""Tier 3: raw wikitext cell value to plain text.

Fixed order of operations -- see docs/specs/003-inline-and-templates.md
section 1. Each step's regex operates on the output of the step before it.
"""

from __future__ import annotations

import html
import re

from .templates import TemplateWarning, resolve_templates

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_REF_PAIR_RE = re.compile(r"<ref\b[^>]*>.*?</ref\s*>", re.IGNORECASE | re.DOTALL)
_REF_SELFCLOSE_RE = re.compile(r"<ref\b[^>]*/>", re.IGNORECASE)
_NOWIKI_RE = re.compile(r"<nowiki\s*>(.*?)</nowiki\s*>", re.IGNORECASE | re.DOTALL)

_WIKILINK_RE = re.compile(r"\[\[(.*?)\]\]", re.DOTALL)
_EXTERNAL_LINK_RE = re.compile(r"\[(https?://[^\s\]]+)(?:\s+([^\]]*))?\]")

_BOLD_RE = re.compile(r"'''(.*?)'''", re.DOTALL)
_ITALIC_RE = re.compile(r"''(.*?)''", re.DOTALL)
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")

_REF_MARKER_RE = re.compile(r"\[(?:\d+|[a-z]|note\s*\d+|citation needed)\]", re.IGNORECASE)

_DROPPED_NAMESPACES = {"file", "image", "category", "media"}

_NOWIKI_PLACEHOLDER = "\x00NOWIKI{}\x00"


def clean_cell(
    raw: str,
    *,
    strict: bool = False,
    table_index: int | None = None,
    row: int | None = None,
    column: int | None = None,
) -> tuple[str, list[TemplateWarning]]:
    """Turn one raw wikitext cell value into plain text plus any warnings."""
    warnings: list[TemplateWarning] = []

    text = _COMMENT_RE.sub("", raw)
    text = _REF_PAIR_RE.sub("", text)
    text = _REF_SELFCLOSE_RE.sub("", text)
    text, nowiki_stash = _extract_nowiki(text)
    text = resolve_templates(
        text,
        strict=strict,
        warnings=warnings,
        table_index=table_index,
        row=row,
        column=column,
    )
    text = _WIKILINK_RE.sub(_resolve_wikilink, text)
    text = _EXTERNAL_LINK_RE.sub(_resolve_external_link, text)
    text = _strip_formatting(text)
    text = _decode_entities(text)
    text = _REF_MARKER_RE.sub("", text)
    text = _restore_nowiki(text, nowiki_stash)
    text = _collapse_whitespace(text)

    return text, warnings


def _extract_nowiki(text: str) -> tuple[str, list[str]]:
    stash: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        stash.append(match.group(1))
        return _NOWIKI_PLACEHOLDER.format(len(stash) - 1)

    return _NOWIKI_RE.sub(_replace, text), stash


def _restore_nowiki(text: str, stash: list[str]) -> str:
    for i, literal in enumerate(stash):
        text = text.replace(_NOWIKI_PLACEHOLDER.format(i), literal)
    return text


def _resolve_wikilink(match: re.Match[str]) -> str:
    content = match.group(1)
    parts = content.split("|")
    target = parts[0].strip()

    ns_split = target.split(":", 1)
    if len(ns_split) == 2 and ns_split[0].strip().lower() in _DROPPED_NAMESPACES:
        return ""

    if len(parts) > 1:
        return parts[-1].strip()
    return target.split("#", 1)[0].strip()


def _resolve_external_link(match: re.Match[str]) -> str:
    url, text = match.group(1), match.group(2)
    return text.strip() if text else url


def _strip_formatting(text: str) -> str:
    text = _BOLD_RE.sub(r"\1", text)
    text = _ITALIC_RE.sub(r"\1", text)
    text = _BR_RE.sub(" ", text)
    text = _TAG_RE.sub("", text)
    return text


def _decode_entities(text: str) -> str:
    text = text.replace("&nbsp;", " ")
    text = html.unescape(text)
    return text.replace("\xa0", " ")


def _collapse_whitespace(text: str) -> str:
    return " ".join(text.split())
