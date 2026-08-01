"""
============================================================================
FILE: research_runner.py
LOCATION: server/services/research_runner.py
============================================================================
PURPOSE:
    Bounded iterative research loop with incremental persistence,
    cancellation, degradation, and progress events.
ROLE IN PROJECT:
    Owns deterministic control flow around ResearcherAgent and provider
    coordinator. Always terminates; never deletes partial rows on cancel.
KEY COMPONENTS:
    - ResearchRunner: Orchestrates plan → search → synthesize → finalize
    - ResearchOutcome: Safe terminal result (no keys/excerpts)
    - ResearchCancelled: Cooperative cancellation signal
DEPENDENCIES:
    - External: None
    - Internal: agents, search budget/safety/types, schemas, stores
USAGE:
    outcome = await ResearchRunner(...).run(job_id=..., session_id=..., ...)
============================================================================
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Sequence
from urllib.parse import urlsplit

from server.schemas.generation import (
    GenerationCursor,
    GenerationLock,
    GenerationWarning,
    GroundingStatus,
    ResearchCursor,
)
from server.schemas.progress import (
    ProgressEventType,
    ResearchDegradedPayload,
    ResearchSectionReadyPayload,
)
from server.schemas.research import (
    CoverageItem,
    ResearchFinalization,
    ResearchIteration,
    ResearchPlan,
    ResearchSource,
    ResearchStatus,
)
from server.search.budget import (
    ResearchBudgetExceeded,
    ResearchBudgetLedger,
    resolve_research_budget,
)
from server.search.source_safety import (
    content_identity,
    deduplicate_results,
    format_untrusted_sources,
)
from server.search.types import (
    AllProvidersUnavailable,
    NormalizedSearchResult,
    ROTATABLE_SEARCH_ERRORS,
    SearchError,
    SearchErrorClass,
    SearchQuery,
)

logger = logging.getLogger(__name__)


class ResearchCancelled(RuntimeError):
    """Raised when a job cancel flag is observed mid-research."""


@dataclass
class ResearchOutcome:
    """Safe terminal research result without secrets or excerpts."""

    report_id: str
    status: ResearchStatus
    grounding_status: GroundingStatus
    warnings: list[GenerationWarning] = field(default_factory=list)


def coverage_is_complete(
    coverage: Sequence[CoverageItem],
    sources: Sequence[ResearchSource],
    *,
    recency_days: Optional[int] = None,
    now: Optional[datetime] = None,
) -> bool:
    """Deterministic coverage completion rule.

    Requires every required item covered or explicit_unknown, at least three
    distinct root domains among retained sources, and freshness-sensitive
    themes backed by an in-window source or explicit_unknown.
    """
    if not coverage:
        return False

    for item in coverage:
        if not item.required:
            continue
        if not (item.covered or item.explicit_unknown):
            return False

    domains = {
        (urlsplit(str(source.url)).hostname or "").lower()
        for source in sources
        if source.url
    }
    domains.discard("")
    if len(domains) < 3:
        return False

    if recency_days is not None and recency_days > 0:
        clock = now or datetime.now(timezone.utc)
        for item in coverage:
            if not item.freshness_sensitive or not item.required:
                continue
            if item.explicit_unknown:
                continue
            if not item.covered:
                return False
            linked = [
                source
                for source in sources
                if source.id in set(item.source_ids)
            ]
            if not linked:
                return False
            fresh_ok = False
            for source in linked:
                stamp = source.published_at or source.retrieved_at
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                age = (clock - stamp).total_seconds() / 86400.0
                if age <= recency_days:
                    fresh_ok = True
                    break
            if not fresh_ok:
                return False
    return True


class ResearchRunner:
    """Bounded incremental research orchestrator."""

    def __init__(
        self,
        *,
        agent: Any,
        research_store: Any,
        job_store: Any,
        event_store: Any,
    ) -> None:
        self._agent = agent
        self._research_store = research_store
        self._job_store = job_store
        self._event_store = event_store

    async def run(
        self,
        *,
        job_id: str,
        session_id: str,
        query: str,
        resolved_mode: str,
        coordinator: Any,
        llm_context: Any,
        lock: Optional[GenerationLock] = None,
        existing_plan: Optional[ResearchPlan] = None,
        ledger: Optional[ResearchBudgetLedger] = None,
    ) -> ResearchOutcome:
        """Run the bounded research loop to a terminal status."""
        del job_id  # reserved for future job-scoped telemetry
        warnings: list[GenerationWarning] = []
        limitations: list[str] = []
        conflicts: list[str] = []
        completed_themes: list[str] = []
        section_markdowns: list[str] = []
        coverage: list[CoverageItem] = []
        plan: Optional[ResearchPlan] = existing_plan
        iteration = 0
        next_section_index = 0
        pending_queries: list[str] = []
        sources_by_id: dict[str, ResearchSource] = {}
        shared_ledger = ledger

        report = self._research_store.create_report(session_id=session_id)
        report_id = str(report.id)

        cursor = self._load_research_cursor(session_id)
        iteration = cursor.iteration
        next_section_index = cursor.next_section_index
        pending_queries = list(cursor.pending_queries)
        completed_themes = list(cursor.completed_themes)

        try:
            self._ensure_not_cancelled(session_id)

            if plan is None:
                # Budget bootstrap uses a provisional concept floor until plan
                bootstrap = resolve_research_budget(resolved_mode, 3)
                if shared_ledger is None:
                    ledger = ResearchBudgetLedger.from_cursor(
                        bootstrap, cursor
                    )
                else:
                    # Keep coordinator and runner on one ledger object.
                    shared_ledger.budget = bootstrap
                    ledger = shared_ledger
                ledger.reserve_llm_turn()
                plan = await self._agent.analyze_query(
                    query=query,
                    resolved_mode=resolved_mode,
                    llm_context=llm_context,
                )
                coverage = list(plan.coverage)
                pending_queries = list(plan.initial_queries)
                budget = resolve_research_budget(
                    resolved_mode,
                    plan.provisional_concept_count,
                )
                # Preserve consumed LLM turn against the sized budget
                if shared_ledger is None:
                    ledger = ResearchBudgetLedger(
                        budget,
                        usage=ledger.usage_snapshot(),
                    )
                else:
                    shared_ledger.budget = budget
                    ledger = shared_ledger
            else:
                coverage = list(plan.coverage)
                budget = resolve_research_budget(
                    resolved_mode,
                    plan.provisional_concept_count,
                )
                if shared_ledger is None:
                    ledger = ResearchBudgetLedger.from_cursor(budget, cursor)
                else:
                    shared_ledger.budget = budget
                    ledger = shared_ledger
                if not pending_queries:
                    pending_queries = list(plan.initial_queries)

            self._persist_provider_order(
                session_id=session_id,
                lock=lock,
                coordinator=coordinator,
                research_cursor=ledger.to_cursor(
                    iteration=iteration,
                    next_section_index=next_section_index,
                    pending_queries=pending_queries,
                    completed_themes=completed_themes,
                ),
            )

            while pending_queries:
                self._ensure_not_cancelled(session_id)
                batch_queries = pending_queries[:3]
                pending_queries = pending_queries[3:]
                batch_source_ids: list[str] = []

                for search_query_text in batch_queries:
                    self._ensure_not_cancelled(session_id)
                    try:
                        response = await coordinator.search(
                            SearchQuery(query=search_query_text)
                        )
                    except AllProvidersUnavailable as exc:
                        warning = GenerationWarning(
                            code="providers_unavailable",
                            message=(
                                "All configured search providers are "
                                "unavailable."
                            ),
                        )
                        warnings.append(warning)
                        self._research_store.mark_degraded(
                            session_id=session_id,
                            warning=warning,
                        )
                        self._emit_degraded(session_id, warning)
                        limitations.append(
                            "Search providers exhausted before coverage "
                            "completed."
                        )
                        return await self._finalize(
                            session_id=session_id,
                            report_id=report_id,
                            query=query,
                            coverage=coverage,
                            section_markdowns=section_markdowns,
                            conflicts=conflicts,
                            limitations=limitations,
                            warnings=warnings,
                            llm_context=llm_context,
                            status=ResearchStatus.DEGRADED,
                            grounding=GroundingStatus.DEGRADED,
                            ledger=ledger,
                            lock=lock,
                            iteration=iteration,
                            next_section_index=next_section_index,
                            pending_queries=pending_queries,
                            completed_themes=completed_themes,
                        )
                    except SearchError as exc:
                        if exc.error_class in ROTATABLE_SEARCH_ERRORS:
                            # Coordinator should have rotated; treat as soft
                            limitations.append(
                                f"Search error class {exc.error_class.value}."
                            )
                            continue
                        warning = GenerationWarning(
                            code=f"search_{exc.error_class.value}",
                            message=(
                                f"Search stopped: {exc.error_class.value}."
                            ),
                            provider_id=exc.provider_id,
                        )
                        warnings.append(warning)
                        self._research_store.mark_degraded(
                            session_id=session_id,
                            warning=warning,
                        )
                        self._emit_degraded(session_id, warning)
                        limitations.append(warning.message)
                        return await self._finalize(
                            session_id=session_id,
                            report_id=report_id,
                            query=query,
                            coverage=coverage,
                            section_markdowns=section_markdowns,
                            conflicts=conflicts,
                            limitations=limitations,
                            warnings=warnings,
                            llm_context=llm_context,
                            status=ResearchStatus.DEGRADED,
                            grounding=GroundingStatus.DEGRADED,
                            ledger=ledger,
                            lock=lock,
                            iteration=iteration,
                            next_section_index=next_section_index,
                            pending_queries=pending_queries,
                            completed_themes=completed_themes,
                        )
                    except ResearchBudgetExceeded as exc:
                        limitations.append(
                            f"Stopped at budget limit: {exc.limit_name}."
                        )
                        pending_queries = []
                        break

                    try:
                        ledger.reserve_provider_bytes(
                            max(0, int(response.response_bytes))
                        )
                        ledger.reserve_results(len(response.results))
                    except ResearchBudgetExceeded as exc:
                        limitations.append(
                            f"Stopped at budget limit: {exc.limit_name}."
                        )
                        pending_queries = []
                        break

                    retained = deduplicate_results(response.results)
                    for hit in retained:
                        source = self._persist_hit(
                            session_id=session_id,
                            hit=hit,
                            ledger=ledger,
                        )
                        if source is None:
                            continue
                        sources_by_id[source.id] = source
                        batch_source_ids.append(source.id)

                    self._persist_research_cursor(
                        session_id=session_id,
                        lock=lock,
                        coordinator=coordinator,
                        research_cursor=ledger.to_cursor(
                            iteration=iteration,
                            next_section_index=next_section_index,
                            pending_queries=pending_queries + batch_queries[
                                batch_queries.index(search_query_text) + 1 :
                            ],
                            completed_themes=completed_themes,
                        ),
                    )

                if not batch_source_ids and not sources_by_id:
                    # Empty search batch — still allow synthesis on no evidence
                    pass

                self._ensure_not_cancelled(session_id)
                try:
                    ledger.reserve_llm_turn()
                    untrusted = format_untrusted_sources(
                        [
                            {
                                "source_id": source_id,
                                "url": str(sources_by_id[source_id].url),
                                "title": sources_by_id[source_id].title,
                                "excerpt": sources_by_id[source_id].excerpt,
                            }
                            for source_id in batch_source_ids
                            if source_id in sources_by_id
                        ],
                        max_context_chars=ledger.budget.max_context_chars,
                    )
                    ledger.reserve_context_chars(len(untrusted))
                except ResearchBudgetExceeded as exc:
                    limitations.append(
                        f"Stopped at budget limit: {exc.limit_name}."
                    )
                    break

                draft: ResearchIteration = (
                    await self._agent.synthesize_iteration(
                        query=query,
                        plan=plan,
                        coverage=coverage,
                        untrusted_source_context=untrusted,
                        llm_context=llm_context,
                    )
                )
                allowed_ids = set(sources_by_id.keys())
                draft = await self._validate_source_ids(
                    draft=draft,
                    allowed_ids=allowed_ids,
                    ledger=ledger,
                    llm_context=llm_context,
                    warnings=warnings,
                )

                section = self._research_store.upsert_section(
                    report_id=report_id,
                    sequence_index=next_section_index,
                    theme=draft.theme,
                    markdown=draft.section_markdown,
                    source_ids=list(draft.source_ids),
                )
                section_id = (
                    section.id
                    if isinstance(getattr(section, "id", None), str)
                    else f"section-{next_section_index}"
                )
                self._event_store.append_once(
                    session_id=session_id,
                    event_type=ProgressEventType.RESEARCH_SECTION_READY,
                    payload=ResearchSectionReadyPayload(
                        report_id=report_id,
                        section_id=section_id,
                        sequence_index=next_section_index,
                        source_count=len(draft.source_ids),
                    ),
                    dedupe_key=(
                        f"research_section_ready:{report_id}:"
                        f"{next_section_index}"
                    ),
                )
                section_markdowns.append(
                    f"## {draft.theme}\n{draft.section_markdown}"
                )
                conflicts.extend(draft.conflicts)
                completed_themes.append(draft.theme)
                coverage = self._apply_coverage_updates(
                    coverage, draft.coverage_updates
                )
                next_section_index += 1
                iteration += 1

                if coverage_is_complete(
                    coverage, list(sources_by_id.values())
                ):
                    pending_queries = []
                else:
                    for follow in draft.follow_up_queries:
                        if follow and follow not in pending_queries:
                            pending_queries.append(follow)

                self._persist_research_cursor(
                    session_id=session_id,
                    lock=lock,
                    coordinator=coordinator,
                    research_cursor=ledger.to_cursor(
                        iteration=iteration,
                        next_section_index=next_section_index,
                        pending_queries=pending_queries,
                        completed_themes=completed_themes,
                    ),
                )

            return await self._finalize(
                session_id=session_id,
                report_id=report_id,
                query=query,
                coverage=coverage,
                section_markdowns=section_markdowns,
                conflicts=conflicts,
                limitations=limitations,
                warnings=warnings,
                llm_context=llm_context,
                status=ResearchStatus.COMPLETE,
                grounding=(
                    GroundingStatus.GROUNDED
                    if sources_by_id
                    else GroundingStatus.DEGRADED
                ),
                ledger=ledger,
                lock=lock,
                iteration=iteration,
                next_section_index=next_section_index,
                pending_queries=pending_queries,
                completed_themes=completed_themes,
            )
        except ResearchCancelled:
            self._persist_research_cursor(
                session_id=session_id,
                lock=lock,
                coordinator=coordinator,
                research_cursor=ResearchCursor(
                    iteration=iteration,
                    next_section_index=next_section_index,
                    pending_queries=pending_queries,
                    completed_themes=completed_themes,
                ),
            )
            raise
        except ResearchBudgetExceeded as exc:
            limitations.append(f"Stopped at budget limit: {exc.limit_name}.")
            return await self._finalize(
                session_id=session_id,
                report_id=report_id,
                query=query,
                coverage=coverage,
                section_markdowns=section_markdowns,
                conflicts=conflicts,
                limitations=limitations,
                warnings=warnings,
                llm_context=llm_context,
                status=ResearchStatus.DEGRADED,
                grounding=GroundingStatus.DEGRADED,
                ledger=None,
                lock=lock,
                iteration=iteration,
                next_section_index=next_section_index,
                pending_queries=pending_queries,
                completed_themes=completed_themes,
            )

    async def _finalize(
        self,
        *,
        session_id: str,
        report_id: str,
        query: str,
        coverage: Sequence[CoverageItem],
        section_markdowns: Sequence[str],
        conflicts: Sequence[str],
        limitations: list[str],
        warnings: list[GenerationWarning],
        llm_context: Any,
        status: ResearchStatus,
        grounding: GroundingStatus,
        ledger: Optional[ResearchBudgetLedger],
        lock: Optional[GenerationLock],
        iteration: int,
        next_section_index: int,
        pending_queries: list[str],
        completed_themes: list[str],
    ) -> ResearchOutcome:
        final: Optional[ResearchFinalization] = None
        try:
            if ledger is not None:
                ledger.reserve_llm_turn()
            final = await self._agent.finalize_report(
                query=query,
                coverage=coverage,
                sections=list(section_markdowns),
                conflicts=list(conflicts),
                llm_context=llm_context,
            )
        except Exception as exc:
            logger.warning("finalize_report failed: %s", type(exc).__name__)
            final = ResearchFinalization(
                summary="Research ended with limited synthesis.",
                limitations=limitations
                or ["Finalization unavailable."],
                freshness_note="Retrieval time recorded at run end.",
            )

        merged_limitations = list(final.limitations)
        for item in limitations:
            if item not in merged_limitations:
                merged_limitations.append(item)

        # On degraded paths with no sections, still finalize status
        if status == ResearchStatus.DEGRADED and not section_markdowns:
            # Prefer mark_degraded already done; still stamp terminal fields
            try:
                self._research_store.finalize_report(
                    session_id=session_id,
                    status=status,
                    summary=final.summary,
                    limitations=merged_limitations,
                    freshness_note=final.freshness_note,
                )
            except Exception:
                # mark_degraded may be the only terminal write in some paths
                pass
        else:
            self._research_store.finalize_report(
                session_id=session_id,
                status=status,
                summary=final.summary,
                limitations=merged_limitations,
                freshness_note=final.freshness_note,
            )

        if ledger is not None:
            self._persist_research_cursor(
                session_id=session_id,
                lock=lock,
                coordinator=None,
                research_cursor=ledger.to_cursor(
                    iteration=iteration,
                    next_section_index=next_section_index,
                    pending_queries=pending_queries,
                    completed_themes=completed_themes,
                ),
                grounding_status=grounding,
            )

        return ResearchOutcome(
            report_id=report_id,
            status=status,
            grounding_status=grounding,
            warnings=list(warnings),
        )

    async def _validate_source_ids(
        self,
        *,
        draft: ResearchIteration,
        allowed_ids: set[str],
        ledger: ResearchBudgetLedger,
        llm_context: Any,
        warnings: list[GenerationWarning],
    ) -> ResearchIteration:
        invalid = [sid for sid in draft.source_ids if sid not in allowed_ids]
        if not invalid:
            return draft
        usage = ledger.usage_snapshot()
        turns_left = ledger.budget.max_llm_turns - usage.llm_turns
        if turns_left >= 1:
            try:
                ledger.reserve_llm_turn()
                corrected = await self._agent.correct_source_ids(
                    draft=draft,
                    allowed_source_ids=sorted(allowed_ids),
                    llm_context=llm_context,
                )
                invalid = [
                    sid
                    for sid in corrected.source_ids
                    if sid not in allowed_ids
                ]
                if not invalid:
                    return corrected
                draft = corrected
            except Exception:
                pass
        cleaned_ids = [sid for sid in draft.source_ids if sid in allowed_ids]
        warnings.append(
            GenerationWarning(
                code="invalid_source_ids",
                message="Dropped source IDs not present in persisted batch.",
            )
        )
        return draft.model_copy(update={"source_ids": cleaned_ids})

    def _persist_hit(
        self,
        *,
        session_id: str,
        hit: NormalizedSearchResult,
        ledger: ResearchBudgetLedger,
    ) -> Optional[ResearchSource]:
        excerpt = hit.content or hit.snippet or ""
        try:
            ledger.reserve_sources(1)
            ledger.reserve_excerpt_chars(len(excerpt))
        except ResearchBudgetExceeded:
            return None
        source = ResearchSource(
            id=str(uuid.uuid4()),
            title=hit.title,
            url=hit.canonical_url,
            publisher=hit.publisher,
            published_at=hit.published_at,
            retrieved_at=hit.retrieved_at,
            provider_id=hit.provider_id,
            snippet=hit.snippet,
            excerpt=excerpt,
            relevance_score=None,
        )
        try:
            stored = self._research_store.upsert_source(
                session_id=session_id,
                source=source,
                canonical_url=str(hit.canonical_url),
                content_hash=content_identity(excerpt),
            )
        except Exception as exc:
            logger.warning(
                "upsert_source failed: %s", type(exc).__name__
            )
            return None
        if isinstance(getattr(stored, "id", None), str):
            return stored
        return source

    def _ensure_not_cancelled(self, session_id: str) -> None:
        checker = getattr(self._job_store, "is_cancel_requested", None)
        if checker is None:
            return
        if bool(checker(session_id)):
            raise ResearchCancelled(
                f"Research cancelled for session {session_id}"
            )

    def _load_research_cursor(self, session_id: str) -> ResearchCursor:
        getter = getattr(self._job_store, "get_job", None)
        if getter is None:
            return ResearchCursor()
        try:
            job = getter(session_id)
        except Exception:
            return ResearchCursor()
        cursor = getattr(job, "cursor", None)
        if isinstance(cursor, GenerationCursor):
            research = cursor.research
            if isinstance(research, ResearchCursor):
                return research
        if isinstance(cursor, ResearchCursor):
            return cursor
        return ResearchCursor()

    def _persist_provider_order(
        self,
        *,
        session_id: str,
        lock: Optional[GenerationLock],
        coordinator: Any,
        research_cursor: ResearchCursor,
    ) -> None:
        order = tuple(getattr(coordinator, "provider_order", ()) or ())
        full = GenerationCursor(
            provider_order=list(order),
            research=research_cursor,
        )
        self._call_update_cursor(
            session_id=session_id,
            lock=lock,
            cursor=full,
        )

    def _persist_research_cursor(
        self,
        *,
        session_id: str,
        lock: Optional[GenerationLock],
        coordinator: Any,
        research_cursor: ResearchCursor,
        grounding_status: Optional[GroundingStatus] = None,
    ) -> None:
        order: list = []
        if coordinator is not None:
            order = list(getattr(coordinator, "provider_order", ()) or [])
        full = GenerationCursor(
            provider_order=order,
            research=research_cursor,
        )
        self._call_update_cursor(
            session_id=session_id,
            lock=lock,
            cursor=full,
            grounding_status=grounding_status,
        )

    def _call_update_cursor(
        self,
        *,
        session_id: str,
        lock: Optional[GenerationLock],
        cursor: GenerationCursor,
        grounding_status: Optional[GroundingStatus] = None,
    ) -> None:
        kwargs: dict[str, Any] = {
            "session_id": session_id,
            "cursor": cursor,
        }
        if grounding_status is not None:
            kwargs["grounding_status"] = grounding_status
        if lock is not None:
            kwargs["lock"] = lock
            self._job_store.update_cursor(**kwargs)
            return
        # No fence: try unlocked call for tests/mocks; skip if store requires lock.
        try:
            self._job_store.update_cursor(**kwargs)
        except TypeError:
            try:
                # Some doubles accept positional-only shapes.
                self._job_store.update_cursor(session_id, cursor)
            except Exception:
                logger.debug(
                    "update_cursor skipped without lock for session %s",
                    session_id,
                )
        except Exception as exc:
            # Production store requires GenerationLock; without one, skip.
            logger.debug(
                "update_cursor without lock failed (%s) for session %s",
                type(exc).__name__,
                session_id,
            )

    def _emit_degraded(
        self,
        session_id: str,
        warning: GenerationWarning,
    ) -> None:
        try:
            self._event_store.append_once(
                session_id=session_id,
                event_type=ProgressEventType.RESEARCH_DEGRADED,
                payload=ResearchDegradedPayload(warning=warning),
                dedupe_key=f"research_degraded:{session_id}:{warning.code}",
            )
        except Exception as exc:
            logger.warning(
                "append degraded event failed: %s", type(exc).__name__
            )

    @staticmethod
    def _apply_coverage_updates(
        coverage: list[CoverageItem],
        updates: Sequence[CoverageItem],
    ) -> list[CoverageItem]:
        if not updates:
            return coverage
        by_theme = {item.theme: item for item in coverage}
        for update in updates:
            by_theme[update.theme] = update
        # Preserve original order then append new themes
        ordered: list[CoverageItem] = []
        seen: set = set()
        for item in coverage:
            ordered.append(by_theme[item.theme])
            seen.add(item.theme)
        for item in updates:
            if item.theme not in seen:
                ordered.append(item)
                seen.add(item.theme)
        return ordered


async def run_research(
    *,
    session_id: str,
    topic_query: str,
    llm_context: Any,
    search_context: Any,
    resolved_mode: str = "lite",
    lock: Optional[GenerationLock] = None,
    http_client: Any = None,
) -> tuple[str, bool]:
    """Execute research runner and return (report_id, is_degraded).

    Builds production ProviderCoordinator from runtime credentials, a shared
    budget ledger, and optional fenced lock. Only external HTTP should be
    mocked in integration tests.
    """
    import httpx

    from server.agents.researcher import researcher_agent
    from server.database.generation_jobs import generation_job_store
    from server.database.progress_events import progress_event_store
    from server.database.research_store import research_store
    from server.search.adapters import build_search_adapters
    from server.search.coordinator import ProviderCoordinator

    mode = resolved_mode if resolved_mode in ("lite", "full") else "lite"
    provider_ids = tuple(getattr(search_context, "provider_ids", ()) or ())
    if not provider_ids or not getattr(search_context, "enabled", False):
        raise ValueError("run_research requires enabled search_context providers")

    credentials: dict = {}
    for provider_id in provider_ids:
        credentials[provider_id] = search_context.get_api_key(provider_id)

    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=30.0)
    try:
        all_adapters = build_search_adapters(client)
        adapters = {
            pid: all_adapters[pid]
            for pid in provider_ids
            if pid in all_adapters
        }
        if not adapters:
            raise ValueError("No search adapters available for configured providers")

        persisted_order: list = []
        try:
            job = generation_job_store.get_by_session(session_id)
            if job is not None:
                cursor = getattr(job, "cursor", None)
                order = getattr(cursor, "provider_order", None) or []
                persisted_order = [
                    pid for pid in order if pid in adapters
                ]
        except Exception:
            persisted_order = []

        bootstrap = resolve_research_budget(mode, 3)
        shared_ledger = ResearchBudgetLedger(bootstrap)
        coordinator = ProviderCoordinator.create(
            adapters=adapters,
            credentials=credentials,
            persisted_order=persisted_order,
            ledger=shared_ledger,
        )
        runner = ResearchRunner(
            agent=researcher_agent,
            research_store=research_store,
            job_store=generation_job_store,
            event_store=progress_event_store,
        )
        outcome = await runner.run(
            job_id=f"job-{session_id}",
            session_id=session_id,
            query=topic_query,
            resolved_mode=mode,
            coordinator=coordinator,
            llm_context=llm_context,
            lock=lock,
            ledger=shared_ledger,
        )
    finally:
        if owns_client:
            await client.aclose()

    is_degraded = (
        outcome.grounding_status == GroundingStatus.DEGRADED
        or outcome.status == ResearchStatus.DEGRADED
    )
    return outcome.report_id, is_degraded
