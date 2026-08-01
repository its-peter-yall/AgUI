/**
 * ============================================================================
 * FILE: generationEvents.ts
 * LOCATION: client/src/features/learning/generationEvents.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Immutable event-ID reducer for progressive generation session cache.
 *
 * ROLE IN PROJECT:
 *    Applies SSE generation snapshots to React Query cache while rejecting
 *    duplicate and out-of-order event IDs.
 *
 * KEY COMPONENTS:
 *    - applyGenerationEvent: Pure session cache reducer
 *    - isTerminalGenerationStage: Terminal stage helper
 *
 * DEPENDENCIES:
 *    - External: None
 *    - Internal: @/types/generation, @/types/learning
 *
 * USAGE:
 *    const next = applyGenerationEvent(session, event);
 * ============================================================================
 */

import type { GenerationEvent, GenerationJobPublic, GenerationStage } from '@/types/generation';
import type { LearningSessionWithNodes } from '@/types/learning';

const TERMINAL_STAGES: ReadonlySet<GenerationStage> = new Set([
  'COMPLETE',
  'COMPLETE_DEGRADED',
  'CANCELLED',
  'FAILED',
]);

export function isTerminalGenerationStage(
  stage: GenerationStage | undefined | null,
): boolean {
  if (!stage) return true;
  return TERMINAL_STAGES.has(stage);
}

/**
 * Applies a generation event to a session cache entry.
 * Returns the original reference when the event id is not newer.
 */
export const reconcileGenerationSession = (
  current: LearningSessionWithNodes | undefined,
  incoming: LearningSessionWithNodes,
): LearningSessionWithNodes => {
  if (!current?.generation || !incoming.generation) {
    return incoming;
  }
  if (
    incoming.generation.last_event_id <
    current.generation.last_event_id
  ) {
    return current;
  }
  return incoming;
};

export function applyGenerationEvent(
  session: LearningSessionWithNodes,
  event: GenerationEvent & { generation?: GenerationJobPublic | null },
): LearningSessionWithNodes {
  const currentId = session.generation?.last_event_id ?? 0;
  if (event.id <= currentId) {
    return session;
  }

  const generationSnapshot = event.generation;
  if (!generationSnapshot) {
    return {
      ...session,
      generation: session.generation
        ? { ...session.generation, last_event_id: event.id }
        : session.generation,
    };
  }

  return {
    ...session,
    generation: {
      ...generationSnapshot,
      last_event_id: Math.max(
        generationSnapshot.last_event_id ?? 0,
        event.id,
      ),
    },
  };
}
