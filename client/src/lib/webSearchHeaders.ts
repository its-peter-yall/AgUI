/**
 * ============================================================================
 * FILE: webSearchHeaders.ts
 * LOCATION: client/src/lib/webSearchHeaders.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Pure explicit web-search request header builder.
 *
 * ROLE IN PROJECT:
 *    Builds X-Web-Search* headers only for generate/resume. Keeps search keys
 *    off session, quiz, research, cancel, and delete calls.
 *
 * KEY COMPONENTS:
 *    - WebSearchConfigurationError: Thrown when opt-in lacks capability
 *    - buildWebSearchHeaders: Constructs headers from settings
 *
 * DEPENDENCIES:
 *    - External: None
 *    - Internal: @/lib/webSearchProviders, @/lib/providerSettings, @/types/webSearch
 *
 * USAGE:
 *    const headers = buildWebSearchHeaders(true);
 * ============================================================================
 */

import {
  WEB_SEARCH_PROVIDER_IDS,
  WEB_SEARCH_PROVIDERS,
} from '@/lib/webSearchProviders';
import { getWebSearchSettings } from '@/lib/providerSettings';
import type { WebSearchSettings } from '@/types/webSearch';

export class WebSearchConfigurationError extends Error {
  constructor(message = 'Web search is not configured') {
    super(message);
    this.name = 'WebSearchConfigurationError';
  }
}

/**
 * Builds web-search headers for generate/resume only.
 * Trims keys; includes only enabled providers with nonblank keys in registry order.
 */
export function buildWebSearchHeaders(
  courseEnabled: boolean,
  settings: WebSearchSettings = getWebSearchSettings(),
): Record<string, string> {
  if (!courseEnabled) {
    return { 'X-Web-Search': 'false' };
  }

  if (!settings.masterEnabled) {
    throw new WebSearchConfigurationError(
      'Web search master switch is off',
    );
  }

  const selectedIds = WEB_SEARCH_PROVIDER_IDS.filter((id) => {
    const config = settings.providers[id];
    return config.enabled && config.apiKey.trim().length > 0;
  });

  if (selectedIds.length === 0) {
    throw new WebSearchConfigurationError(
      'No configured web search providers available',
    );
  }

  const headers: Record<string, string> = {
    'X-Web-Search': 'true',
    'X-Web-Search-Providers': selectedIds.join(','),
  };

  for (const id of selectedIds) {
    const meta = WEB_SEARCH_PROVIDERS[id];
    headers[meta.keyHeader] = settings.providers[id].apiKey.trim();
  }

  return headers;
}
