"""wikipedia-tables-mcp: fetch Wikipedia wikitext via Special:Export and parse wikitables."""

from .client import PageResult, SpecialExportClient, TableResult
from .wikitext.tables import Limits

__version__ = "0.1.0"

__all__ = [
    "SpecialExportClient",
    "PageResult",
    "TableResult",
    "Limits",
    "__version__",
]
