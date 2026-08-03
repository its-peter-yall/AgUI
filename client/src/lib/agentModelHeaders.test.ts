/**
 * ============================================================================
 * FILE: agentModelHeaders.test.ts
 * LOCATION: client/src/lib/agentModelHeaders.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Tests per-agent model HTTP header builder.
 *
 * ROLE IN PROJECT:
 *    Locks role header names, cross-provider keys, and incomplete config errors.
 *
 * KEY COMPONENTS:
 *    - buildAgentModelHeaders tests
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: agentModelHeaders, providerSettings types
 *
 * USAGE:
 *    npm run test -- --run src/lib/agentModelHeaders.test.ts
 * ============================================================================
 */

import { describe, expect, it } from 'vitest';
import { buildAgentModelHeaders } from './agentModelHeaders';
import type { ProviderConfig, AIProviderSettings } from './providerSettings';

const baseConfig = (partial: Partial<ProviderConfig> = {}): ProviderConfig => ({
  apiKey: 'or-key',
  model: 'main/model',
  modelTitle: 'Main',
  thinking: { enabled: true, effort: 'high' },
  agentModels: {
    researcher: {
      modelId: 'r-model',
      modelProvider: 'openrouter',
      thinking: { enabled: false, effort: 'low' },
    },
    planner: {
      modelId: 'p-model',
      modelProvider: 'generalcompute',
      thinking: { enabled: false, effort: 'high' },
    },
    generator: {
      modelId: 'g-model',
      modelProvider: 'openrouter',
      thinking: { enabled: true, effort: 'medium' },
    },
    quizzer: {
      modelId: 'q-model',
      modelProvider: 'openrouter',
    },
  },
  ...partial,
});

const settings = (active: ProviderConfig): AIProviderSettings => ({
  activeProvider: 'openrouter',
  providers: {
    openrouter: active,
    generalcompute: {
      apiKey: 'gc-key',
      model: '',
      modelTitle: '',
    },
  },
});

describe('buildAgentModelHeaders', () => {
  it('emits model/provider/thinking headers for all four roles', () => {
    const h = buildAgentModelHeaders(settings(baseConfig()));
    expect(h['X-Researcher-Model']).toBe('r-model');
    expect(h['X-Researcher-Provider']).toBe('openrouter');
    expect(h['X-Planner-Model']).toBe('p-model');
    expect(h['X-Planner-Provider']).toBe('generalcompute');
    expect(h['X-Generator-Model']).toBe('g-model');
    expect(h['X-Generator-Thinking-Enabled']).toBe('true');
    expect(h['X-Generator-Thinking-Effort']).toBe('medium');
    expect(h['X-Quizzer-Model']).toBe('q-model');
    expect(h['X-Researcher-Thinking-Enabled']).toBeUndefined();
  });

  it('includes both provider keys when roles span providers', () => {
    const h = buildAgentModelHeaders(settings(baseConfig()));
    expect(h['X-OpenRouter-Key']).toBe('or-key');
    expect(h['X-GeneralCompute-Key']).toBe('gc-key');
  });

  it('throws when agent models incomplete', () => {
    expect(() =>
      buildAgentModelHeaders(
        settings(baseConfig({ agentModels: { researcher: { modelId: 'r' } } })),
      ),
    ).toThrow(/Researcher, Planner, Generator, and Quizzer/i);
  });
});
