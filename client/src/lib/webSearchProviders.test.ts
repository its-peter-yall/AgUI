/**
 * ============================================================================
 * FILE: webSearchProviders.test.ts
 * LOCATION: client/src/lib/webSearchProviders.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Verifies curated client search provider metadata.
 *
 * ROLE IN PROJECT:
 *    Prevents provider drift between Settings, headers, and server contracts.
 *
 * KEY COMPONENTS:
 *    - WEB_SEARCH_PROVIDER_IDS contract tests
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: @/lib/webSearchProviders
 *
 * USAGE:
 *    npm run test -- --run src/lib/webSearchProviders.test.ts
 * ============================================================================
 */

import { describe, expect, it } from 'vitest';

import {
  WEB_SEARCH_PROVIDER_IDS,
  WEB_SEARCH_PROVIDERS,
} from '@/lib/webSearchProviders';

describe('WEB_SEARCH_PROVIDERS', () => {
  it('contains exactly four locked providers in display order', () => {
    expect(WEB_SEARCH_PROVIDER_IDS).toEqual([
      'tavily',
      'exa',
      'brave',
      'serpapi',
    ]);
  });

  it('contains complete current-year metadata and header names', () => {
    expect(WEB_SEARCH_PROVIDERS.tavily.recommended).toBe(true);
    expect(WEB_SEARCH_PROVIDERS.brave.requiresPaymentMethod).toBe(true);
    expect(WEB_SEARCH_PROVIDERS.brave.attributionRequired).toBe(true);
    expect(WEB_SEARCH_PROVIDERS.serpapi.keyHeader).toBe('X-SerpApi-Key');

    for (const providerId of WEB_SEARCH_PROVIDER_IDS) {
      const provider = WEB_SEARCH_PROVIDERS[providerId];
      expect(provider.id).toBe(providerId);
      expect(provider.freeTierSummary.length).toBeGreaterThan(10);
      expect(provider.signupUrl).toMatch(/^https:\/\//);
      expect(provider.docsUrl).toMatch(/^https:\/\//);
      expect(provider.verifiedAt).toBe('2026-08-01');
    }
  });
});
