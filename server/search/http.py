"""
============================================================================
FILE: http.py
LOCATION: server/search/http.py
============================================================================
PURPOSE:
    Capped HTTP response reads, safe status mapping, retry-after parsing,
    and log redaction for search provider adapters.
ROLE IN PROJECT:
    Shared HTTP safety layer so adapters never call raise_for_status() or
    leak provider bodies and credentials into exceptions or logs.
KEY COMPONENTS:
    - map_http_status_to_error_class: Exact error matrix mapping
    - parse_retry_after: Safe Retry-After header parse
    - read_capped_json: Streamed JSON read with byte cap
    - SearchSecretRedactionFilter: Redacts secret query params in logs
    - install_search_log_redaction: Idempotent filter install on httpx
DEPENDENCIES:
    - External: httpx
    - Internal: server.search.types
USAGE:
    from server.search.http import map_http_status_to_error_class
============================================================================
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from server.search.types import SearchError, SearchErrorClass, SearchProviderId

logger = logging.getLogger(__name__)

_SECRET_QUERY_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "key",
        "token",
        "access_token",
        "signature",
        "secret",
    }
)

_URL_IN_TEXT_RE = re.compile(r"https?://[^\s\"']+", re.IGNORECASE)

_REDACTION_INSTALLED = False


def map_http_status_to_error_class(
    status_code: int,
    *,
    provider_id: Optional[SearchProviderId] = None,
) -> SearchErrorClass:
    """Map HTTP status codes to SearchErrorClass per the locked matrix.

    Args:
        status_code: HTTP response status.
        provider_id: Optional provider for provider-specific codes.

    Returns:
        Matching SearchErrorClass.
    """
    if status_code in {401, 403}:
        return SearchErrorClass.AUTHENTICATION
    if status_code in {400, 404, 422}:
        return SearchErrorClass.INVALID_REQUEST
    if status_code == 451:
        return SearchErrorClass.POLICY
    if status_code == 429:
        return SearchErrorClass.RATE_LIMIT
    if status_code == 402:
        return SearchErrorClass.QUOTA
    if (
        provider_id == SearchProviderId.TAVILY
        and status_code in {432, 433}
    ):
        return SearchErrorClass.QUOTA
    if 500 <= status_code <= 599:
        return SearchErrorClass.AVAILABILITY
    return SearchErrorClass.INVALID_RESPONSE


def parse_retry_after(value: Optional[str]) -> Optional[float]:
    """Parse Retry-After as non-negative seconds; reject invalid values.

    Args:
        value: Raw header value or None.

    Returns:
        Delay in seconds, or None when unusable.
    """
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        return None
    if seconds < 0:
        return None
    return seconds


def raise_for_search_status(
    response: httpx.Response,
    *,
    provider_id: SearchProviderId,
) -> None:
    """Raise a safe SearchError for non-success statuses without body echo.

    Args:
        response: httpx response (must not be consumed for error body).
        provider_id: Provider that produced the response.

    Raises:
        SearchError: For any status outside 200-299.
    """
    status = response.status_code
    if 200 <= status <= 299:
        if status != 200:
            # Redirects and non-200 success are rejected (follow_redirects=False)
            raise SearchError(
                provider_id=provider_id,
                error_class=SearchErrorClass.INVALID_RESPONSE,
                status_code=status,
            )
        return
    error_class = map_http_status_to_error_class(
        status, provider_id=provider_id
    )
    retry_after = parse_retry_after(response.headers.get("Retry-After"))
    raise SearchError(
        provider_id=provider_id,
        error_class=error_class,
        status_code=status,
        retry_after_seconds=retry_after,
    )


async def read_capped_json(
    response: httpx.Response,
    *,
    max_bytes: int,
    provider_id: SearchProviderId,
    return_byte_count: bool = False,
) -> Any:
    """Read response body up to max_bytes and parse JSON safely.

    Args:
        response: Successful httpx response (prefer streamed).
        max_bytes: Hard byte cap before INVALID_RESPONSE.
        provider_id: Provider for safe error tagging.
        return_byte_count: When True, return (payload, actual_bytes).

    Returns:
        Parsed JSON value, or (payload, actual_bytes) when requested.

    Raises:
        SearchError: On oversize body or malformed JSON.
    """
    if max_bytes < 1:
        raise SearchError(
            provider_id=provider_id,
            error_class=SearchErrorClass.INVALID_RESPONSE,
            status_code=response.status_code,
        )
    chunks: list[bytes] = []
    total = 0
    try:
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise SearchError(
                    provider_id=provider_id,
                    error_class=SearchErrorClass.INVALID_RESPONSE,
                    status_code=response.status_code,
                )
            chunks.append(chunk)
    except SearchError:
        raise
    except httpx.TimeoutException as exc:
        raise SearchError(
            provider_id=provider_id,
            error_class=SearchErrorClass.TIMEOUT,
            status_code=None,
        ) from exc
    except httpx.NetworkError as exc:
        raise SearchError(
            provider_id=provider_id,
            error_class=SearchErrorClass.AVAILABILITY,
            status_code=None,
        ) from exc
    raw = b"".join(chunks)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SearchError(
            provider_id=provider_id,
            error_class=SearchErrorClass.INVALID_RESPONSE,
            status_code=response.status_code,
        ) from exc
    if return_byte_count:
        return payload, total
    return payload


def redact_secret_query_values(url: str) -> str:
    """Rewrite secret-named query values in a URL string to [REDACTED]."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    pairs: list[tuple[str, str]] = []
    changed = False
    for name, value in parse_qsl(parts.query, keep_blank_values=True):
        if name.lower() in _SECRET_QUERY_NAMES:
            pairs.append((name, "[REDACTED]"))
            changed = True
        else:
            pairs.append((name, value))
    if not changed:
        return url
    # urlencode quotes brackets as %5B %5D matching test expectation
    redacted_query = urlencode(pairs, doseq=True)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, redacted_query, parts.fragment)
    )


class SearchSecretRedactionFilter(logging.Filter):
    """Logging filter that redacts secret query params in log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = message
        for match in _URL_IN_TEXT_RE.finditer(message):
            original = match.group(0)
            safe = redact_secret_query_values(original)
            if safe != original:
                redacted = redacted.replace(original, safe)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def install_search_log_redaction() -> None:
    """Install SearchSecretRedactionFilter once on httpx and httpcore loggers."""
    global _REDACTION_INSTALLED
    if _REDACTION_INSTALLED:
        return
    redaction_filter = SearchSecretRedactionFilter()
    for name in ("httpx", "httpcore"):
        target = logging.getLogger(name)
        already = any(
            isinstance(existing, SearchSecretRedactionFilter)
            for existing in target.filters
        )
        if not already:
            target.addFilter(redaction_filter)
    _REDACTION_INSTALLED = True
