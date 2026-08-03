/**
 * ============================================================================
 * FILE: TopicInput.test.tsx
 * LOCATION: client/src/features/learning/TopicInput.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Tests per-course search opt-in and immediate accepted-shell navigation.
 *
 * ROLE IN PROJECT:
 *    Guards hidden capability and explicit OFF-by-default course behavior.
 *
 * KEY COMPONENTS:
 *    - TopicInput web-search interaction tests
 *
 * DEPENDENCIES:
 *    - External: React Query, Testing Library, Vitest
 *    - Internal: TopicInput, learningApi, providerSettings
 *
 * USAGE:
 *    npm run test -- --run src/features/learning/TopicInput.test.tsx
 * ============================================================================
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TopicInput } from './TopicInput';

const mocks = vi.hoisted(() => ({
  generateCourse: vi.fn(),
  navigate: vi.fn(),
  capability: true,
  agentsReady: true,
}));

vi.mock('@/lib/learningApi', () => ({
  generateCourse: mocks.generateCourse,
}));

vi.mock('@/lib/providerSettings', () => ({
  getProviderSettings: () => ({
    activeProvider: 'openrouter',
    agentModels: mocks.agentsReady
      ? {
          researcher: { modelId: 'r' },
          planner: { modelId: 'p' },
          generator: { modelId: 'g' },
          quizzer: { modelId: 'q' },
        }
      : undefined,
    providers: {
      openrouter: {
        apiKey: 'llm-key',
        model: 'test/model',
        modelTitle: 'Test',
      },
      generalcompute: { apiKey: '', model: '', modelTitle: '' },
    },
  }),
  areAgentModelsConfigured: () => mocks.agentsReady,
  hasWebSearchCapability: () => mocks.capability,
}));

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>(
    'react-router-dom',
  );
  return { ...actual, useNavigate: () => mocks.navigate };
});

function renderInput() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <TopicInput />
    </QueryClientProvider>,
  );
  return client;
}

describe('TopicInput web search', () => {
  beforeEach(() => {
    mocks.generateCourse.mockReset();
    mocks.navigate.mockReset();
    mocks.capability = true;
    mocks.agentsReady = true;
  });

  it('disables Learn when agent models incomplete', () => {
    mocks.agentsReady = false;
    renderInput();
    fireEvent.change(screen.getByRole('searchbox'), {
      target: { value: 'Modern CSS' },
    });
    expect(
      screen.getByRole('button', { name: /start learning/i }),
    ).toBeDisabled();
    expect(
      screen.getByRole('alert'),
    ).toHaveTextContent(/Researcher, Planner, Generator, and Quizzer/i);
  });

  it('enables Learn when key and all four agent models set', () => {
    renderInput();
    fireEvent.change(screen.getByRole('searchbox'), {
      target: { value: 'Modern CSS' },
    });
    expect(
      screen.getByRole('button', { name: /start learning/i }),
    ).not.toBeDisabled();
  });

  it('hides search icon when capability is unavailable', () => {
    mocks.capability = false;
    renderInput();
    expect(
      screen.queryByRole('button', { name: /use web search/i }),
    ).not.toBeInTheDocument();
  });

  it('shows search icon unselected for every new input mount', () => {
    const first = renderInput();
    expect(
      screen.getByRole('button', { name: /use web search/i }),
    ).toHaveAttribute('aria-pressed', 'false');
    first.clear();
  });

  it('submits selected search state and navigates from 202 shell', async () => {
    mocks.generateCourse.mockResolvedValue({
      session: {
        id: 'session-1',
        query: 'Modern CSS',
        course_title: 'Modern CSS',
        title_finalized: false,
        nodes: [],
      },
      generation: { id: 'job-1', stage: 'INITIALIZING', last_event_id: 1 },
    });
    const client = renderInput();
    fireEvent.change(screen.getByRole('searchbox'), {
      target: { value: 'Modern CSS' },
    });
    fireEvent.click(screen.getByRole('button', { name: /use web search/i }));
    expect(
      screen.getByRole('button', { name: /use web search/i }),
    ).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: /start learning/i }));
    await waitFor(() => {
      expect(mocks.generateCourse).toHaveBeenCalledWith(
        { query: 'Modern CSS', user_id: undefined, mode: 'auto' },
        { webSearchEnabled: true },
      );
    });
    expect(
      client.getQueryData(['learningSession', 'session-1']),
    ).toMatchObject({ id: 'session-1', generation: { id: 'job-1' } });
    expect(mocks.navigate).toHaveBeenCalledWith('/learn/session-1');
  });
});
