/**
 * ============================================================================
 * FILE: CourseSourcesPanel.test.tsx
 * LOCATION: client/src/features/learning/CourseSourcesPanel.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Tests Course Sources panel for partial, degraded, and complete reports.
 *
 * ROLE IN PROJECT:
 *    Guards section/source counts, Brave attribution, and close accessibility.
 *
 * KEY COMPONENTS:
 *    - CourseSourcesPanel tests
 *
 * DEPENDENCIES:
 *    - External: Testing Library, Vitest
 *    - Internal: CourseSourcesPanel
 *
 * USAGE:
 *    npm run test -- --run src/features/learning/CourseSourcesPanel.test.tsx
 * ============================================================================
 */

import type { ReactNode, ComponentPropsWithoutRef } from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CourseSourcesPanel } from './CourseSourcesPanel';
import type { ResearchReport } from '@/types/generation';

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, ...props }: ComponentPropsWithoutRef<'div'>) => (
      <div {...props}>{children}</div>
    ),
  },
  AnimatePresence: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

vi.mock('./MarkdownRenderer', () => ({
  MarkdownRenderer: ({ content }: { content: string }) => (
    <div data-testid="md">{content}</div>
  ),
}));

const baseReport: ResearchReport = {
  id: 'report-1',
  session_id: 'session-1',
  status: 'RESEARCHING',
  summary: null,
  limitations: [],
  freshness_note: null,
  sections: [
    {
      id: 'sec-1',
      sequence_index: 0,
      theme: 'Fundamentals',
      markdown: 'Section body',
      source_ids: ['source-1'],
      created_at: '2026-08-01T00:00:00Z',
      updated_at: '2026-08-01T00:00:00Z',
    },
  ],
  sources: [
    {
      id: 'source-1',
      title: 'MDN CSS',
      url: 'https://developer.mozilla.org/css',
      publisher: 'MDN',
      published_at: '2026-01-01T00:00:00Z',
      retrieved_at: '2026-08-01T00:00:00Z',
      provider_id: 'tavily',
      snippet: 'CSS basics',
      excerpt: 'Cascading Style Sheets',
      relevance_score: 0.9,
    },
  ],
  provider_statuses: [
    {
      provider_id: 'tavily',
      state: 'USED',
      search_calls: 2,
      result_count: 5,
      error_class: null,
    },
  ],
  warnings: [],
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:00:00Z',
};

describe('CourseSourcesPanel', () => {
  it('renders partial researching report with section and source counts', () => {
    render(
      <CourseSourcesPanel
        isOpen
        onClose={vi.fn()}
        report={baseReport}
      />,
    );
    expect(screen.getByText(/1 sources/i)).toBeInTheDocument();
    expect(screen.getByText(/1 sections/i)).toBeInTheDocument();
    expect(screen.getByText('Fundamentals')).toBeInTheDocument();
    expect(screen.getByText(/tavily: USED/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /close course sources/i })).toBeInTheDocument();
  });

  it('shows degraded limitations without grounded claim and Brave attribution', () => {
    render(
      <CourseSourcesPanel
        isOpen
        onClose={vi.fn()}
        report={{
          ...baseReport,
          status: 'DEGRADED',
          limitations: ['Quota exhausted on all providers'],
          warnings: [
            {
              code: 'ALL_PROVIDERS_FAILED',
              message: 'All search providers failed',
              provider_id: null,
            },
          ],
          sources: [
            {
              ...baseReport.sources[0],
              provider_id: 'brave',
            },
          ],
        }}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent(/not fully web-grounded/i);
    expect(screen.getByText(/Quota exhausted/i)).toBeInTheDocument();
    expect(screen.getByText(/Powered by Brave/i)).toBeInTheDocument();
  });

  it('shows retrieved and published metadata on complete report', () => {
    render(
      <CourseSourcesPanel
        isOpen
        onClose={vi.fn()}
        report={{ ...baseReport, status: 'COMPLETE' }}
      />,
    );
    expect(screen.getByText(/Published 2026-01-01/i)).toBeInTheDocument();
    expect(screen.getByText(/Retrieved 2026-08-01/i)).toBeInTheDocument();
    expect(screen.getByText(/Cascading Style Sheets/i)).toBeInTheDocument();
  });
});
