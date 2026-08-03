/**
 * ============================================================================
 * FILE: storageBoot.ts
 * LOCATION: client/src/lib/storageBoot.ts
 * ============================================================================
 *
 * PURPOSE:
 *    One-shot storage boot: connect, hydrate app settings, enable write-through.
 *
 * ROLE IN PROJECT:
 *    Runs before first React render so Mongo-backed settings load once and
 *    subsequent provider/search saves serialize complete snapshots to Mongo.
 *    Hydration never blanks non-empty local API keys with empty cloud secrets.
 *
 * KEY COMPONENTS:
 *    - bootstrapStorage: singleton boot promise
 *    - hydrateAndEnableCloudSettings: Settings connect path
 *    - merge helpers: secret-preserving cloud hydrate
 *    - disableCloudSettingsSync: disconnect path
 *    - resetStorageBootForTests: test isolation only
 *
 * DEPENDENCIES:
 *    - External: None
 *    - Internal: storageApi, mongoStorageSettings, providerSettings
 *
 * USAGE:
 *    await bootstrapStorage();
 * ============================================================================
 */

import { getMongoStorageSettings } from '@/lib/mongoStorageSettings';
import {
  APP_SETTINGS_CHANGED_EVENT,
  APP_SETTINGS_HYDRATED_EVENT,
  getProviderSettings,
  getWebSearchSettings,
  setProviderSettings,
  setWebSearchSettings,
  type AIProviderSettings,
  type ProviderConfig,
} from '@/lib/providerSettings';
import {
  connectStorage,
  getAppSettings,
  getStorageStatus,
  putAppSettings,
} from '@/lib/storageApi';
import type { AppSettingsSnapshot, StorageStatus } from '@/types/storage';
import type {
  WebSearchProviderConfig,
  WebSearchSettings,
} from '@/types/webSearch';
import { WEB_SEARCH_PROVIDER_IDS } from '@/lib/webSearchProviders';

export interface StorageBootResult {
  status: StorageStatus | null;
  error: string | null;
}

let bootPromise: Promise<StorageBootResult> | null = null;
let stopCloudSync: (() => void) | null = null;

export function bootstrapStorage(): Promise<StorageBootResult> {
  if (!bootPromise) bootPromise = runStorageBoot();
  return bootPromise;
}

async function runStorageBoot(): Promise<StorageBootResult> {
  try {
    let status = await getStorageStatus();
    if (status.deploymentMode === 'local' && !status.connected) {
      const connection = getMongoStorageSettings();
      if (connection) status = await connectStorage(connection);
    }
    if (status.activeBackend === 'mongo') {
      await applyCloudSnapshotAndSync();
    }
    return { status, error: null };
  } catch (error: unknown) {
    const message =
      error instanceof Error ? error.message : 'Storage boot failed';
    console.error('Storage boot failed:', error);
    return { status: null, error: message };
  }
}

function isBlankSecret(value: unknown): boolean {
  return typeof value !== 'string' || value.trim().length === 0;
}

function pickSecret(cloud: unknown, local: string): string {
  if (!isBlankSecret(cloud)) return cloud as string;
  return local;
}

function hasProviderShape(
  value: AIProviderSettings | null | undefined,
): value is AIProviderSettings {
  return (
    value != null &&
    typeof value === 'object' &&
    value.providers != null &&
    typeof value.providers === 'object'
  );
}

function hasWebSearchShape(
  value: WebSearchSettings | null | undefined,
): value is WebSearchSettings {
  return (
    value != null &&
    typeof value === 'object' &&
    value.providers != null &&
    typeof value.providers === 'object'
  );
}

function mergeProviderConfig(
  local: ProviderConfig,
  cloud?: Partial<ProviderConfig>,
): ProviderConfig {
  if (!cloud || typeof cloud !== 'object') return local;
  return {
    ...local,
    ...cloud,
    apiKey: pickSecret(cloud.apiKey, local.apiKey),
  };
}

/** Cloud hydrate merge: never blank non-empty local secrets. */
export function mergeProviderSettingsPreservingSecrets(
  local: AIProviderSettings,
  cloud: Partial<AIProviderSettings>,
): AIProviderSettings {
  const cloudProviders = cloud.providers;
  return {
    activeProvider:
      cloud.activeProvider !== undefined
        ? cloud.activeProvider
        : local.activeProvider,
    agentModels:
      cloud.agentModels !== undefined ? cloud.agentModels : local.agentModels,
    providers: {
      openrouter: mergeProviderConfig(
        local.providers.openrouter,
        cloudProviders?.openrouter,
      ),
      generalcompute: mergeProviderConfig(
        local.providers.generalcompute,
        cloudProviders?.generalcompute,
      ),
    },
  };
}

function mergeWebSearchProvider(
  local: WebSearchProviderConfig,
  cloud?: Partial<WebSearchProviderConfig>,
): WebSearchProviderConfig {
  if (!cloud || typeof cloud !== 'object') return local;
  return {
    ...local,
    ...cloud,
    apiKey: pickSecret(cloud.apiKey, local.apiKey),
  };
}

/** Deep-merge web search; keep local keys when cloud secret empty. */
export function mergeWebSearchSettingsPreservingSecrets(
  local: WebSearchSettings,
  cloud: Partial<WebSearchSettings>,
): WebSearchSettings {
  const cloudProviders = cloud.providers;
  const providers = { ...local.providers };
  for (const id of WEB_SEARCH_PROVIDER_IDS) {
    providers[id] = mergeWebSearchProvider(
      local.providers[id],
      cloudProviders?.[id],
    );
  }
  return {
    masterEnabled:
      typeof cloud.masterEnabled === 'boolean'
        ? cloud.masterEnabled
        : local.masterEnabled,
    providers,
  };
}

async function applyCloudSnapshotAndSync(): Promise<void> {
  const snapshot = await getAppSettings();
  const localProvider = getProviderSettings();
  const localWebSearch = getWebSearchSettings();

  const cloudProvider = snapshot.providerSettings;
  const cloudWebSearch = snapshot.webSearchSettings;
  const providerReady = hasProviderShape(cloudProvider);
  const webReady = hasWebSearchShape(cloudWebSearch);

  if (!providerReady && !webReady) {
    await putAppSettings({
      providerSettings: localProvider,
      webSearchSettings: localWebSearch,
    });
  } else {
    if (providerReady) {
      setProviderSettings(
        mergeProviderSettingsPreservingSecrets(localProvider, cloudProvider),
      );
    }
    if (webReady) {
      setWebSearchSettings(
        mergeWebSearchSettingsPreservingSecrets(localWebSearch, cloudWebSearch),
      );
    }
  }

  window.dispatchEvent(new Event(APP_SETTINGS_HYDRATED_EVENT));
  startCloudSettingsSync();
}

export async function hydrateAndEnableCloudSettings(): Promise<void> {
  await applyCloudSnapshotAndSync();
}

export function disableCloudSettingsSync(): void {
  stopCloudSettingsSync();
}

function startCloudSettingsSync(): void {
  stopCloudSettingsSync();
  let queue = Promise.resolve();
  const listener = () => {
    const snapshot: AppSettingsSnapshot = {
      providerSettings: getProviderSettings(),
      webSearchSettings: getWebSearchSettings(),
    };
    queue = queue
      .then(async () => {
        await putAppSettings(snapshot);
      })
      .catch(() => undefined);
  };
  window.addEventListener(APP_SETTINGS_CHANGED_EVENT, listener);
  stopCloudSync = () => {
    window.removeEventListener(APP_SETTINGS_CHANGED_EVENT, listener);
    stopCloudSync = null;
  };
}

function stopCloudSettingsSync(): void {
  if (stopCloudSync) stopCloudSync();
}

export function resetStorageBootForTests(): void {
  bootPromise = null;
  stopCloudSettingsSync();
}
