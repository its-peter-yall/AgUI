"""
============================================================================
FILE: concept_chat_search.py
LOCATION: server/services/concept_chat_search.py
============================================================================
PURPOSE:
    One-shot web search helper and OpenAI tool schema for concept chat.
ROLE IN PROJECT:
    Gives the concept-chat assistant a web_search tool backed by the same
    adapters and ProviderCoordinator as Researcher, without research jobs.
    - Exposes a stable tool definition (constraints in the description)
    - Caps coordinator retries with a tiny duck-typed ledger
    - Runs a single SearchQuery and always closes the httpx client
KEY COMPONENTS:
    - WEB_SEARCH_TOOL: OpenAI function schema (query only)
    - ChatSearchLedger: 2x-provider call cap and 25s monotonic window
    - one_shot_chat_search: Filter adapters and run ProviderCoordinator
DEPENDENCIES:
    - External: httpx
    - Internal: server.schemas.search, server.search adapters/coordinator/types
USAGE:
    from server.services.concept_chat_search import (
        WEB_SEARCH_TOOL,
        one_shot_chat_search,
    )
    response = await one_shot_chat_search(search_context, query)
============================================================================
"""

from __future__ import annotations

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the public web for current facts, versions, APIs, or "
            "news that the concept card does not cover. Use only when the "
            "concept content and prior messages lack the context needed to "
            "answer. Do not search if prior web_search results already "
            "cover the question. One search per turn. Write one meticulous "
            "query using specific terms, versions, and concept-title "
            "disambiguation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Single meticulous search query. Include specific "
                        "terms, versions, and the concept title when needed "
                        "to disambiguate."
                    ),
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}
