/**
 * ============================================================================
 * FILE: AgentModelsPanel.test.tsx
 * LOCATION: client/src/features/settings/AgentModelsPanel.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Tests Agent Models panel role labels, save wiring, and selection display.
 *
 * ROLE IN PROJECT:
 *    Guards four-role picker UI and setAgentModelSelection integration.
 *
 * KEY COMPONENTS:
 *    - AgentModelsPanel render and selection tests
 *
 * DEPENDENCIES:
 *    - External: @testing-library/react, @tanstack/react-query, vitest
 *    - Internal: AgentModelsPanel, providerSettings
 *
 * USAGE:
 *    npm run test -- --run src/features/settings/AgentModelsPanel.test.tsx
 * ============================================================================
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./ModelPicker', () => ({
  ModelPicker: ({
    activeModel,
    onSelect,
  }: {
    activeModel: string;
    onSelect: (p: string, id: string, title: string) => void;
  }) => (
    <div>
      <span data-testid="active-model">{activeModel || 'none'}</span>
      <button
        type="button"
        onClick={() => onSelect('openrouter', 'test/model', 'Test Model')}
      >
        pick-model
      </button>
    </div>
  ),
}));

vi.mock('./ThinkingModeToggle', () => ({
  ThinkingModeToggle: () => <div>thinking-toggle</div>,
}));

import { AgentModelsPanel } from './AgentModelsPanel';
import {
  getProviderSettings,
  setProviderConfig,
} from '@/lib/providerSettings';

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
    localStorage.clear();
    setProviderConfig('openrouter', {
      apiKey: 'or-key',
      model: 'main',
      modelTitle: 'Main',
    });
  });

  it('renders four role labels', () => {
    renderPanel();
    expect(screen.getByText('Researcher')).toBeInTheDocument();
    expect(screen.getByText('Planner')).toBeInTheDocument();
    expect(screen.getByText('Generator')).toBeInTheDocument();
    expect(screen.getByText('Quizzer')).toBeInTheDocument();
  });

  it('persists selection and shows it in the UI', () => {
    renderPanel();
    fireEvent.click(screen.getAllByText('pick-model')[0]);
    expect(screen.getByText('Selected:')).toBeInTheDocument();
    expect(screen.getByText('Test Model')).toBeInTheDocument();
    expect(screen.getAllByTestId('active-model')[0]).toHaveTextContent(
      'test/model',
    );
    const stored = getProviderSettings();
    expect(stored.agentModels?.researcher).toEqual(
      expect.objectContaining({
        modelId: 'test/model',
        modelTitle: 'Test Model',
        modelProvider: 'openrouter',
      }),
    );
  });
});
