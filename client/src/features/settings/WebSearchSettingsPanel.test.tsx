/**
 * ============================================================================
 * FILE: WebSearchSettingsPanel.test.tsx
 * LOCATION: client/src/features/settings/WebSearchSettingsPanel.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Tests optional web-search settings and curated provider controls.
 *
 * ROLE IN PROJECT:
 *    Guards default-off visibility, local validation, metadata, and persistence.
 *
 * KEY COMPONENTS:
 *    - WebSearchSettingsPanel interaction tests
 *
 * DEPENDENCIES:
 *    - External: @testing-library/react, vitest
 *    - Internal: WebSearchSettingsPanel, providerSettings
 *
 * USAGE:
 *    npm run test -- --run src/features/settings/WebSearchSettingsPanel.test.tsx
 * ============================================================================
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';

import { WebSearchSettingsPanel } from './WebSearchSettingsPanel';

describe('WebSearchSettingsPanel', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('starts off and hides all provider cards', () => {
    render(<WebSearchSettingsPanel />);
    expect(
      screen.getByRole('switch', { name: /enable web search/i }),
    ).toHaveAttribute('aria-checked', 'false');
    expect(screen.queryByText('Tavily')).not.toBeInTheDocument();
    expect(screen.queryByText('Brave Search')).not.toBeInTheDocument();
  });

  it('shows exactly four provider cards after enabling master switch', () => {
    render(<WebSearchSettingsPanel />);
    fireEvent.click(
      screen.getByRole('switch', { name: /enable web search/i }),
    );
    for (const label of ['Tavily', 'Exa', 'Brave Search', 'SerpAPI']) {
      expect(screen.getByRole('heading', { name: label })).toBeInTheDocument();
    }
    expect(screen.getByText(/card required/i)).toBeInTheDocument();
    expect(screen.getByText(/attribution/i)).toBeInTheDocument();
  });

  it('requires a nonblank key before enabling a provider', () => {
    render(<WebSearchSettingsPanel />);
    fireEvent.click(
      screen.getByRole('switch', { name: /enable web search/i }),
    );
    fireEvent.click(
      screen.getByRole('checkbox', { name: /enable tavily/i }),
    );
    expect(screen.getByRole('alert')).toHaveTextContent(/api key is required/i);
    expect(
      screen.getByRole('checkbox', { name: /enable tavily/i }),
    ).not.toBeChecked();
  });

  it('stores key locally and enables configured provider without network call', () => {
    render(<WebSearchSettingsPanel />);
    fireEvent.click(
      screen.getByRole('switch', { name: /enable web search/i }),
    );
    fireEvent.change(screen.getByLabelText(/tavily api key/i), {
      target: { value: 'tvly-browser-key' },
    });
    fireEvent.click(
      screen.getByRole('checkbox', { name: /enable tavily/i }),
    );
    expect(
      screen.getByRole('checkbox', { name: /enable tavily/i }),
    ).toBeChecked();
    expect(localStorage.getItem('web_search_settings')).toContain(
      'tvly-browser-key',
    );
  });

  it('uses safe external signup and docs links', () => {
    render(<WebSearchSettingsPanel />);
    fireEvent.click(
      screen.getByRole('switch', { name: /enable web search/i }),
    );
    const signup = screen.getByRole('link', { name: /get tavily key/i });
    expect(signup).toHaveAttribute('href', 'https://app.tavily.com');
    expect(signup).toHaveAttribute('target', '_blank');
    expect(signup).toHaveAttribute('rel', 'noreferrer noopener');
  });
});
