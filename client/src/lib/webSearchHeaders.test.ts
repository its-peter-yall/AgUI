/**
 * ============================================================================
 * FILE: webSearchHeaders.test.ts
 * LOCATION: client/src/lib/webSearchHeaders.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Tests explicit web-search header construction.
 *
 * ROLE IN PROJECT:
 *    Prevents search credentials from reaching unrelated API endpoints.
 *
 * KEY COMPONENTS:
 *    - buildWebSearchHeaders tests
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: @/lib/webSearchHeaders
 *
 * USAGE:
 *    npm run test -- --run src/lib/webSearchHeaders.test.ts
 * ============================================================================
 */

import { describe, expect, it } from 'vitest';

import { WebSearchConfigurationError, buildWebSearchHeaders } from './webSearchHeaders';
import type { WebSearchSettings } from '@/types/webSearch';

const settings: WebSearchSettings = {
  masterEnabled: true,
  providers: {
    tavily: { apiKey: ' tvly-secret ', enabled: true },
    exa: { apiKey: 'exa-unused', enabled: false },
    brave: { apiKey: 'brave-secret', enabled: true },
    serpapi: { apiKey: '', enabled: false },
  },
};

describe('buildWebSearchHeaders', () => {
  it('returns only false flag when course opt-in is off', () => {
    expect(buildWebSearchHeaders(false, settings)).toEqual({
      'X-Web-Search': 'false',
    });
  });

  it('returns only selected configured provider keys in registry order', () => {
    expect(buildWebSearchHeaders(true, settings)).toEqual({
      'X-Web-Search': 'true',
      'X-Web-Search-Providers': 'tavily,brave',
      'X-Tavily-Key': 'tvly-secret',
      'X-Brave-Key': 'brave-secret',
    });
  });

  it('rejects opt-in when master or configured providers are unavailable', () => {
    expect(() =>
      buildWebSearchHeaders(true, { ...settings, masterEnabled: false }),
    ).toThrow(WebSearchConfigurationError);
    expect(() =>
      buildWebSearchHeaders(true, {
        masterEnabled: true,
        providers: {
          tavily: { apiKey: '', enabled: false },
          exa: { apiKey: '', enabled: false },
          brave: { apiKey: '', enabled: false },
          serpapi: { apiKey: '', enabled: false },
        },
      }),
    ).toThrow(WebSearchConfigurationError);
  });
});
