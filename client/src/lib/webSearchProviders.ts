/**
 * ============================================================================
 * FILE: webSearchProviders.ts
 * LOCATION: client/src/lib/webSearchProviders.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Curated metadata for Tavily, Exa, Brave, and SerpAPI search providers.
 *
 * ROLE IN PROJECT:
 *    Supplies display copy, signup/docs links, and request header names for
 *    Settings and future search request construction.
 *
 * KEY COMPONENTS:
 *    - WEB_SEARCH_PROVIDER_IDS: Readonly tuple of the four locked IDs
 *    - WEB_SEARCH_PROVIDERS: Typed record of provider metadata
 *
 * DEPENDENCIES:
 *    - External: None
 *    - Internal: @/types/webSearch
 *
 * USAGE:
 *    import { WEB_SEARCH_PROVIDERS } from '@/lib/webSearchProviders';
 * ============================================================================
 */

import type {
  WebSearchProviderId,
  WebSearchProviderMetadata,
} from '@/types/webSearch';

export const WEB_SEARCH_PROVIDER_IDS = [
  'tavily',
  'exa',
  'brave',
  'serpapi',
] as const satisfies readonly WebSearchProviderId[];

export const WEB_SEARCH_PROVIDERS: Record<
  WebSearchProviderId,
  WebSearchProviderMetadata
> = {
  tavily: {
    id: 'tavily',
    displayName: 'Tavily',
    freeTierSummary:
      '1,000 API credits each month; no card required.',
    signupUrl: 'https://app.tavily.com',
    docsUrl:
      'https://docs.tavily.com/documentation/api-reference/endpoint/search',
    keyHeader: 'X-Tavily-Key',
    keyPlaceholder: 'tvly-...',
    requiresPaymentMethod: false,
    attributionRequired: false,
    recommended: true,
    verifiedAt: '2026-08-01',
  },
  exa: {
    id: 'exa',
    displayName: 'Exa',
    freeTierSummary:
      '$10 monthly free credits plus signup credits; no card required.',
    signupUrl: 'https://dashboard.exa.ai/api-keys',
    docsUrl: 'https://exa.ai/docs/reference/search',
    keyHeader: 'X-Exa-Key',
    keyPlaceholder: 'exa-...',
    requiresPaymentMethod: false,
    attributionRequired: false,
    recommended: false,
    verifiedAt: '2026-08-01',
  },
  brave: {
    id: 'brave',
    displayName: 'Brave Search',
    freeTierSummary:
      '$5 monthly credits, about 1,000 searches; card required.',
    signupUrl: 'https://api-dashboard.search.brave.com/register',
    docsUrl:
      'https://api-dashboard.search.brave.com/documentation/quickstart',
    keyHeader: 'X-Brave-Key',
    keyPlaceholder: 'BSA...',
    requiresPaymentMethod: true,
    attributionRequired: true,
    recommended: false,
    verifiedAt: '2026-08-01',
  },
  serpapi: {
    id: 'serpapi',
    displayName: 'SerpAPI',
    freeTierSummary:
      '250 searches each month on recurring free plan.',
    signupUrl: 'https://serpapi.com/users/sign_up',
    docsUrl: 'https://serpapi.com/search-api',
    keyHeader: 'X-SerpApi-Key',
    keyPlaceholder: 'serpapi-...',
    requiresPaymentMethod: false,
    attributionRequired: false,
    recommended: false,
    verifiedAt: '2026-08-01',
  },
};
