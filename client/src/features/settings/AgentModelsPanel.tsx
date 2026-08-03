/**
 * ============================================================================
 * FILE: AgentModelsPanel.tsx
 * LOCATION: client/src/features/settings/AgentModelsPanel.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Four role model pickers + per-role thinking for learning agents.
 *
 * ROLE IN PROJECT:
 *    Settings UI for per-agent model selection (Approach A headers).
 *
 * KEY COMPONENTS:
 *    - AgentModelsPanel: Researcher/Planner/Generator/Quizzer pickers
 *
 * DEPENDENCIES:
 *    - External: react, @tanstack/react-query, lucide-react
 *    - Internal: ModelPicker, ThinkingModeToggle, providerSettings, types
 *
 * USAGE:
 *    import { AgentModelsPanel } from './AgentModelsPanel';
 *    <AgentModelsPanel />
 * ============================================================================
 */

import { useCallback, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Bot } from 'lucide-react';

import { ModelPicker } from './ModelPicker';
import { ThinkingModeToggle } from './ThinkingModeToggle';
import {
  getProviderSettings,
  setAgentModelSelection,
} from '@/lib/providerSettings';
import { getProviderModels, ProviderApiError } from '@/lib/providerApi';
import { AGENT_ROLES } from '@/types/provider';
import type {
  AgentRole,
  AIProvider,
  ProviderModel,
  ThinkingEffort,
} from '@/types/provider';

const ROLE_META: Record<AgentRole, { label: string; help: string }> = {
  researcher: {
    label: 'Researcher',
    help: 'Web research plan and synthesis turns.',
  },
  planner: {
    label: 'Planner',
    help: 'Course outline and topic briefs.',
  },
  generator: {
    label: 'Generator',
    help: 'Topic card content generation.',
  },
  quizzer: {
    label: 'Quizzer',
    help: 'Quiz question generation.',
  },
};

export function AgentModelsPanel() {
  const [settings, setSettings] = useState(() => getProviderSettings());
  const activeProvider = settings.activeProvider;
  const activeConfig = settings.providers[activeProvider];

  const { data: orModels } = useQuery<ProviderModel[], ProviderApiError>({
    queryKey: [
      'provider-models',
      'openrouter',
      settings.providers.openrouter.apiKey,
    ],
    queryFn: () =>
      getProviderModels('openrouter', settings.providers.openrouter.apiKey),
    enabled: settings.providers.openrouter.apiKey.trim().length > 0,
    staleTime: 1000 * 60 * 60 * 24,
    retry: false,
  });

  const refresh = useCallback(() => {
    setSettings(getProviderSettings());
  }, []);

  const handleSelect = useCallback(
    (role: AgentRole) =>
      (provider: AIProvider, modelId: string, modelTitle: string) => {
        const prev = activeConfig.agentModels?.[role];
        setAgentModelSelection(activeProvider, role, {
          modelId,
          modelTitle,
          modelProvider: provider,
          thinking: prev?.thinking ?? { enabled: false, effort: 'high' },
        });
        refresh();
      },
    [activeConfig.agentModels, activeProvider, refresh],
  );

  const handleThinking = useCallback(
    (role: AgentRole) => (enabled: boolean, effort: ThinkingEffort) => {
      const prev = activeConfig.agentModels?.[role];
      if (!prev?.modelId) return;
      setAgentModelSelection(activeProvider, role, {
        ...prev,
        thinking: { enabled, effort },
      });
      refresh();
    },
    [activeConfig.agentModels, activeProvider, refresh],
  );

  return (
    <div className="flex flex-col gap-6">
      <p className="text-xs text-muted-foreground">
        Required before starting, resuming, or regenerating a course. Each role
        may use OpenRouter or General Compute independently.
      </p>
      {AGENT_ROLES.map((role) => {
        const sel = activeConfig.agentModels?.[role];
        const roleProvider = sel?.modelProvider ?? activeProvider;
        const supportsThinking =
          roleProvider === 'openrouter' &&
          !!sel?.modelId &&
          (orModels?.find((m) => m.id === sel.modelId)?.supports_thinking ??
            false);

        return (
          <div
            key={role}
            className="border border-border rounded-xl p-4 space-y-3"
          >
            <div className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-[#ffb74d]" aria-hidden="true" />
              <h3 className="text-sm font-semibold">{ROLE_META[role].label}</h3>
            </div>
            <p className="text-xs text-muted-foreground">
              {ROLE_META[role].help}
            </p>
            <ModelPicker
              openRouterKey={settings.providers.openrouter.apiKey}
              generalComputeKey={settings.providers.generalcompute.apiKey}
              activeProvider={roleProvider}
              activeModel={sel?.modelId ?? ''}
              onSelect={handleSelect(role)}
            />
            {sel?.modelTitle && (
              <p className="text-xs text-muted-foreground">
                Selected:{' '}
                <span className="font-medium text-foreground">
                  {sel.modelTitle}
                </span>
              </p>
            )}
            {roleProvider === 'openrouter' && sel?.modelId && (
              <ThinkingModeToggle
                enabled={sel.thinking?.enabled ?? false}
                effort={sel.thinking?.effort ?? 'high'}
                onChange={handleThinking(role)}
                supportsThinking={supportsThinking}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
