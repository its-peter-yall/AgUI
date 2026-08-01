/**
 * ============================================================================
 * FILE: GenerationStatusPanel.test.tsx
 * LOCATION: client/src/features/learning/GenerationStatusPanel.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Tests progressive generation status panel copy and controls.
 *
 * ROLE IN PROJECT:
 *    Guards stage labels, research counts, and stop/resume retained flow.
 *
 * KEY COMPONENTS:
 *    - GenerationStatusPanel tests
 *
 * DEPENDENCIES:
 *    - External: Testing Library, Vitest
 *    - Internal: GenerationStatusPanel
 *
 * USAGE:
 *    npm run test -- --run src/features/learning/GenerationStatusPanel.test.tsx
 * ============================================================================
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { GenerationStatusPanel } from './GenerationStatusPanel';
import type { GenerationJobPublic } from '@/types/generation';

const generation = {
  id: 'job-1',
  session_id: 'session-1',
  stage: 'RESEARCHING',
  web_search_requested: true,
  grounding_status: 'PENDING',
  counts: {
    topics_total: 0,
    briefs_ready: 0,
    topics_ready: 0,
    topics_failed: 0,
    research_sections: 2,
    sources: 7,
  },
  warnings: [],
  cancel_requested: false,
  can_cancel: true,
  can_resume: false,
  last_event_id: 3,
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
} as const satisfies GenerationJobPublic;

describe('GenerationStatusPanel', () => {
  it('renders research before an outline exists', () => {
    render(
      <GenerationStatusPanel
        generation={generation}
        onCancel={vi.fn()}
        onResume={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByText(/researching current sources/i)).toBeInTheDocument();
    expect(screen.getByText(/2 sections/i)).toBeInTheDocument();
    expect(screen.getByText(/7 sources/i)).toBeInTheDocument();
  });

  it.each([
    ['OUTLINING', 'Building table of contents'],
    ['PLANNING_PREVIEW', 'Planning first 3 topics'],
    ['GENERATING_PREVIEW', 'Generating preview topics'],
    ['PLANNING_BATCH', 'Planning next topic batch'],
    ['GENERATING_BATCH', 'Generating next topic batch'],
    ['COMPLETE', 'Course generation complete'],
  ] as const)('maps %s to visible stage copy', (stage, copy) => {
    render(
      <GenerationStatusPanel
        generation={{ ...generation, stage }}
        onCancel={vi.fn()}
        onResume={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByText(new RegExp(copy, 'i'))).toBeInTheDocument();
  });

  it('shows Stop while running and Resume after retained cancellation', () => {
    const cancel = vi.fn();
    const resume = vi.fn();
    const { rerender } = render(
      <GenerationStatusPanel
        generation={generation}
        onCancel={cancel}
        onResume={resume}
        onDelete={vi.fn()}
      />,
    );
    screen.getByRole('button', { name: /stop generation/i }).click();
    expect(cancel).toHaveBeenCalledOnce();
    rerender(
      <GenerationStatusPanel
        generation={{
          ...generation,
          stage: 'CANCELLED',
          can_cancel: false,
          can_resume: true,
        }}
        onCancel={cancel}
        onResume={resume}
        onDelete={vi.fn()}
      />,
    );
    screen.getByRole('button', { name: /resume generation/i }).click();
    expect(resume).toHaveBeenCalledOnce();
    expect(screen.getByText(/partial course retained/i)).toBeInTheDocument();
  });

  it('shows degraded and failed stages with warnings and busy controls', () => {
    const del = vi.fn();
    render(
      <GenerationStatusPanel
        generation={{
          ...generation,
          stage: 'COMPLETE_DEGRADED',
          grounding_status: 'DEGRADED',
          can_cancel: false,
          can_resume: false,
          warnings: [
            {
              code: 'research_unavailable',
              message: 'Web research unavailable',
              provider_id: null,
            },
          ],
          counts: {
            ...generation.counts,
            topics_total: 10,
            topics_ready: 8,
            topics_failed: 2,
          },
        }}
        onCancel={vi.fn()}
        onResume={vi.fn()}
        onDelete={del}
        isCancelling
        isResuming
        isDeleting
      />,
    );
    expect(
      screen.getByText(/course complete with research warning/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/web research unavailable/i)).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /delete course permanently/i }),
    ).toBeDisabled();
  });

  it('maps paused and failed stages', () => {
    const { rerender } = render(
      <GenerationStatusPanel
        generation={{
          ...generation,
          stage: 'PAUSED',
          can_resume: true,
          can_cancel: false,
        }}
        onCancel={vi.fn()}
        onResume={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByText(/generation paused/i)).toBeInTheDocument();
    rerender(
      <GenerationStatusPanel
        generation={{
          ...generation,
          stage: 'FAILED',
          can_cancel: false,
          can_resume: false,
        }}
        onCancel={vi.fn()}
        onResume={vi.fn()}
        onDelete={vi.fn()}
      />,
    );
    expect(screen.getByText(/course generation failed/i)).toBeInTheDocument();
  });
});
