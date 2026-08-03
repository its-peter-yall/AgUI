/**
 * ============================================================================
 * FILE: providerSettings.test.ts
 * LOCATION: client/src/lib/providerSettings.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Unit tests for provider settings persistence and agent model helpers.
 *
 * ROLE IN PROJECT:
 *    Guards localStorage load/save and agent model configuration checks.
 *
 * KEY COMPONENTS:
 *    - agent model settings tests
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: providerSettings
 *
 * USAGE:
 *    npm run test -- --run src/lib/providerSettings.test.ts
 * ============================================================================
 */

import { beforeEach, describe, expect, it } from 'vitest';
import type { AgentRole } from '@/types/provider';
import {
  areAgentModelsConfigured,
  getAgentModelSelection,
  getProviderSettings,
  setAgentModelSelection,
  setProviderConfig,
} from './providerSettings';

describe('provider settings basics', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('returns empty defaults when storage empty', () => {
    const s = getProviderSettings();
    expect(s.activeProvider).toBe('openrouter');
    expect(s.providers.openrouter.apiKey).toBe('');
    expect(s.agentModels).toBeUndefined();
  });

  it('persists provider config', () => {
    setProviderConfig('openrouter', {
      apiKey: 'k',
      model: 'm',
      modelTitle: 'M',
    });
    const s = getProviderSettings();
    expect(s.providers.openrouter.apiKey).toBe('k');
    expect(s.providers.openrouter.model).toBe('m');
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
    expect(areAgentModelsConfigured(getProviderSettings())).toBe(false);
  });

  it('areAgentModelsConfigured true only when all four have modelId', () => {
    const roles: AgentRole[] = [
      'researcher',
      'planner',
      'generator',
      'quizzer',
    ];
    for (const role of roles) {
      setAgentModelSelection(role, {
        modelId: `${role}-model`,
        modelTitle: role,
        modelProvider: 'openrouter',
      });
    }
    expect(areAgentModelsConfigured(getProviderSettings())).toBe(true);
  });

  it('false when one role missing or blank modelId', () => {
    setAgentModelSelection('researcher', { modelId: 'r' });
    setAgentModelSelection('planner', { modelId: 'p' });
    setAgentModelSelection('generator', { modelId: 'g' });
    expect(areAgentModelsConfigured(getProviderSettings())).toBe(false);

    setAgentModelSelection('quizzer', { modelId: '   ' });
    expect(areAgentModelsConfigured(getProviderSettings())).toBe(false);
  });

  it('round-trips agentModels at top level through localStorage', () => {
    setAgentModelSelection('planner', {
      modelId: 'openai/gpt-4o',
      modelTitle: 'GPT-4o',
      modelProvider: 'generalcompute',
      thinking: { enabled: true, effort: 'medium' },
    });
    const again = getProviderSettings();
    expect(getAgentModelSelection(again, 'planner')).toEqual({
      modelId: 'openai/gpt-4o',
      modelTitle: 'GPT-4o',
      modelProvider: 'generalcompute',
      thinking: { enabled: true, effort: 'medium' },
    });
    // Survives active provider switch
    const raw = localStorage.getItem('ai_provider_settings');
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!);
    expect(parsed.agentModels.planner.modelId).toBe('openai/gpt-4o');
    expect(parsed.providers.openrouter.agentModels).toBeUndefined();
  });

  it('migrates legacy per-provider agentModels on load', () => {
    localStorage.setItem(
      'ai_provider_settings',
      JSON.stringify({
        activeProvider: 'generalcompute',
        providers: {
          openrouter: {
            apiKey: 'or',
            model: '',
            modelTitle: '',
            agentModels: {
              researcher: { modelId: 'r1', modelTitle: 'R' },
              planner: { modelId: 'p1' },
              generator: { modelId: 'g1' },
              quizzer: { modelId: 'q1' },
            },
          },
          generalcompute: {
            apiKey: 'gc',
            model: 'main',
            modelTitle: 'Main',
          },
        },
      }),
    );
    const s = getProviderSettings();
    expect(s.activeProvider).toBe('generalcompute');
    expect(areAgentModelsConfigured(s)).toBe(true);
    expect(s.agentModels?.researcher?.modelId).toBe('r1');
  });

  it('ignores invalid agentModels shape on load', () => {
    localStorage.setItem(
      'ai_provider_settings',
      JSON.stringify({
        activeProvider: 'openrouter',
        agentModels: { planner: 'bad' },
        providers: {
          openrouter: {
            apiKey: '',
            model: '',
            modelTitle: '',
          },
          generalcompute: {
            apiKey: '',
            model: '',
            modelTitle: '',
          },
        },
      }),
    );
    const s = getProviderSettings();
    expect(s.agentModels?.planner).toBeUndefined();
  });

  it('keeps agentModels when updating provider config', () => {
    setAgentModelSelection('researcher', { modelId: 'r' });
    setAgentModelSelection('planner', { modelId: 'p' });
    setAgentModelSelection('generator', { modelId: 'g' });
    setAgentModelSelection('quizzer', { modelId: 'q' });
    setProviderConfig('openrouter', { model: 'new-main', modelTitle: 'New' });
    expect(areAgentModelsConfigured(getProviderSettings())).toBe(true);
    expect(getProviderSettings().agentModels?.researcher?.modelId).toBe('r');
  });

  it('round-trips chatThinking with chat model', () => {
    setProviderConfig('openrouter', {
      apiKey: 'k',
      model: 'm',
      modelTitle: 'M',
      chatModel: 'or/think',
      chatModelTitle: 'Think',
      chatModelProvider: 'openrouter',
      chatThinking: { enabled: true, effort: 'medium' },
    });
    const cfg = getProviderSettings().providers.openrouter;
    expect(cfg.chatThinking).toEqual({ enabled: true, effort: 'medium' });
    expect(cfg.chatModel).toBe('or/think');
  });
});
