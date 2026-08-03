/**
 * ============================================================================
 * FILE: LearningPage.test.tsx
 * LOCATION: client/src/features/learning/LearningPage.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Tests LearningPage retained cancel/resume/delete controls.
 *
 * ROLE IN PROJECT:
 *    Guards generation merge, resume capability gate, and delete cleanup.
 *
 * KEY COMPONENTS:
 *    - LearningPage control tests
 *
 * DEPENDENCIES:
 *    - External: React Query, Testing Library, Vitest
 *    - Internal: LearningPage, learningApi
 *
 * USAGE:
 *    npm run test -- --run src/features/learning/LearningPage.test.tsx
 * ============================================================================
 */

import type { ReactNode, ComponentPropsWithoutRef } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { LearningPage } from './LearningPage';
import type { LearningSessionWithNodes } from '@/types/learning';

const api = vi.hoisted(() => ({
  getLearningSession: vi.fn(),
  cancelGeneration: vi.fn(),
  resumeGeneration: vi.fn(),
  deleteSession: vi.fn(),
  getCourseResearch: vi.fn(),
  hasWebSearchCapability: vi.fn(() => true),
  navigate: vi.fn(),
}));

vi.mock('@/lib/learningApi', () => ({
  getLearningSession: api.getLearningSession,
  cancelGeneration: api.cancelGeneration,
  resumeGeneration: api.resumeGeneration,
  deleteSession: api.deleteSession,
  getCourseResearch: api.getCourseResearch,
}));

vi.mock('@/lib/providerSettings', () => ({
  hasWebSearchCapability: () => api.hasWebSearchCapability(),
  getProviderSettings: () => ({
    activeProvider: 'openrouter',
    providers: {
      openrouter: {
        apiKey: 'k',
        model: 'm',
        modelTitle: 'M',
        agentModels: {
          researcher: { modelId: 'r' },
          planner: { modelId: 'p' },
          generator: { modelId: 'g' },
          quizzer: { modelId: 'q' },
        },
      },
      generalcompute: { apiKey: '', model: '', modelTitle: '' },
    },
  }),
  areAgentModelsConfigured: () => true,
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return {
    ...actual,
    useNavigate: () => api.navigate,
  };
});

vi.mock('./LearningPathContainer', () => ({
  LearningPathContainer: () => <div data-testid="path-container" />,
}));

vi.mock('./useSessionEvents', () => ({
  useSessionEvents: vi.fn(),
  isTerminalGenerationStage: (stage?: string) =>
    !stage ||
    ['COMPLETE', 'COMPLETE_DEGRADED', 'CANCELLED', 'FAILED'].includes(stage),
}));

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, ...props }: ComponentPropsWithoutRef<'div'>) => (
      <div {...props}>{children}</div>
    ),
  },
  AnimatePresence: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

const runningSession: LearningSessionWithNodes = {
  id: 'session-1',
  user_id: null,
  query: 'CSS',
  course_title: 'CSS',
  total_nodes: 1,
  completed_nodes: 0,
  last_active_node_id: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: null,
  nodes: [
    {
      id: 'n1',
      learning_session_id: 'session-1',
      sequence_index: 0,
      title: 'Topic',
      content_markdown: 'Body',
      status: 'VIEWING_EXPLANATION',
      error_message: null,
      retry_available: false,
      module_status: 'READY',
      quiz: null,
      quiz_set: null,
      quiz_hidden: null,
      quiz_set_hidden: null,
      created_at: '2026-08-01T00:00:00Z',
      updated_at: null,
    },
  ],
  generation: {
    id: 'job-1',
    session_id: 'session-1',
    stage: 'GENERATING_BATCH',
    web_search_requested: true,
    grounding_status: 'PENDING',
    counts: {
      topics_total: 3,
      briefs_ready: 1,
      topics_ready: 1,
      topics_failed: 0,
      research_sections: 1,
      sources: 2,
    },
    warnings: [],
    cancel_requested: false,
    can_cancel: true,
    can_resume: false,
    last_event_id: 4,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
  },
};

function renderPage(session = runningSession) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  client.setQueryData(['learningSession', 'session-1'], session);
  api.getLearningSession.mockResolvedValue(session);
  api.getCourseResearch.mockResolvedValue({
    id: 'r1',
    session_id: 'session-1',
    status: 'RESEARCHING',
    summary: null,
    limitations: [],
    freshness_note: null,
    sections: [],
    sources: [],
    provider_statuses: [],
    warnings: [],
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
  });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/learn/session-1']}>
        <Routes>
          <Route path="/learn/:sessionId" element={<LearningPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

describe('LearningPage controls', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.hasWebSearchCapability.mockReturnValue(true);
    window.confirm = vi.fn(() => true);
  });

  it('cancel updates generation only and retains nodes', async () => {
    api.cancelGeneration.mockResolvedValue({
      generation: {
        ...runningSession.generation!,
        stage: 'CANCELLED',
        can_cancel: false,
        can_resume: true,
      },
    });
    const client = renderPage();
    await screen.findByRole('button', { name: /stop generation/i });
    fireEvent.click(screen.getByRole('button', { name: /stop generation/i }));
    await waitFor(() => {
      expect(api.cancelGeneration).toHaveBeenCalledWith('session-1');
    });
    await waitFor(() => {
      const data = client.getQueryData<LearningSessionWithNodes>([
        'learningSession',
        'session-1',
      ]);
      expect(data?.generation?.stage).toBe('CANCELLED');
      expect(data?.nodes).toHaveLength(1);
      expect(data?.nodes[0].title).toBe('Topic');
    });
  });

  it('resume sends webSearchEnabled when research unfinished and capability exists', async () => {
    const cancelled = {
      ...runningSession,
      generation: {
        ...runningSession.generation!,
        stage: 'CANCELLED' as const,
        can_cancel: false,
        can_resume: true,
        grounding_status: 'PENDING' as const,
        web_search_requested: true,
      },
    };
    api.resumeGeneration.mockResolvedValue({
      generation: {
        ...cancelled.generation!,
        stage: 'RESEARCHING',
        can_cancel: true,
        can_resume: false,
      },
    });
    renderPage(cancelled);
    fireEvent.click(
      await screen.findByRole('button', { name: /resume generation/i }),
    );
    await waitFor(() => {
      expect(api.resumeGeneration).toHaveBeenCalledWith('session-1', {
        webSearchEnabled: true,
      });
    });
  });

  it('shows actionable error when resume needs search but capability missing', async () => {
    api.hasWebSearchCapability.mockReturnValue(false);
    const cancelled = {
      ...runningSession,
      generation: {
        ...runningSession.generation!,
        stage: 'CANCELLED' as const,
        can_cancel: false,
        can_resume: true,
        grounding_status: 'PENDING' as const,
        web_search_requested: true,
      },
    };
    renderPage(cancelled);
    fireEvent.click(
      await screen.findByRole('button', { name: /resume generation/i }),
    );
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/web search capability/i);
    });
    expect(api.resumeGeneration).not.toHaveBeenCalled();
  });

  it('delete confirms, clears cache, and navigates dashboard', async () => {
    api.deleteSession.mockResolvedValue(undefined);
    const client = renderPage();
    const removeSpy = vi.spyOn(client, 'removeQueries');
    fireEvent.click(
      await screen.findByRole('button', { name: /delete course permanently/i }),
    );
    await waitFor(() => {
      expect(api.deleteSession).toHaveBeenCalledWith('session-1');
      expect(api.navigate).toHaveBeenCalledWith('/learn');
    });
    expect(removeSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        queryKey: ['learningSession', 'session-1'],
      }),
    );
  });
});
