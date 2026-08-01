/**
 * ============================================================================
 * FILE: internetGroundedGeneration.test.tsx
 * LOCATION: client/src/features/learning/__tests__/internetGroundedGeneration.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Tests progressive Internet-grounded course behavior across query cache,
 *    EventSource, polling repair, sources, and retained controls.
 *
 * ROLE IN PROJECT:
 *    Provides browser acceptance coverage for Phase 6 integration.
 *
 * KEY COMPONENTS:
 *    - Progressive generation browser scenarios
 *
 * DEPENDENCIES:
 *    - External: React Query, React Router, Testing Library, Vitest
 *    - Internal: LearningPage, generation events, FakeEventSource
 *
 * USAGE:
 *    npm run test -- --run src/features/learning/__tests__/internetGroundedGeneration.test.tsx
 * ============================================================================
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { LearningPage } from '@/features/learning/LearningPage';
import { FakeEventSource } from '@/test/FakeEventSource';
import type { GenerationEvent } from '@/types/generation';
import type { LearningSessionWithNodes } from '@/types/learning';

const api = vi.hoisted(() => ({
  cancelGeneration: vi.fn(),
  deleteSession: vi.fn(),
  getCourseResearch: vi.fn(),
  getLearningSession: vi.fn(),
  resumeGeneration: vi.fn(),
  updateLastActiveNode: vi.fn().mockResolvedValue(undefined),
}));

vi.mock('@/lib/learningApi', () => api);

vi.mock('@/lib/providerSettings', () => ({
  hasWebSearchCapability: () => true,
}));

const shell = (stage: string, eventId: number): LearningSessionWithNodes => ({
  id: 'session-1',
  user_id: null,
  query: 'Modern React',
  course_title: 'Modern React',
  title_finalized: stage !== 'RESEARCHING',
  mode: 'full',
  resolved_mode: 'full',
  total_nodes: stage === 'RESEARCHING' ? 0 : 4,
  completed_nodes: 0,
  last_active_node_id: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
  nodes: [],
  generation: {
    id: 'job-1',
    session_id: 'session-1',
    stage: stage as LearningSessionWithNodes['generation'] extends infer G
      ? G extends { stage: infer S }
        ? S
        : never
      : never,
    web_search_requested: true,
    grounding_status: stage === 'COMPLETE_DEGRADED' ? 'DEGRADED' : 'PENDING',
    counts: {
      topics_total: stage === 'RESEARCHING' ? 0 : 4,
      briefs_ready: 0,
      topics_ready: 0,
      topics_failed: 0,
      research_sections: 1,
      sources: 2,
    },
    warnings: [],
    cancel_requested: false,
    can_cancel: true,
    can_resume: false,
    last_event_id: eventId,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
  },
});

const stageEvent = (
  id: number,
  stage: string,
  base: LearningSessionWithNodes,
): GenerationEvent => ({
  id,
  session_id: 'session-1',
  event_type: 'stage_changed',
  payload: {
    previous_stage: base.generation!.stage,
    stage: stage as NonNullable<LearningSessionWithNodes['generation']>['stage'],
  },
  generation: {
    ...base.generation!,
    stage: stage as NonNullable<LearningSessionWithNodes['generation']>['stage'],
    last_event_id: id,
  },
  created_at: '2026-08-01T00:00:00Z',
});

function renderPage(initial: LearningSessionWithNodes) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  queryClient.setQueryData(['learningSession', 'session-1'], initial);
  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/learn/session-1']}>
        <Routes>
          <Route path="/learn/:sessionId" element={<LearningPage />} />
          <Route path="/learn" element={<div>Course dashboard</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return queryClient;
}

describe('Internet-grounded generation browser flow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    FakeEventSource.reset();
    Object.defineProperty(globalThis, 'EventSource', {
      configurable: true,
      value: FakeEventSource,
    });
    api.getCourseResearch.mockResolvedValue({
      status: 'RESEARCHING',
      sections: [{ id: 'section-1', theme: 'Current versions', markdown: 'React 19.' }],
      sources: [],
      provider_statuses: [],
      limitations: [],
      warnings: [],
    });
  });

  it('renders research first and never regresses after a stale poll', async () => {
    const researching = shell('RESEARCHING', 4);
    const delayed = shell('RESEARCHING', 4);
    api.getLearningSession.mockImplementation(
      () => new Promise<LearningSessionWithNodes>((resolve) => {
        setTimeout(() => resolve(delayed), 25);
      }),
    );
    const client = renderPage(researching);

    expect(
      await screen.findByText(/researching current sources/i),
    ).toBeInTheDocument();
    const stream = FakeEventSource.instances[0];
    stream.emit(
      'stage_changed',
      stageEvent(5, 'OUTLINING', researching),
      '5',
    );
    await waitFor(() => {
      expect(
        client.getQueryData<LearningSessionWithNodes>([
          'learningSession',
          'session-1',
        ])?.generation?.stage,
      ).toBe('OUTLINING');
    });
    await new Promise((resolve) => setTimeout(resolve, 40));
    expect(
      client.getQueryData<LearningSessionWithNodes>([
        'learningSession',
        'session-1',
      ])?.generation?.stage,
    ).toBe('OUTLINING');
  });

  it('keeps partial artifacts on stop and resumes with fresh capability', async () => {
    const generating = shell('GENERATING_PREVIEW', 8);
    generating.nodes = [
      {
        id: 'node-1',
        learning_session_id: 'session-1',
        sequence_index: 0,
        title: 'React Actions',
        content_markdown: '# React Actions',
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
    ];
    api.getLearningSession.mockResolvedValue(generating);
    api.cancelGeneration.mockResolvedValue({
      generation: {
        ...generating.generation!,
        stage: 'CANCELLED',
        can_cancel: false,
        can_resume: true,
        last_event_id: 9,
      },
    });
    api.resumeGeneration.mockResolvedValue({
      generation: {
        ...generating.generation!,
        stage: 'GENERATING_PREVIEW',
        last_event_id: 10,
      },
    });
    const client = renderPage(generating);

    fireEvent.click(await screen.findByRole('button', { name: /stop generation/i }));
    await waitFor(() => expect(api.cancelGeneration).toHaveBeenCalledWith('session-1'));
    expect(screen.getAllByText('React Actions').length).toBeGreaterThan(0);
    expect(
      client.getQueryData<LearningSessionWithNodes>([
        'learningSession',
        'session-1',
      ])?.nodes,
    ).toHaveLength(1);
    fireEvent.click(await screen.findByRole('button', { name: /resume generation/i }));
    await waitFor(() => expect(api.resumeGeneration).toHaveBeenCalledOnce());
    expect(screen.getAllByText('React Actions').length).toBeGreaterThan(0);
  });
});
