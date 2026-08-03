/**
 * ============================================================================
 * FILE: providerSettings.ts
 * LOCATION: client/src/lib/providerSettings.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Manages multi-provider (OpenRouter, General Compute) settings in
 *    localStorage.
 *
 * ROLE IN PROJECT:
 *    Provides read/write/clear/mask capabilities for provider-specific API keys
 *    and model selections. Seamlessly migrates legacy OpenRouter settings on first access.
 *
 * KEY COMPONENTS:
 *    - ProviderConfig: Per-provider API key and model selection structure
 *    - AIProviderSettings: Registry-wide active provider and configuration mapping
 *    - getProviderSettings(): Safe load with legacy migration logic
 *    - setProviderSettings(): Merge and persist settings
 *    - getActiveProviderConfig(): Shorthand to active provider's config
 *    - setProviderConfig(): Update a specific provider's configuration
 *    - clearProviderConfig(): Reset a specific provider's configuration
 *    - getWebSearchSettings(): Safe load of browser-only web search settings
 *    - setWebSearchSettings(): Persist web search settings to its own key
 *    - hasWebSearchCapability(): Master + enabled provider + nonblank key check
 *
 * DEPENDENCIES:
 *    - External: None
 *    - Internal: @/types/provider, @/types/webSearch, @/lib/webSearchProviders
 *
 * USAGE:
 *    import { getProviderSettings, setProviderConfig } from '@/lib/providerSettings';
 * ============================================================================
 */

import type {
	AIProvider,
	AgentModelSelection,
	AgentRole,
	ThinkingConfig,
	ThinkingEffort,
} from "@/types/provider";
import { AGENT_ROLES } from "@/types/provider";
import type {
	WebSearchProviderConfig,
	WebSearchProviderId,
	WebSearchSettings,
} from "@/types/webSearch";
import { WEB_SEARCH_PROVIDER_IDS } from "@/lib/webSearchProviders";

const STORAGE_KEY = "ai_provider_settings";
const LEGACY_STORAGE_KEY = "openrouter_settings";

export interface ProviderConfig {
	apiKey: string;
	model: string;
	modelTitle: string;
	chatModel?: string;
	chatModelTitle?: string;
	chatModelProvider?: AIProvider;
	maxCompletionTokens?: number;
	thinking?: ThinkingConfig;
	agentModels?: Partial<Record<AgentRole, AgentModelSelection>>;
}

export interface AIProviderSettings {
	activeProvider: AIProvider;
	providers: Record<AIProvider, ProviderConfig>;
}

const EMPTY_CONFIG: ProviderConfig = {
	apiKey: "",
	model: "",
	modelTitle: "",
	maxCompletionTokens: undefined,
	thinking: {
		enabled: false,
		effort: "high",
	},
};

/**
 * Reads settings from localStorage, migrating legacy OpenRouter settings if present.
 */
export function getProviderSettings(): AIProviderSettings {
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (raw) {
			const parsed = JSON.parse(raw) as Partial<AIProviderSettings>;
			return {
				activeProvider:
					parsed?.activeProvider === "generalcompute"
						? "generalcompute"
						: "openrouter",
				providers: {
					openrouter: {
						apiKey:
							typeof parsed?.providers?.openrouter?.apiKey === "string"
								? parsed.providers.openrouter.apiKey
								: "",
						model:
							typeof parsed?.providers?.openrouter?.model === "string"
								? parsed.providers.openrouter.model
								: "",
						modelTitle:
							typeof parsed?.providers?.openrouter?.modelTitle === "string"
								? parsed.providers.openrouter.modelTitle
								: "",
						chatModel:
							typeof parsed?.providers?.openrouter?.chatModel === "string"
								? parsed.providers.openrouter.chatModel
								: undefined,
						chatModelTitle:
							typeof parsed?.providers?.openrouter?.chatModelTitle === "string"
								? parsed.providers.openrouter.chatModelTitle
								: undefined,
						chatModelProvider:
							parsed?.providers?.openrouter?.chatModelProvider ===
							"generalcompute"
								? "generalcompute"
								: parsed?.providers?.openrouter?.chatModelProvider ===
										"openrouter"
									? "openrouter"
									: undefined,
						maxCompletionTokens:
							parsed?.providers?.openrouter?.maxCompletionTokens ?? undefined,
						thinking: parsed?.providers?.openrouter?.thinking ?? {
							enabled: false,
							effort: "high",
						},
					},
					generalcompute: {
						apiKey:
							typeof parsed?.providers?.generalcompute?.apiKey === "string"
								? parsed.providers.generalcompute.apiKey
								: "",
						model:
							typeof parsed?.providers?.generalcompute?.model === "string"
								? parsed.providers.generalcompute.model
								: "",
						modelTitle:
							typeof parsed?.providers?.generalcompute?.modelTitle === "string"
								? parsed.providers.generalcompute.modelTitle
								: "",
						chatModel:
							typeof parsed?.providers?.generalcompute?.chatModel === "string"
								? parsed.providers.generalcompute.chatModel
								: undefined,
						chatModelTitle:
							typeof parsed?.providers?.generalcompute?.chatModelTitle ===
							"string"
								? parsed.providers.generalcompute.chatModelTitle
								: undefined,
						chatModelProvider:
							parsed?.providers?.generalcompute?.chatModelProvider ===
							"generalcompute"
								? "generalcompute"
								: parsed?.providers?.generalcompute?.chatModelProvider ===
										"openrouter"
									? "openrouter"
									: undefined,
						maxCompletionTokens:
							parsed?.providers?.generalcompute?.maxCompletionTokens ??
							undefined,
						thinking: parsed?.providers?.generalcompute?.thinking ?? {
							enabled: false,
							effort: "high",
						},
					},
				},
			};
		}

		// Try reading legacy format
		const legacyRaw = localStorage.getItem(LEGACY_STORAGE_KEY);
		if (legacyRaw) {
			const legacyParsed = JSON.parse(legacyRaw) as {
				apiKey?: string;
				model?: string;
				modelTitle?: string;
			};
			const migrated: AIProviderSettings = {
				activeProvider: "openrouter",
				providers: {
					openrouter: {
						apiKey:
							typeof legacyParsed.apiKey === "string"
								? legacyParsed.apiKey
								: "",
						model:
							typeof legacyParsed.model === "string" ? legacyParsed.model : "",
						modelTitle:
							typeof legacyParsed.modelTitle === "string"
								? legacyParsed.modelTitle
								: "",
						thinking: { enabled: false, effort: "high" },
					},
					generalcompute: { ...EMPTY_CONFIG },
				},
			};
			// Save migrated data & cleanup legacy
			localStorage.setItem(STORAGE_KEY, JSON.stringify(migrated));
			localStorage.removeItem(LEGACY_STORAGE_KEY);
			return migrated;
		}

		return {
			activeProvider: "openrouter",
			providers: {
				openrouter: { ...EMPTY_CONFIG },
				generalcompute: { ...EMPTY_CONFIG },
			},
		};
	} catch {
		return {
			activeProvider: "openrouter",
			providers: {
				openrouter: { ...EMPTY_CONFIG },
				generalcompute: { ...EMPTY_CONFIG },
			},
		};
	}
}

/**
 * Partially updates settings in localStorage, merging with existing values.
 */
export function setProviderSettings(
	partial: Partial<AIProviderSettings>,
): void {
	const current = getProviderSettings();
	const merged: AIProviderSettings = {
		activeProvider:
			partial.activeProvider !== undefined
				? partial.activeProvider
				: current.activeProvider,
		providers: {
			openrouter: partial.providers?.openrouter
				? { ...current.providers.openrouter, ...partial.providers.openrouter }
				: current.providers.openrouter,
			generalcompute: partial.providers?.generalcompute
				? {
						...current.providers.generalcompute,
						...partial.providers.generalcompute,
					}
				: current.providers.generalcompute,
		},
	};
	localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
}

/**
 * Returns configuration for the active provider.
 */
export function getActiveProviderConfig(): ProviderConfig {
	const settings = getProviderSettings();
	return settings.providers[settings.activeProvider];
}

/**
 * Sets the active AI provider.
 */
export function setActiveProvider(provider: AIProvider): void {
	setProviderSettings({ activeProvider: provider });
}

/**
 * Updates a specific provider's configuration.
 */
export function setProviderConfig(
	provider: AIProvider,
	config: Partial<ProviderConfig>,
): void {
	const settings = getProviderSettings();
	const updatedProviders = {
		...settings.providers,
		[provider]: {
			...settings.providers[provider],
			...config,
		},
	};
	setProviderSettings({ providers: updatedProviders });
}

/**
 * Resets a specific provider's configuration.
 */
export function clearProviderConfig(provider: AIProvider): void {
	setProviderConfig(provider, { ...EMPTY_CONFIG });
}

/**
 * Updates thinking configuration for a specific provider.
 */
export function setProviderThinking(
	provider: AIProvider,
	thinking: ThinkingConfig,
): void {
	const settings = getProviderSettings();
	const updatedProviders = {
		...settings.providers,
		[provider]: {
			...settings.providers[provider],
			thinking: {
				enabled: thinking.enabled,
				effort: thinking.effort,
			},
		},
	};
	setProviderSettings({ providers: updatedProviders });
}

/**
 * Masks an API key for safe display.
 */
export function maskApiKey(key: string | undefined | null): string {
	if (!key || key.length < 8) {
		return "";
	}
	const suffix = key.slice(-4);
	return `${key.slice(0, 6)}...${suffix}`;
}

export const WEB_SEARCH_STORAGE_KEY = "web_search_settings";

function createDefaultWebSearchSettings(): WebSearchSettings {
	return {
		masterEnabled: false,
		providers: {
			tavily: { apiKey: "", enabled: false },
			exa: { apiKey: "", enabled: false },
			brave: { apiKey: "", enabled: false },
			serpapi: { apiKey: "", enabled: false },
		},
	};
}

/**
 * Reads web-search settings from their own localStorage key, defaulting
 * missing or invalid fields and discarding unknown providers. Never rewrites
 * malformed storage and returns fresh nested objects.
 */
export function getWebSearchSettings(): WebSearchSettings {
	const fallback = createDefaultWebSearchSettings();
	try {
		const raw = localStorage.getItem(WEB_SEARCH_STORAGE_KEY);
		if (!raw) {
			return fallback;
		}
		const parsed = JSON.parse(raw) as Partial<WebSearchSettings>;
		const providers = { ...fallback.providers };
		const parsedProviders =
			parsed && typeof parsed === "object" ? parsed.providers : undefined;
		if (parsedProviders && typeof parsedProviders === "object") {
			for (const providerId of WEB_SEARCH_PROVIDER_IDS) {
				const entry = parsedProviders[providerId] as
					| Partial<WebSearchProviderConfig>
					| undefined;
				if (!entry || typeof entry !== "object") {
					continue;
				}
				providers[providerId] = {
					apiKey:
						typeof entry.apiKey === "string" ? entry.apiKey : "",
					enabled:
						typeof entry.enabled === "boolean" ? entry.enabled : false,
				};
			}
		}
		return {
			masterEnabled:
				typeof parsed?.masterEnabled === "boolean"
					? parsed.masterEnabled
					: false,
			providers,
		};
	} catch {
		return fallback;
	}
}

/**
 * Persists web-search settings only to WEB_SEARCH_STORAGE_KEY.
 */
export function setWebSearchSettings(settings: WebSearchSettings): void {
	localStorage.setItem(WEB_SEARCH_STORAGE_KEY, JSON.stringify(settings));
}

/**
 * Enables or disables web search at the master level.
 */
export function setWebSearchMasterEnabled(enabled: boolean): void {
	const settings = getWebSearchSettings();
	setWebSearchSettings({ ...settings, masterEnabled: enabled });
}

/**
 * Updates a single provider's key and/or enablement.
 */
export function setWebSearchProviderConfig(
	providerId: WebSearchProviderId,
	config: Partial<WebSearchProviderConfig>,
): void {
	const settings = getWebSearchSettings();
	setWebSearchSettings({
		...settings,
		providers: {
			...settings.providers,
			[providerId]: {
				...settings.providers[providerId],
				...config,
			},
		},
	});
}

/**
 * Returns enabled providers with nonblank keys in registry display order.
 */
export function getConfiguredWebSearchProviders(): WebSearchProviderId[] {
	const settings = getWebSearchSettings();
	return WEB_SEARCH_PROVIDER_IDS.filter(
		(providerId) =>
			settings.providers[providerId].enabled &&
			settings.providers[providerId].apiKey.trim().length > 0,
	);
}

/**
 * True only when the master switch and at least one provider key are set.
 */
export function hasWebSearchCapability(): boolean {
	return (
		getWebSearchSettings().masterEnabled &&
		getConfiguredWebSearchProviders().length > 0
	);
}
