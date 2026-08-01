/**
 * ============================================================================
 * FILE: CourseCard.test.tsx
 * LOCATION: client/src/features/learning/CourseCard.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Tests dashboard generation status badges on course cards.
 *
 * ROLE IN PROJECT:
 *    Guards generating/paused/cancelled/degraded badge rendering.
 *
 * KEY COMPONENTS:
 *    - CourseCard badge tests
 *
 * DEPENDENCIES:
 *    - External: Testing Library, Vitest
 *    - Internal: CourseCard
 *
 * USAGE:
 *    npm run test -- --run src/features/learning/CourseCard.test.tsx
 * ============================================================================
 */

import type { ReactNode, ComponentPropsWithoutRef } from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CourseCard } from './CourseCard';
import type { LearningSessionSummary } from '@/types/learning';
import type { GenerationJobPublic } from '@/types/generation';

vi.mock('framer-motion', () => ({
  motion: {
    article: ({ children, ...props }: ComponentPropsWithoutRef<'article'>) => (
      <article {...props}>{children}</article>
    ),
  },
  AnimatePresence: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

const baseSession: LearningSessionSummary = {
  id: 's1',
  query: 'CSS',
  course_title: 'Modern CSS',
  status: 'in_progress',
  progress_percent: 10,
  total_nodes: 5,
  completed_nodes: 0,
  last_active_node_title: null,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
  completed_at: null,
  revision_count: 0,
};

function gen(stage: GenerationJobPublic['stage']): GenerationJobPublic {
  return {
    id: 'job-1',
    session_id: 's1',
    stage,
    web_search_requested: true,
    grounding_status: stage === 'COMPLETE_DEGRADED' ? 'DEGRADED' : 'PENDING',
    counts: {
      topics_total: 5,
      briefs_ready: 1,
      topics_ready: 1,
      topics_failed: 0,
      research_sections: 1,
      sources: 2,
    },
    warnings: [],
    cancel_requested: false,
    can_cancel: false,
    can_resume: stage === 'CANCELLED' || stage === 'PAUSED',
    last_event_id: 1,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
  };
}

describe('CourseCard generation badges', () => {
  it.each([
    ['GENERATING_PREVIEW', /generating/i],
    ['PAUSED', /paused/i],
    ['CANCELLED', /cancelled/i],
    ['COMPLETE_DEGRADED', /research warning/i],
  ] as const)('shows badge for %s', (stage, label) => {
    render(
      <CourseCard
        session={{ ...baseSession, generation: gen(stage) }}
        onResume={vi.fn()}
        onRevise={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByTestId('generation-badge')).toHaveTextContent(label);
  });
});
