"""
============================================================================
FILE: coordinator.py
LOCATION: server/search/coordinator.py
============================================================================
PURPOSE:
    One-time provider order, explicit retry, and approved rotation for
    job-local search provider failover.
ROLE IN PROJECT:
    Owns deterministic multi-provider search policy without hidden retries.
    - Shuffles configured providers once per job when no order persisted
    - Retries rate/timeout/availability once within budget then rotates
    - Never rotates on auth/invalid/policy/invalid-response
KEY COMPONENTS:
    - ProviderCoordinator: Job-scoped coordinator with private credentials
DEPENDENCIES:
    - External: None (stdlib random/asyncio)
    - Internal: server.search.types, server.search.registry
USAGE:
    coordinator = ProviderCoordinator.create(adapters=..., credentials=...)
    response = await coordinator.search(query)
============================================================================
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence

from server.search.registry import SEARCH_PROVIDER_REGISTRY
from server.search.types import (
    ROTATABLE_SEARCH_ERRORS,
    AllProvidersUnavailable,
    SearchError,
    SearchErrorClass,
    SearchProviderId,
    SearchQuery,
    SearchResponse,
)

SleepFn = Callable[[float], Awaitable[None]]
JitterFn = Callable[[float], float]
LedgerLike = Any


class ProviderCoordinator:
    """Coordinates enabled search adapters with explicit failover policy."""

    def __init__(
        self,
        *,
        adapters: Mapping[SearchProviderId, Any],
        credentials: Mapping[SearchProviderId, str],
        provider_order: Sequence[SearchProviderId],
        ledger: LedgerLike,
        sleep: SleepFn,
        jitter: JitterFn,
    ) -> None:
        self._adapters = dict(adapters)
        # Private; excluded from repr
        self._credentials = dict(credentials)
        self._provider_order = tuple(provider_order)
        self._ledger = ledger
        self._sleep = sleep
        self._jitter = jitter
        self._unavailable: set[SearchProviderId] = set()

    def __repr__(self) -> str:
        return (
            f"ProviderCoordinator(provider_order={self._provider_order!r}, "
            f"unavailable={sorted(p.value for p in self._unavailable)!r})"
        )

    @property
    def provider_order(self) -> tuple[SearchProviderId, ...]:
        """Immutable configured provider order for this job."""
        return self._provider_order

    @classmethod
    def create(
        cls,
        *,
        adapters: Mapping[SearchProviderId, Any],
        credentials: Mapping[SearchProviderId, str],
        persisted_order: Sequence[SearchProviderId],
        ledger: LedgerLike,
        rng: Optional[random.Random] = None,
        sleep: Optional[SleepFn] = None,
        jitter: Optional[JitterFn] = None,
    ) -> "ProviderCoordinator":
        """Build a coordinator with validated adapters and one-time order.

        Args:
            adapters: Enabled adapters keyed by provider ID.
            credentials: API keys keyed by the same provider IDs.
            persisted_order: Prior job order, or empty to shuffle once.
            ledger: Budget ledger exposing reserve_search_call/remaining_seconds.
            rng: Optional RNG used only for initial shuffle.
            sleep: Async sleep used for retry backoff.
            jitter: Delay jitter function (identity in tests).

        Returns:
            Configured ProviderCoordinator.

        Raises:
            ValueError: On empty or mismatched adapter/credential sets.
        """
        adapter_ids = set(adapters.keys())
        credential_ids = set(credentials.keys())
        if not adapter_ids:
            raise ValueError("At least one search adapter is required")
        if adapter_ids != credential_ids:
            raise ValueError(
                "Adapter and credential provider IDs must match exactly"
            )
        for provider_id, key in credentials.items():
            if not key or not str(key).strip():
                raise ValueError(
                    f"Missing credential for provider {provider_id.value}"
                )

        if persisted_order:
            order = tuple(persisted_order)
            if set(order) != adapter_ids or len(order) != len(adapter_ids):
                raise ValueError(
                    "Persisted provider order must be a permutation of "
                    "configured provider IDs"
                )
        else:
            # Registry insertion order, then shuffle exactly once.
            registry_ids = [
                provider_id
                for provider_id in SEARCH_PROVIDER_REGISTRY
                if provider_id in adapter_ids
            ]
            # Include any unexpected IDs deterministically after registry ones
            extras = sorted(
                (pid for pid in adapter_ids if pid not in set(registry_ids)),
                key=lambda pid: pid.value,
            )
            order_list = registry_ids + extras
            active_rng = rng if rng is not None else random.Random()
            active_rng.shuffle(order_list)
            order = tuple(order_list)

        async def default_sleep(delay: float) -> None:
            await asyncio.sleep(delay)

        def default_jitter(delay: float) -> float:
            # Small positive jitter without requiring RNG injection
            span = max(delay * 0.25, 0.05)
            active = rng if rng is not None else random.Random()
            return delay + active.uniform(0.0, span)

        return cls(
            adapters=adapters,
            credentials=credentials,
            provider_order=order,
            ledger=ledger,
            sleep=sleep or default_sleep,
            jitter=jitter or default_jitter,
        )

    async def search(
        self,
        query: SearchQuery,
        *,
        timeout_seconds: float = 20.0,
    ) -> SearchResponse:
        """Search using the current healthy provider with approved failover.

        Raises:
            SearchError: Non-rotatable failures (auth/invalid/policy/response).
            AllProvidersUnavailable: Every configured provider failed rotatably.
            ResearchBudgetExceeded: Propagated from ledger.reserve_search_call.
        """
        last_rotatable: Optional[SearchError] = None

        while True:
            provider_id = self._next_healthy_provider()
            if provider_id is None:
                raise AllProvidersUnavailable(provider_ids=self._provider_order)

            adapter = self._adapters[provider_id]
            api_key = self._credentials[provider_id]

            try:
                return await self._attempt_provider(
                    adapter=adapter,
                    provider_id=provider_id,
                    api_key=api_key,
                    query=query,
                    timeout_seconds=timeout_seconds,
                )
            except SearchError as exc:
                if exc.error_class not in ROTATABLE_SEARCH_ERRORS:
                    raise
                last_rotatable = exc
                self._unavailable.add(provider_id)
                continue

        # Unreachable; keeps type checkers happy
        if last_rotatable is not None:
            raise last_rotatable
        raise AllProvidersUnavailable(provider_ids=self._provider_order)

    def _next_healthy_provider(self) -> Optional[SearchProviderId]:
        for provider_id in self._provider_order:
            if provider_id not in self._unavailable:
                return provider_id
        return None

    async def _attempt_provider(
        self,
        *,
        adapter: Any,
        provider_id: SearchProviderId,
        api_key: str,
        query: SearchQuery,
        timeout_seconds: float,
    ) -> SearchResponse:
        """Try one provider with at most one approved same-provider retry."""
        # First attempt
        self._ledger.reserve_search_call()
        try:
            return await adapter.search(
                query,
                api_key=api_key,
                timeout_seconds=timeout_seconds,
            )
        except SearchError as first_error:
            if first_error.error_class not in ROTATABLE_SEARCH_ERRORS:
                raise
            if first_error.error_class == SearchErrorClass.QUOTA:
                # Quota: no same-provider retry; rotate immediately
                raise
            # rate/timeout/availability: one retry within budget
            await self._backoff(first_error)
            self._ledger.reserve_search_call()
            try:
                return await adapter.search(
                    query,
                    api_key=api_key,
                    timeout_seconds=timeout_seconds,
                )
            except SearchError as second_error:
                if second_error.error_class not in ROTATABLE_SEARCH_ERRORS:
                    raise
                # Second rotatable failure → mark unavailable via outer loop
                raise second_error

    async def _backoff(self, error: SearchError) -> None:
        remaining = 2.0
        remaining_fn = getattr(self._ledger, "remaining_seconds", None)
        if callable(remaining_fn):
            try:
                remaining = float(remaining_fn())
            except Exception:
                remaining = 2.0
        base = error.retry_after_seconds
        if base is None:
            base = self._jitter(0.25)
        delay = min(base, 2.0, max(remaining, 0.0))
        if delay > 0:
            await self._sleep(delay)
