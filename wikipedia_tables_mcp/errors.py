"""Structured error types for wikipedia-tables-mcp.

See docs/specs/005-public-api.md section 4 for the tree and the policy on
which errors cross the SpecialExportClient boundary as exceptions versus
result fields.
"""

from __future__ import annotations


class SpecialExportError(Exception):
    """Base class for every error this package raises."""

    def __init__(
        self,
        message: str,
        *,
        title: str | None = None,
        status_code: int | None = None,
        raw: str | None = None,
        table_index: int | None = None,
        row: int | None = None,
        column: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.title = title
        self.status_code = status_code
        self.raw = raw
        self.table_index = table_index
        self.row = row
        self.column = column


class ConfigurationError(SpecialExportError):
    """Empty or invalid User-Agent, bad base URL, or other misconfiguration."""


class FetchError(SpecialExportError):
    """Network failure, or a non-retryable HTTP status."""


class RateLimitError(FetchError):
    """HTTP 429 after retries are exhausted."""


class ExportParseError(SpecialExportError):
    """Response is not valid export XML, or has no <text> element."""


class PageNotFoundError(SpecialExportError):
    """Requested title is absent from the export response.

    Raised by the fetch layer only. The client layer converts this into
    exists=False plus error, never raising it to its own caller.
    """


class WikitextParseError(SpecialExportError):
    """A wikitext structure (table, section, inline markup) could not be parsed."""


class TemplateResolutionError(SpecialExportError):
    """A template could not be resolved, raised only when strict=True."""
