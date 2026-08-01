/**
 * ============================================================================
 * FILE: WebSearchSettingsPanel.tsx
 * LOCATION: client/src/features/settings/WebSearchSettingsPanel.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Master toggle and curated web-search provider cards for Settings.
 *
 * ROLE IN PROJECT:
 *    Lets users enable optional web search, store provider keys in the browser,
 *    and configure which providers participate in course research.
 *
 * KEY COMPONENTS:
 *    - WebSearchSettingsPanel: Master switch + four provider cards
 *
 * DEPENDENCIES:
 *    - External: react, lucide-react
 *    - Internal: @/lib/providerSettings, @/lib/webSearchProviders, @/lib/utils
 *
 * USAGE:
 *    import { WebSearchSettingsPanel } from './WebSearchSettingsPanel';
 *    <WebSearchSettingsPanel />
 * ============================================================================
 */

import { useCallback, useState } from 'react';
import { AlertTriangle, ExternalLink, Star } from 'lucide-react';

import {
  WEB_SEARCH_PROVIDER_IDS,
  WEB_SEARCH_PROVIDERS,
} from '@/lib/webSearchProviders';
import {
  getWebSearchSettings,
  setWebSearchMasterEnabled,
  setWebSearchProviderConfig,
} from '@/lib/providerSettings';
import type { WebSearchProviderId, WebSearchSettings } from '@/types/webSearch';
import { cn } from '@/lib/utils';

export function WebSearchSettingsPanel() {
  const [settings, setSettings] = useState<WebSearchSettings>(() =>
    getWebSearchSettings(),
  );
  const [keyErrors, setKeyErrors] = useState<
    Partial<Record<WebSearchProviderId, string>>
  >({});

  const refresh = useCallback(() => {
    setSettings(getWebSearchSettings());
  }, []);

  const handleMasterToggle = useCallback(() => {
    const next = !settings.masterEnabled;
    setWebSearchMasterEnabled(next);
    refresh();
  }, [refresh, settings.masterEnabled]);

  const handleKeyChange = useCallback(
    (providerId: WebSearchProviderId, value: string) => {
      setWebSearchProviderConfig(providerId, { apiKey: value });
      setKeyErrors((prev) => {
        if (!prev[providerId]) return prev;
        const next = { ...prev };
        delete next[providerId];
        return next;
      });
      refresh();
    },
    [refresh],
  );

  const handleEnableToggle = useCallback(
    (providerId: WebSearchProviderId) => {
      const config = settings.providers[providerId];
      const nextEnabled = !config.enabled;
      if (nextEnabled && !config.apiKey.trim()) {
        setKeyErrors((prev) => ({
          ...prev,
          [providerId]: 'API key is required',
        }));
        return;
      }
      setWebSearchProviderConfig(providerId, { enabled: nextEnabled });
      setKeyErrors((prev) => {
        if (!prev[providerId]) return prev;
        const next = { ...prev };
        delete next[providerId];
        return next;
      });
      refresh();
    },
    [refresh, settings.providers],
  );

  return (
    <div className="w-full flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-foreground">
            Optional web search
          </p>
          <p className="text-xs text-muted-foreground mt-0.5">
            Ground courses in current internet sources when you opt in per
            course.
          </p>
        </div>
        <input
          type="checkbox"
          role="switch"
          checked={settings.masterEnabled}
          aria-label="Enable web search"
          onChange={handleMasterToggle}
          className={cn(
            'h-5 w-9 cursor-pointer accent-[#ffb74d]',
            'focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ffb74d] rounded',
          )}
        />
      </div>

      {settings.masterEnabled && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {WEB_SEARCH_PROVIDER_IDS.map((providerId) => {
            const meta = WEB_SEARCH_PROVIDERS[providerId];
            const config = settings.providers[providerId];
            const error = keyErrors[providerId];
            const keyLabel = `${meta.displayName} API key`;

            return (
              <div
                key={providerId}
                className={cn(
                  'p-4 rounded-xl border border-border bg-card/80 backdrop-blur-md shadow-sm',
                  'flex flex-col gap-3',
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <h3 className="text-sm font-bold tracking-wide text-foreground">
                      {meta.displayName}
                    </h3>
                    {meta.recommended && (
                      <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold uppercase tracking-wider text-[#ffb74d] bg-[#ffb74d]/10 border border-[#ffb74d]/30 px-1.5 py-0.5 rounded">
                        <Star className="h-3 w-3" aria-hidden="true" />
                        Recommended
                      </span>
                    )}
                  </div>
                  <label className="inline-flex items-center gap-1.5 text-xs text-muted-foreground shrink-0 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={config.enabled}
                      onChange={() => handleEnableToggle(providerId)}
                      aria-label={`Enable ${meta.displayName}`}
                      className="rounded border-border text-[#ffb74d] focus:ring-[#ffb74d]"
                    />
                    Enable
                  </label>
                </div>

                <p className="text-xs text-muted-foreground leading-relaxed">
                  {meta.freeTierSummary}
                </p>

                {meta.requiresPaymentMethod && (
                  <p className="text-xs text-amber-600 dark:text-amber-400 flex items-start gap-1.5">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                    Card required for free-tier signup.
                  </p>
                )}

                {meta.attributionRequired && (
                  <p className="text-xs text-muted-foreground">
                    Attribution required: sources from this provider show
                    &quot;Powered by Brave&quot;.
                  </p>
                )}

                <div className="flex flex-col gap-1.5">
                  <label
                    htmlFor={`web-search-key-${providerId}`}
                    className="text-xs font-semibold text-muted-foreground uppercase tracking-wider"
                  >
                    {keyLabel}
                  </label>
                  <input
                    id={`web-search-key-${providerId}`}
                    type="password"
                    value={config.apiKey}
                    onChange={(e) =>
                      handleKeyChange(providerId, e.target.value)
                    }
                    placeholder={meta.keyPlaceholder}
                    autoComplete="off"
                    className={cn(
                      'w-full rounded-lg px-3 py-2 text-sm',
                      'bg-muted border text-foreground placeholder:text-muted-foreground',
                      'focus:outline-none focus:ring-2 focus:ring-[#ffb74d]/50 transition-all',
                      error ? 'border-destructive/50' : 'border-border',
                    )}
                  />
                  {error && (
                    <p role="alert" className="text-xs text-red-400 font-medium">
                      {error}
                    </p>
                  )}
                </div>

                <div className="flex flex-wrap gap-3 text-xs">
                  <a
                    href={meta.signupUrl}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1 text-[#ffb74d] hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ffb74d] rounded"
                  >
                    Get {meta.displayName} key
                    <ExternalLink className="h-3 w-3" aria-hidden="true" />
                  </a>
                  <a
                    href={meta.docsUrl}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ffb74d] rounded"
                  >
                    Docs
                    <ExternalLink className="h-3 w-3" aria-hidden="true" />
                  </a>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
