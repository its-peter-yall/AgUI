/**
 * ============================================================================
 * FILE: generationEvents.test.ts
 * LOCATION: client/src/features/learning/generationEvents.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Tests immutable generation event cache reducer.
 *
 * ROLE IN PROJECT:
 *    Guards duplicate/out-of-order rejection and snapshot application.
 *
 * KEY COMPONENTS:
 *    - applyGenerationEvent tests
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: generationEvents, types
 *
 * USAGE:
 *    npm run test -- --run src/features/learning/generationEvents.test.ts
 * ============================================================================
 */

import { describe, expect, it } from 'vitest';

import { applyGenerationEvent } from './generationEvents';
import type { GenerationEvent } from '@/types/generation';
import type { LearningSessionWithNodes } from '@/types/learning';

const session = {
  id: 'session-1',
  nodes: [],
  generation: {
    stage: 'RESEARCHING',
    last_event_id: 4,
    counts: { research_sections: 0, sources: 0 },
  },
} as LearningSessionWithNodes;

describe('applyGenerationEvent', () => {
  it('ignores duplicate and older event IDs', () => {
    const duplicate = {
      id: 4,
      event_type: 'stage_changed',
      generation: { ...session.generation, stage: 'OUTLINING' },
    } as GenerationEvent;
    expect(applyGenerationEvent(session, duplicate)).toBe(session);
  });

  it('immutably applies newest generation snapshot', () => {
    const event = {
      id: 5,
      event_type: 'stage_changed',
      generation: {
        ...session.generation,
        stage: 'OUTLINING',
        last_event_id: 5,
      },
    } as GenerationEvent;
    const next = applyGenerationEvent(session, event);
    expect(next).not.toBe(session);
    expect(next.generation?.stage).toBe('OUTLINING');
    expect(session.generation?.stage).toBe('RESEARCHING');
  });
});
