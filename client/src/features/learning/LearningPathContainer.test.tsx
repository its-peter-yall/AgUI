/**
 * ============================================================================
 * FILE: LearningPathContainer.test.tsx
 * LOCATION: client/src/features/learning/LearningPathContainer.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Tests progressive module rendering in the learning path container.
 *
 * ROLE IN PROJECT:
 *    Guards empty-shell stage view, skeleton modules, and READY cards.
 *
 * KEY COMPONENTS:
 *    - LearningPathContainer progressive tests
 *
 * DEPENDENCIES:
 *    - External: React Query, Testing Library, Vitest
 *    - Internal: LearningPathContainer
 *
 * USAGE:
 *    npm run test -- --run src/features/learning/LearningPathContainer.test.tsx
 * ============================================================================
 */

import type { ReactNode, ComponentPropsWithoutRef } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { LearningPathContainer } from './LearningPathContainer';
import type { LearningSessionWithNodes } from '@/types/learning';

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, ...props }: ComponentPropsWithoutRef<'div'>) => (
      <div {...props}>{children}</div>
    ),
  },
  AnimatePresence: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

vi.mock('./ConceptCard', () => ({
  ConceptCard: ({ node }: { node: { title: string } }) => (
    <div data-testid="concept-card">{node.title}</div>
  ),
}));

vi.mock('./ChatPanel', () => ({
  ChatPanel: () => null,
}));

vi.mock('./useLearningMutations', () => ({
  useLearningMutations: () => ({
    proceedToQuiz: vi.fn(),
    submitAnswer: vi.fn(),
    retry: vi.fn(),
    continueToNext: vi.fn(),
    regenerate: vi.fn(),
    advanceToNextQuiz: vi.fn(),
    goToPreviousQuiz: vi.fn(),
    isAnyLoading: false,
    isRegenerating: false,
    isTransitioning: false,
  }),
}));

vi.mock('@/lib/learningApi', () => ({
  generateCourse: vi.fn(),
  getLearningSession: vi.fn(),
  updateLastActiveNode: vi.fn().mockResolvedValue(undefined),
}));

const generation = {
  id: 'job-1',
  session_id: 'session-1',
  stage: 'GENERATING_PREVIEW' as const,
  web_search_requested: false,
  grounding_status: 'DISABLED' as const,
  counts: {
    topics_total: 2,
    briefs_ready: 2,
    topics_ready: 0,
    topics_failed: 0,
    research_sections: 0,
    sources: 0,
  },
  warnings: [],
  cancel_requested: false,
  can_cancel: true,
  can_resume: false,
  last_event_id: 2,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
};

function wrap(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
}

describe('LearningPathContainer progressive', () => {
  it('renders status rather than No topics yet for empty nonterminal shell', () => {
    const session = {
      id: 'session-1',
      user_id: null,
      query: 'CSS',
      course_title: 'CSS',
      total_nodes: 0,
      completed_nodes: 0,
      last_active_node_id: null,
      created_at: '2026-08-01T00:00:00Z',
      updated_at: null,
      nodes: [],
      generation,
    } as LearningSessionWithNodes;

    wrap(
      <LearningPathContainer sessionId="session-1" session={session} />,
    );
    expect(screen.getByText(/preparing your course outline/i)).toBeInTheDocument();
    expect(screen.queryByText(/no topics yet/i)).not.toBeInTheDocument();
  });

  it('renders titled skeletons for SKELETON and GENERATING modules', () => {
    const session = {
      id: 'session-1',
      user_id: null,
      query: 'CSS',
      course_title: 'CSS',
      total_nodes: 2,
      completed_nodes: 0,
      last_active_node_id: null,
      created_at: '2026-08-01T00:00:00Z',
      updated_at: null,
      generation,
      nodes: [
        {
          id: 'n1',
          learning_session_id: 'session-1',
          sequence_index: 0,
          title: 'Selectors',
          content_markdown: '',
          status: 'LOCKED',
          error_message: null,
          retry_available: false,
          module_status: 'GENERATING',
          quiz: null,
          quiz_set: null,
          quiz_hidden: null,
          quiz_set_hidden: null,
          created_at: '2026-08-01T00:00:00Z',
          updated_at: null,
        },
        {
          id: 'n2',
          learning_session_id: 'session-1',
          sequence_index: 1,
          title: 'Cascade',
          content_markdown: '',
          status: 'LOCKED',
          error_message: null,
          retry_available: false,
          module_status: 'SKELETON',
          quiz: null,
          quiz_set: null,
          quiz_hidden: null,
          quiz_set_hidden: null,
          created_at: '2026-08-01T00:00:00Z',
          updated_at: null,
        },
      ],
    } as LearningSessionWithNodes;

    wrap(
      <LearningPathContainer sessionId="session-1" session={session} />,
    );
    expect(screen.getByText('Selectors')).toBeInTheDocument();
    expect(screen.queryByTestId('concept-card')).not.toBeInTheDocument();
  });

  it('renders ConceptCard for READY modules', () => {
    const session = {
      id: 'session-1',
      user_id: null,
      query: 'CSS',
      course_title: 'CSS',
      total_nodes: 1,
      completed_nodes: 0,
      last_active_node_id: null,
      created_at: '2026-08-01T00:00:00Z',
      updated_at: null,
      generation: { ...generation, stage: 'COMPLETE' as const, can_cancel: false },
      nodes: [
        {
          id: 'n1',
          learning_session_id: 'session-1',
          sequence_index: 0,
          title: 'Ready Topic',
          content_markdown: 'Hello',
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
    } as LearningSessionWithNodes;

    wrap(
      <LearningPathContainer sessionId="session-1" session={session} />,
    );
    expect(screen.getByTestId('concept-card')).toHaveTextContent('Ready Topic');
  });
});
