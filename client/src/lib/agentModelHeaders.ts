/**
 * ============================================================================
 * FILE: agentModelHeaders.ts
 * LOCATION: client/src/lib/agentModelHeaders.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Centralize per-agent model HTTP header names and builders.
 *
 * ROLE IN PROJECT:
 *    Shared by learningApi and regenApi for generate/resume/regen.
 *
 * KEY COMPONENTS:
 *    - agentModelHeaderName: role + kind → header name
 *    - buildAgentModelHeaders: full header map for learning mutations
 *
 * DEPENDENCIES:
 *    - External: None
 *    - Internal: types/provider, providerSettings, providerApi
 *
 * USAGE:
 *    const headers = buildAgentModelHeaders(getProviderSettings());
 * ============================================================================
 */

import { AGENT_ROLES } from '@/types/provider';
import type { AgentRole, AIProvider } from '@/types/provider';
import {
  areAgentModelsConfigured,
  type AIProviderSettings,
} from './providerSettings';
import { buildProviderHeaders } from './providerApi';

const ROLE_HEADER_PREFIX: Record<AgentRole, string> = {
  researcher: 'Researcher',
  planner: 'Planner',
  generator: 'Generator',
  quizzer: 'Quizzer',
};

export function agentModelHeaderName(
  role: AgentRole,
  kind: 'Model' | 'Provider' | 'Thinking-Enabled' | 'Thinking-Effort',
): string {
  return `X-${ROLE_HEADER_PREFIX[role]}-${kind}`;
}

/**
 * Build base LLM headers (active provider model for depth_router) plus
 * required per-role agent headers. Throws if four roles incomplete.
 */
export function buildAgentModelHeaders(
  settings: AIProviderSettings,
): Record<string, string> {
  const active = settings.providers[settings.activeProvider];
  if (!areAgentModelsConfigured(settings)) {
    throw new Error(
      'Set Researcher, Planner, Generator, and Quizzer models in Settings before generating.',
    );
  }

  const headers = buildProviderHeaders(
    settings.activeProvider,
    active.apiKey,
    active.model || undefined,
    active.thinking,
    active.maxCompletionTokens,
  );

  const orKey = settings.providers.openrouter.apiKey?.trim();
  const gcKey = settings.providers.generalcompute.apiKey?.trim();
  if (orKey) headers['X-OpenRouter-Key'] = orKey;
  if (gcKey) headers['X-GeneralCompute-Key'] = gcKey;

  for (const role of AGENT_ROLES) {
    const sel = settings.agentModels![role]!;
    const provider: AIProvider =
      sel.modelProvider ?? settings.activeProvider;
    headers[agentModelHeaderName(role, 'Model')] = sel.modelId.trim();
    headers[agentModelHeaderName(role, 'Provider')] = provider;
    if (sel.thinking?.enabled) {
      headers[agentModelHeaderName(role, 'Thinking-Enabled')] = 'true';
      headers[agentModelHeaderName(role, 'Thinking-Effort')] =
        sel.thinking.effort || 'high';
    }
  }

  return headers;
}
