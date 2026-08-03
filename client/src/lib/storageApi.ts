/**
 * ============================================================================
 * FILE: storageApi.ts
 * LOCATION: client/src/lib/storageApi.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Typed Axios client for storage lifecycle and cloud app-settings APIs.
 *
 * ROLE IN PROJECT:
 *    Single HTTP surface for status, connect, disconnect, migrate, and
 *    app-settings read/write used by boot and Settings UI.
 *
 * KEY COMPONENTS:
 *    - getStorageStatus / connectStorage / disconnectStorage
 *    - migrateStorage / getAppSettings / putAppSettings
 *    - Per-call timeouts (migrate/connect heavier than status)
 *
 * DEPENDENCIES:
 *    - External: axios
 *    - Internal: mongoStorageSettings, providerSettings, storage types, webSearch
 *
 * USAGE:
 *    const status = await getStorageStatus();
 * ============================================================================
 */

import axios from 'axios';

import type { MongoStorageSettings } from '@/lib/mongoStorageSettings';
import type { AIProviderSettings } from '@/lib/providerSettings';
import type {
  AppSettingsSnapshot,
  StorageMigrationResult,
  StorageStatus,
} from '@/types/storage';
import type { WebSearchSettings } from '@/types/webSearch';

/** Default for status / app-settings / disconnect. */
export const STORAGE_DEFAULT_TIMEOUT_MS = 10_000;
/** Connect needs headroom for Atlas server selection. */
export const STORAGE_CONNECT_TIMEOUT_MS = 15_000;
/** Migrate copies tables + checkpoints; real DBs exceed 10s. */
export const STORAGE_MIGRATE_TIMEOUT_MS = 300_000;

const storageApi = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  timeout: STORAGE_DEFAULT_TIMEOUT_MS,
});

export async function getStorageStatus(): Promise<StorageStatus> {
  const response = await storageApi.get<StorageStatus>(
    '/settings/storage/status',
  );
  return response.data;
}

export async function connectStorage(
  settings: MongoStorageSettings,
): Promise<StorageStatus> {
  const response = await storageApi.post<StorageStatus>(
    '/settings/storage/connect',
    settings,
    { timeout: STORAGE_CONNECT_TIMEOUT_MS },
  );
  return response.data;
}

export async function disconnectStorage(): Promise<StorageStatus> {
  const response = await storageApi.post<StorageStatus>(
    '/settings/storage/disconnect',
  );
  return response.data;
}

export async function migrateStorage(
  providerSettings: AIProviderSettings,
  webSearchSettings: WebSearchSettings,
): Promise<StorageMigrationResult> {
  const response = await storageApi.post<StorageMigrationResult>(
    '/settings/storage/migrate',
    { providerSettings, webSearchSettings },
    { timeout: STORAGE_MIGRATE_TIMEOUT_MS },
  );
  return response.data;
}

export async function getAppSettings(): Promise<AppSettingsSnapshot> {
  const response = await storageApi.get<AppSettingsSnapshot>(
    '/settings/storage/app-settings',
  );
  return response.data;
}

export async function putAppSettings(
  snapshot: AppSettingsSnapshot,
): Promise<AppSettingsSnapshot> {
  const response = await storageApi.put<AppSettingsSnapshot>(
    '/settings/storage/app-settings',
    snapshot,
  );
  return response.data;
}
