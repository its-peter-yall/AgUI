/**
 * ============================================================================
 * FILE: providerSettings.test.ts
 * LOCATION: client/src/lib/providerSettings.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Tests AI and web-search settings persistence boundaries.
 *
 * ROLE IN PROJECT:
 *    Guarantees web capability is hidden and inactive by default while keys
 *    remain browser-local at rest.
 *
 * KEY COMPONENTS:
 *    - Web-search defaults, parsing, updates, and capability tests
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: @/lib/providerSettings
 *
 * USAGE:
 *    npm run test -- --run src/lib/providerSettings.test.ts
 * ============================================================================
 */

import { beforeEach, describe, expect, it } from 'vitest';

import {
  WEB_SEARCH_STORAGE_KEY,
  areAgentModelsConfigured,
  getAgentModelSelection,
  getConfiguredWebSearchProviders,
  getProviderSettings,
  getWebSearchSettings,
  hasWebSearchCapability,
  setAgentModelSelection,
  setProviderConfig,
  setWebSearchMasterEnabled,
  setWebSearchProviderConfig,
} from '@/lib/providerSettings';
import type { AgentRole } from '@/types/provider';

describe('web search provider settings', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('defaults master and every provider to off', () => {
    expect(getWebSearchSettings()).toEqual({
      masterEnabled: false,
      providers: {
        tavily: { apiKey: '', enabled: false },
        exa: { apiKey: '', enabled: false },
        brave: { apiKey: '', enabled: false },
        serpapi: { apiKey: '', enabled: false },
      },
    });
    expect(hasWebSearchCapability()).toBe(false);
  });

  it('recovers safely from malformed storage', () => {
    localStorage.setItem(WEB_SEARCH_STORAGE_KEY, '{bad json');
    expect(getWebSearchSettings().masterEnabled).toBe(false);
    expect(getConfiguredWebSearchProviders()).toEqual([]);
  });

  it('normalizes partial records and discards unknown providers', () => {
    localStorage.setItem(
      WEB_SEARCH_STORAGE_KEY,
      JSON.stringify({
        masterEnabled: true,
        providers: {
          tavily: { apiKey: '  tvly-key  ', enabled: true },
          unknown: { apiKey: 'unknown-key', enabled: true },
        },
      }),
    );
    expect(getWebSearchSettings()).toEqual({
      masterEnabled: true,
      providers: {
        tavily: { apiKey: '  tvly-key  ', enabled: true },
        exa: { apiKey: '', enabled: false },
        brave: { apiKey: '', enabled: false },
        serpapi: { apiKey: '', enabled: false },
      },
    });
  });

  it('requires master, enabled provider, and nonblank key for capability', () => {
    setWebSearchProviderConfig('exa', {
      apiKey: 'exa-key',
      enabled: true,
    });
    expect(hasWebSearchCapability()).toBe(false);

    setWebSearchMasterEnabled(true);
    expect(hasWebSearchCapability()).toBe(true);
    expect(getConfiguredWebSearchProviders()).toEqual(['exa']);

    setWebSearchProviderConfig('exa', { apiKey: '   ' });
    expect(hasWebSearchCapability()).toBe(false);
  });

  it('does not mix web keys into AI provider storage', () => {
    setWebSearchMasterEnabled(true);
    setWebSearchProviderConfig('brave', {
      apiKey: 'brave-browser-key',
      enabled: true,
    });
    expect(localStorage.getItem('ai_provider_settings')).toBeNull();
    expect(localStorage.getItem(WEB_SEARCH_STORAGE_KEY)).toContain(
      'brave-browser-key',
    );
  });
});

describe('agent model settings', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('treats missing agentModels as unconfigured', () => {
    setProviderConfig('openrouter', {
      apiKey: 'k',
      model: 'm',
      modelTitle: 'M',
    });
    const cfg = getProviderSettings().providers.openrouter;
    expect(areAgentModelsConfigured(cfg)).toBe(false);
  });

  it('areAgentModelsConfigured true only when all four have modelId', () => {
    const roles: AgentRole[] = [
      'researcher',
      'planner',
      'generator',
      'quizzer',
    ];
    for (const role of roles) {
      setAgentModelSelection('openrouter', role, {
        modelId: `${role}-model`,
        modelTitle: role,
        modelProvider: 'openrouter',
      });
    }
    const cfg = getProviderSettings().providers.openrouter;
    expect(areAgentModelsConfigured(cfg)).toBe(true);
  });

  it('false when one role missing or blank modelId', () => {
    setAgentModelSelection('openrouter', 'researcher', {
      modelId: 'r',
    });
    setAgentModelSelection('openrouter', 'planner', { modelId: 'p' });
    setAgentModelSelection('openrouter', 'generator', { modelId: 'g' });
    // quizzer missing
    expect(
      areAgentModelsConfigured(
        getProviderSettings().providers.openrouter,
      ),
    ).toBe(false);

    setAgentModelSelection('openrouter', 'quizzer', { modelId: '   ' });
    expect(
      areAgentModelsConfigured(
        getProviderSettings().providers.openrouter,
      ),
    ).toBe(false);
  });

  it('round-trips agentModels through localStorage', () => {
    setAgentModelSelection('openrouter', 'planner', {
      modelId: 'openai/gpt-4o',
      modelTitle: 'GPT-4o',
      modelProvider: 'generalcompute',
      thinking: { enabled: true, effort: 'medium' },
    });
    const again = getProviderSettings().providers.openrouter;
    expect(getAgentModelSelection(again, 'planner')).toEqual({
      modelId: 'openai/gpt-4o',
      modelTitle: 'GPT-4o',
      modelProvider: 'generalcompute',
      thinking: { enabled: true, effort: 'medium' },
    });
  });

  it('ignores invalid agentModels shape on load', () => {
    localStorage.setItem(
      'ai_provider_settings',
      JSON.stringify({
        activeProvider: 'openrouter',
        providers: {
          openrouter: {
            apiKey: '',
            model: '',
            modelTitle: '',
            agentModels: { planner: 'bad' },
          },
          generalcompute: {
            apiKey: '',
            model: '',
            modelTitle: '',
          },
        },
      }),
    );
    const cfg = getProviderSettings().providers.openrouter;
    expect(cfg.agentModels?.planner).toBeUndefined();
  });
});
