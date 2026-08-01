"""
============================================================================
FILE: citation_validation.py
LOCATION: server/services/citation_validation.py
============================================================================
PURPOSE:
    Sanitizes grounded content markdown and citations against approved source IDs.
ROLE IN PROJECT:
    Ensures generated content only references approved research sources and
    strips unapproved external web links.
KEY COMPONENTS:
    - sanitize_grounded_content: Removes unapproved citations and strips URLs
DEPENDENCIES:
    - External: re
    - Internal: server.schemas.generation
USAGE:
    cleaned, valid_cites, warnings = sanitize_grounded_content(
        markdown, citations, approved_source_ids
    )
============================================================================
"""

from __future__ import annotations

import re
from typing import Sequence, Set

from server.schemas.generation import SourceCitation


_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")
_RAW_URL_PATTERN = re.compile(r"https?://\S+")


def sanitize_grounded_content(
    markdown: str,
    citations: Sequence[SourceCitation],
    approved_source_ids: Set[str],
) -> tuple[str, list[SourceCitation], list[str]]:
    """Sanitize content markdown and citations against approved source IDs.

    Args:
        markdown: Raw content markdown string.
        citations: List of SourceCitation objects.
        approved_source_ids: Set of valid source IDs.

    Returns:
        Tuple of (cleaned_markdown, valid_citations, warnings)
    """
    warnings: list[str] = []
    valid_citations: list[SourceCitation] = []

    for cite in citations:
        if cite.source_id in approved_source_ids:
            valid_citations.append(cite)
        else:
            if "removed_unsupported_citations" not in warnings:
                warnings.append("removed_unsupported_citations")

    cleaned_markdown = markdown

    # Replace [text](https://...) with text
    def _replace_link(match: re.Match) -> str:
        if "removed_unsupported_citations" not in warnings:
            warnings.append("removed_unsupported_citations")
        return match.group(1)

    if _MARKDOWN_LINK_PATTERN.search(cleaned_markdown):
        cleaned_markdown = _MARKDOWN_LINK_PATTERN.sub(_replace_link, cleaned_markdown)

    # Replace any leftover raw URLs
    if _RAW_URL_PATTERN.search(cleaned_markdown):
        if "removed_unsupported_citations" not in warnings:
            warnings.append("removed_unsupported_citations")
        cleaned_markdown = _RAW_URL_PATTERN.sub("", cleaned_markdown)

    return cleaned_markdown, valid_citations, warnings
