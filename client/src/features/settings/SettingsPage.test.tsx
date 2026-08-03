/**
 * ============================================================================
 * FILE: SettingsPage.test.tsx
 * LOCATION: client/src/features/settings/SettingsPage.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Tests top-level settings section disclosure behavior.
 *
 * ROLE IN PROJECT:
 *    Guards collapsed defaults and accessible section toggles without coupling
 *    these tests to individual settings panel implementations.
 *
 * KEY COMPONENTS:
 *    - SettingsPage disclosure interaction tests
 *
 * DEPENDENCIES:
 *    - External: @testing-library/react, react-router-dom, vitest
 *    - Internal: SettingsPage
 *
 * USAGE:
 *    npm run test -- --run src/features/settings/SettingsPage.test.tsx
 * ============================================================================
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';

import { SettingsPage } from './SettingsPage';

vi.mock('./OpenRouterSettingsPanel', () => ({
  OpenRouterSettingsPanel: () => <div>OpenRouter panel content</div>,
}));

vi.mock('./WebSearchSettingsPanel', () => ({
  WebSearchSettingsPanel: () => <div>Web search panel content</div>,
}));

vi.mock('./AgentModelsPanel', () => ({
  AgentModelsPanel: () => <div>Agent models panel content</div>,
}));

vi.mock('./ModelPicker', () => ({
  ModelPicker: () => <div>Model picker content</div>,
}));

vi.mock('./ThinkingModeToggle', () => ({
  ThinkingModeToggle: () => <div>chat-thinking-toggle</div>,
}));

vi.mock('./StorageSettingsPanel', () => ({
  StorageSettingsPanel: () => (
    <div data-testid="storage-settings-panel">Storage panel content</div>
  ),
}));

function renderSettingsPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('SettingsPage', () => {
  it('starts with every top-level section collapsed', () => {
    renderSettingsPage();

    for (const name of [
      'Appearance',
      /Data Storage/,
      'AI Provider Credentials',
      'Web Search',
      'Agent Models',
      'Chat Assistant Model',
    ]) {
      expect(screen.getByRole('button', { name })).toHaveAttribute(
        'aria-expanded',
        'false',
      );
    }

    expect(screen.queryByText('OpenRouter panel content')).not.toBeInTheDocument();
    expect(screen.queryByText('Web search panel content')).not.toBeInTheDocument();
    expect(screen.queryByText('Model picker content')).not.toBeInTheDocument();
    expect(
      screen.queryByTestId('storage-settings-panel'),
    ).not.toBeInTheDocument();
  });

  it('expands Data Storage section and renders panel', async () => {
    renderSettingsPage();

    expect(screen.getByRole('button', { name: /Data Storage/ })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    fireEvent.click(screen.getByRole('button', { name: /Data Storage/ }));
    expect(screen.getByRole('button', { name: /Data Storage/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(screen.getByTestId('storage-settings-panel')).toBeInTheDocument();
  });

  it('expands and collapses only the section that was selected', () => {
    renderSettingsPage();

    const webSearchButton = screen.getByRole('button', { name: 'Web Search' });

    fireEvent.click(webSearchButton);

    expect(webSearchButton).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(screen.getByText('Web search panel content')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Appearance' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );

    fireEvent.click(webSearchButton);

    expect(webSearchButton).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Web search panel content')).not.toBeInTheDocument();
  });
});
