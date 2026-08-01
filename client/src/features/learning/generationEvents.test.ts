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
  user_id: null,
  query: 'q',
  course_title: 'q',
  total_nodes: 0,
  completed_nodes: 0,
  last_active_node_id: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: null,
  nodes: [],
  generation: {
    id: 'job-1',
    session_id: 'session-1',
    stage: 'RESEARCHING',
    web_search_requested: true,
    grounding_status: 'PENDING',
    last_event_id: 4,
    counts: {
      topics_total: 0,
      briefs_ready: 0,
      topics_ready: 0,
      topics_failed: 0,
      research_sections: 0,
      sources: 0,
    },
    warnings: [],
    cancel_requested: false,
    can_cancel: true,
    can_resume: false,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
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
