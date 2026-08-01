/**
 * ============================================================================
 * FILE: webSearch.ts
 * LOCATION: client/src/types/webSearch.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Browser web-search provider settings and metadata contracts.
 *
 * ROLE IN PROJECT:
 *    Mirrors the server search registry on the client for Settings display
 *    and request header construction.
 *
 * KEY COMPONENTS:
 *    - WebSearchProviderId: The four locked provider IDs
 *    - WebSearchProviderConfig: Per-provider key and enablement
 *    - WebSearchSettings: Master switch plus provider configs
 *    - WebSearchProviderMetadata: Static provider display metadata
 *
 * DEPENDENCIES:
 *    - External: None
 *    - Internal: None
 *
 * USAGE:
 *    import type { WebSearchSettings } from '@/types/webSearch';
 * ============================================================================
 */

export type WebSearchProviderId =
  | 'tavily'
  | 'exa'
  | 'brave'
  | 'serpapi';

export interface WebSearchProviderConfig {
  apiKey: string;
  enabled: boolean;
}

export interface WebSearchSettings {
  masterEnabled: boolean;
  providers: Record<WebSearchProviderId, WebSearchProviderConfig>;
}

export interface WebSearchProviderMetadata {
  id: WebSearchProviderId;
  displayName: string;
  freeTierSummary: string;
  signupUrl: string;
  docsUrl: string;
  keyHeader: string;
  keyPlaceholder: string;
  requiresPaymentMethod: boolean;
  attributionRequired: boolean;
  recommended: boolean;
  verifiedAt: string;
}
