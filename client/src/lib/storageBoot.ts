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
 *
 * KEY COMPONENTS:
 *    - bootstrapStorage: singleton boot promise
 *    - hydrateAndEnableCloudSettings: Settings connect path
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
} from '@/lib/providerSettings';
import {
  connectStorage,
  getAppSettings,
  getStorageStatus,
  putAppSettings,
} from '@/lib/storageApi';
import type { StorageStatus } from '@/types/storage';

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
    return { status: null, error: message };
  }
}

async function applyCloudSnapshotAndSync(): Promise<void> {
  const snapshot = await getAppSettings();
  if (snapshot.providerSettings) {
    setProviderSettings(snapshot.providerSettings);
  }
  if (snapshot.webSearchSettings) {
    setWebSearchSettings(snapshot.webSearchSettings);
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
    const snapshot = {
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
