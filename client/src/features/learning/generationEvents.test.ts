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

import {
  applyGenerationEvent,
  reconcileGenerationSession,
} from './generationEvents';
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

  it('bumps last_event_id when generation snapshot is absent', () => {
    const event = {
      id: 9,
      event_type: 'stage_changed',
    } as GenerationEvent;
    const next = applyGenerationEvent(session, event);
    expect(next.generation?.last_event_id).toBe(9);
    expect(next.generation?.stage).toBe('RESEARCHING');
  });

  it('returns session unchanged when generation missing on event without snapshot', () => {
    const bare = { ...session, generation: null } as LearningSessionWithNodes;
    const event = {
      id: 1,
      event_type: 'stage_changed',
    } as GenerationEvent;
    expect(applyGenerationEvent(bare, event)).toEqual(bare);
  });
});

describe('reconcileGenerationSession', () => {
  it('keeps newer SSE state when a delayed poll returns an older event ID', () => {
    const current = {
      ...session,
      generation: {
        ...session.generation,
        stage: 'OUTLINING',
        last_event_id: 8,
      },
    } as LearningSessionWithNodes;
    const delayedPoll = {
      ...current,
      generation: {
        ...current.generation,
        stage: 'RESEARCHING',
        last_event_id: 7,
      },
    } as LearningSessionWithNodes;

    expect(reconcileGenerationSession(current, delayedPoll)).toBe(current);
  });

  it('returns incoming when current generation is missing', () => {
    const incoming = {
      ...session,
      generation: { ...session.generation, last_event_id: 1 },
    } as LearningSessionWithNodes;
    expect(reconcileGenerationSession(undefined, incoming)).toBe(incoming);
    expect(
      reconcileGenerationSession(
        { ...session, generation: null } as LearningSessionWithNodes,
        incoming,
      ),
    ).toBe(incoming);
  });

  it('accepts a poll snapshot at the same or newer event ID', () => {
    const current = {
      ...session,
      generation: { ...session.generation, last_event_id: 8 },
    } as LearningSessionWithNodes;
    const repaired = {
      ...current,
      nodes: [
        {
          id: 'node-1',
          learning_session_id: 'session-1',
          sequence_index: 0,
          title: 'Ready topic',
          content_markdown: '# Ready topic',
          status: 'VIEWING_EXPLANATION',
          error_message: null,
          retry_available: false,
          complexity: 'Basic',
          total_quizzes: 1,
          quiz: null,
          quiz_set: null,
          quiz_hidden: null,
          quiz_set_hidden: null,
          created_at: '2026-08-01T00:00:00Z',
          updated_at: '2026-08-01T00:00:00Z',
          module_status: 'READY',
          citations: [],
        },
      ],
      generation: {
        ...current.generation,
        stage: 'GENERATING_PREVIEW',
        last_event_id: 9,
      },
    } as LearningSessionWithNodes;

    expect(reconcileGenerationSession(current, repaired)).toBe(repaired);
  });
});
