/**
 * ============================================================================
 * FILE: useSessionEvents.ts
 * LOCATION: client/src/features/learning/useSessionEvents.ts
 * ============================================================================
 *
 * PURPOSE:
 *    EventSource lifecycle for progressive generation progress events.
 *
 * ROLE IN PROJECT:
 *    Opens a credential-free SSE stream, applies events to React Query cache,
 *    and invalidates session/research queries for structural updates.
 *
 * KEY COMPONENTS:
 *    - useSessionEvents: Hook managing EventSource + cache updates
 *    - PROGRESS_EVENT_TYPES: All nine server event names
 *
 * DEPENDENCIES:
 *    - External: @tanstack/react-query
 *    - Internal: generationEvents, types
 *
 * USAGE:
 *    useSessionEvents(sessionId, enabled);
 * ============================================================================
 */

import { useEffect, useRef } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import {
  applyGenerationEvent,
  isTerminalGenerationStage,
} from './generationEvents';
import type { GenerationEvent, ProgressEventType } from '@/types/generation';
import type { LearningSessionWithNodes } from '@/types/learning';

const PROGRESS_EVENT_TYPES: readonly ProgressEventType[] = [
  'stage_changed',
  'research_section_ready',
  'research_degraded',
  'outline_ready',
  'module_ready',
  'module_failed',
  'generation_paused',
  'generation_cancelled',
  'generation_complete',
] as const;

const SESSION_INVALIDATING: ReadonlySet<ProgressEventType> = new Set([
  'outline_ready',
  'module_ready',
  'module_failed',
]);

const RESEARCH_INVALIDATING: ReadonlySet<ProgressEventType> = new Set([
  'research_section_ready',
  'research_degraded',
]);

const TERMINAL_EVENTS: ReadonlySet<ProgressEventType> = new Set([
  'generation_complete',
  'generation_cancelled',
]);

function parseGenerationEvent(raw: string): GenerationEvent | null {
  try {
    const parsed = JSON.parse(raw) as Partial<GenerationEvent>;
    if (
      typeof parsed.id !== 'number' ||
      typeof parsed.session_id !== 'string' ||
      typeof parsed.event_type !== 'string'
    ) {
      return null;
    }
    return parsed as GenerationEvent;
  } catch {
    return null;
  }
}

/**
 * Subscribe to session generation SSE while enabled.
 * Uses cached last_event_id as ?after= cursor. No credentials in URL.
 */
export function useSessionEvents(
  sessionId: string | undefined,
  enabled: boolean,
): void {
  const queryClient = useQueryClient();
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!sessionId || !enabled) {
      return;
    }

    const cached = queryClient.getQueryData<LearningSessionWithNodes>([
      'learningSession',
      sessionId,
    ]);
    const after = cached?.generation?.last_event_id ?? 0;
    const baseURL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    const url = `${baseURL}/learning/sessions/${sessionId}/events?after=${after}`;

    const source = new EventSource(url);
    sourceRef.current = source;

    const handleEvent = (message: MessageEvent) => {
      const event = parseGenerationEvent(String(message.data));
      if (!event) return;

      queryClient.setQueryData<LearningSessionWithNodes>(
        ['learningSession', sessionId],
        (prev) => {
          if (!prev) return prev;
          return applyGenerationEvent(prev, event);
        },
      );

      const type = event.event_type;
      if (SESSION_INVALIDATING.has(type) || TERMINAL_EVENTS.has(type)) {
        void queryClient.invalidateQueries({
          queryKey: ['learningSession', sessionId],
        });
      }
      if (RESEARCH_INVALIDATING.has(type) || TERMINAL_EVENTS.has(type)) {
        void queryClient.invalidateQueries({
          queryKey: ['courseResearch', sessionId],
        });
      }

      if (TERMINAL_EVENTS.has(type)) {
        source.close();
        sourceRef.current = null;
      }
    };

    for (const type of PROGRESS_EVENT_TYPES) {
      source.addEventListener(type, handleEvent as EventListener);
    }

    source.onerror = () => {
      // Leave EventSource for native reconnect; polling repairs gaps.
    };

    return () => {
      source.close();
      if (sourceRef.current === source) {
        sourceRef.current = null;
      }
    };
  }, [sessionId, enabled, queryClient]);
}

export { isTerminalGenerationStage };
