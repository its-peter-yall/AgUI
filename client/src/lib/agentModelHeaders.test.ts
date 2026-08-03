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
import type { AIProviderSettings } from './providerSettings';

const fullAgentModels = {
  researcher: {
    modelId: 'r-model',
    modelProvider: 'openrouter' as const,
    thinking: { enabled: false as const, effort: 'low' as const },
  },
  planner: {
    modelId: 'p-model',
    modelProvider: 'generalcompute' as const,
    thinking: { enabled: false as const, effort: 'high' as const },
  },
  generator: {
    modelId: 'g-model',
    modelProvider: 'openrouter' as const,
    thinking: { enabled: true as const, effort: 'medium' as const },
  },
  quizzer: {
    modelId: 'q-model',
    modelProvider: 'openrouter' as const,
  },
};

const baseSettings = (
  partial: Partial<AIProviderSettings> = {},
): AIProviderSettings => ({
  activeProvider: 'openrouter',
  agentModels: fullAgentModels,
  providers: {
    openrouter: {
      apiKey: 'or-key',
      model: 'main/model',
      modelTitle: 'Main',
      thinking: { enabled: true, effort: 'high' },
    },
    generalcompute: {
      apiKey: 'gc-key',
      model: '',
      modelTitle: '',
    },
  },
  ...partial,
});

describe('buildAgentModelHeaders', () => {
  it('emits model/provider/thinking headers for all four roles', () => {
    const h = buildAgentModelHeaders(baseSettings());
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
    const h = buildAgentModelHeaders(baseSettings());
    expect(h['X-OpenRouter-Key']).toBe('or-key');
    expect(h['X-GeneralCompute-Key']).toBe('gc-key');
  });

  it('throws when agent models incomplete', () => {
    expect(() =>
      buildAgentModelHeaders(
        baseSettings({
          agentModels: { researcher: { modelId: 'r' } },
        }),
      ),
    ).toThrow(/Researcher, Planner, Generator, and Quizzer/i);
  });
});
