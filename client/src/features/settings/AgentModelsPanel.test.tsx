/**
 * ============================================================================
 * FILE: AgentModelsPanel.test.tsx
 * LOCATION: client/src/features/settings/AgentModelsPanel.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Tests Agent Models panel role labels and save wiring.
 *
 * ROLE IN PROJECT:
 *    Guards four-role picker UI and setAgentModelSelection integration.
 *
 * KEY COMPONENTS:
 *    - AgentModelsPanel render and selection tests
 *
 * DEPENDENCIES:
 *    - External: @testing-library/react, @tanstack/react-query, vitest
 *    - Internal: AgentModelsPanel
 *
 * USAGE:
 *    npm run test -- --run src/features/settings/AgentModelsPanel.test.tsx
 * ============================================================================
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const setAgentModelSelection = vi.fn();

vi.mock('@/lib/providerSettings', () => ({
  getProviderSettings: () => ({
    activeProvider: 'openrouter',
    providers: {
      openrouter: {
        apiKey: 'or-key',
        model: 'main',
        modelTitle: 'Main',
        agentModels: {},
      },
      generalcompute: { apiKey: 'gc-key', model: '', modelTitle: '' },
    },
  }),
  setAgentModelSelection: (...args: unknown[]) =>
    setAgentModelSelection(...args),
  setProviderConfig: vi.fn(),
}));

vi.mock('./ModelPicker', () => ({
  ModelPicker: ({
    onSelect,
  }: {
    onSelect: (p: string, id: string, title: string) => void;
  }) => (
    <button
      type="button"
      onClick={() => onSelect('openrouter', 'test/model', 'Test Model')}
    >
      pick-model
    </button>
  ),
}));

vi.mock('./ThinkingModeToggle', () => ({
  ThinkingModeToggle: () => <div>thinking-toggle</div>,
}));

import { AgentModelsPanel } from './AgentModelsPanel';

function renderPanel() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <AgentModelsPanel />
    </QueryClientProvider>,
  );
}

describe('AgentModelsPanel', () => {
  beforeEach(() => {
    setAgentModelSelection.mockClear();
  });

  it('renders four role labels', () => {
    renderPanel();
    expect(screen.getByText('Researcher')).toBeInTheDocument();
    expect(screen.getByText('Planner')).toBeInTheDocument();
    expect(screen.getByText('Generator')).toBeInTheDocument();
    expect(screen.getByText('Quizzer')).toBeInTheDocument();
  });

  it('saves selection via setAgentModelSelection on active provider', () => {
    renderPanel();
    fireEvent.click(screen.getAllByText('pick-model')[0]);
    expect(setAgentModelSelection).toHaveBeenCalledWith(
      'openrouter',
      'researcher',
      expect.objectContaining({
        modelId: 'test/model',
        modelTitle: 'Test Model',
        modelProvider: 'openrouter',
      }),
    );
  });
});
