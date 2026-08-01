"""
============================================================================
FILE: _common.py
LOCATION: server/search/adapters/_common.py
============================================================================
PURPOSE:
    Shared normalization helpers for curated search adapters.
ROLE IN PROJECT:
    Keeps date parsing, publisher fallback, and safe request execution
    consistent across Tavily, Exa, Brave, and SerpAPI adapters.
KEY COMPONENTS:
    - parse_provider_datetime: Best-effort UTC-aware datetime parse
    - publisher_from_host: Hostname fallback publisher
    - execute_search_request: Shared request/error/capped-JSON path
DEPENDENCIES:
    - External: httpx
    - Internal: server.search.http, server.search.types
USAGE:
    from server.search.adapters._common import execute_search_request
============================================================================
"""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx

from server.search.http import raise_for_search_status, read_capped_json
from server.search.types import SearchError, SearchErrorClass, SearchProviderId

DEFAULT_RESPONSE_BYTE_CAP = 1_000_000


def parse_provider_datetime(value: Any) -> Optional[datetime]:
    """Parse common provider date strings into UTC-aware datetimes."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass
    try:
        # Date-only YYYY-MM-DD
        if len(text) == 10 and text[4] == "-" and text[7] == "-":
            parsed = datetime.strptime(text, "%Y-%m-%d")
            return parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        return None


def publisher_from_host(url: str) -> Optional[str]:
    """Return lowercase hostname from a URL for publisher fallback."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    return host.lower()


async def execute_search_request(
    client: httpx.AsyncClient,
    *,
    provider_id: SearchProviderId,
    method: str,
    url: str,
    timeout_seconds: float,
    headers: Optional[dict[str, str]] = None,
    json_body: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
    max_bytes: int = DEFAULT_RESPONSE_BYTE_CAP,
) -> tuple[Any, int]:
    """Perform one provider HTTP call with safe error mapping.

    Returns:
        Tuple of (parsed_json, response_byte_length).

    Raises:
        SearchError: Mapped provider/transport failures without body echo.
    """
    timeout = httpx.Timeout(timeout_seconds)
    try:
        async with client.stream(
            method,
            url,
            headers=headers,
            json=json_body,
            params=params,
            timeout=timeout,
            follow_redirects=False,
        ) as response:
            # Reject redirects explicitly (3xx)
            if response.is_redirect:
                raise SearchError(
                    provider_id=provider_id,
                    error_class=SearchErrorClass.INVALID_RESPONSE,
                    status_code=response.status_code,
                )

            raise_for_search_status(response, provider_id=provider_id)

            # Early reject when Content-Length already exceeds cap.
            content_length_header = response.headers.get("Content-Length")
            if content_length_header is not None:
                try:
                    stated_length = int(content_length_header)
                except ValueError:
                    stated_length = None
                else:
                    if stated_length > max_bytes:
                        raise SearchError(
                            provider_id=provider_id,
                            error_class=SearchErrorClass.INVALID_RESPONSE,
                            status_code=response.status_code,
                        )

            payload, raw_len = await read_capped_json(
                response,
                max_bytes=max_bytes,
                provider_id=provider_id,
                return_byte_count=True,
            )
            return payload, int(raw_len)
    except SearchError:
        raise
    except httpx.TimeoutException as exc:
        raise SearchError(
            provider_id=provider_id,
            error_class=SearchErrorClass.TIMEOUT,
        ) from exc
    except httpx.NetworkError as exc:
        raise SearchError(
            provider_id=provider_id,
            error_class=SearchErrorClass.AVAILABILITY,
        ) from exc
