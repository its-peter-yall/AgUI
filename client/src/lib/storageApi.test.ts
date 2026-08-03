/**
 * ============================================================================
 * FILE: storageApi.test.ts
 * LOCATION: client/src/lib/storageApi.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Unit tests for storage REST client path and payload contracts.
 *
 * ROLE IN PROJECT:
 *    Guards connect/migrate/status/app-settings HTTP shapes against drift.
 *
 * KEY COMPONENTS:
 *    - Path and body assertions for storage endpoints
 *
 * DEPENDENCIES:
 *    - External: vitest, axios
 *    - Internal: storageApi
 *
 * USAGE:
 *    npm run test -- --run src/lib/storageApi.test.ts
 * ============================================================================
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => {
  const instance = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  };
  return { instance };
});

vi.mock('axios', () => ({
  default: {
    create: () => mocks.instance,
    isAxiosError: () => false,
  },
}));

import {
  connectStorage,
  disconnectStorage,
  getAppSettings,
  getStorageStatus,
  migrateStorage,
  putAppSettings,
} from './storageApi';
import type {
  AppSettingsSnapshot,
  StorageMigrationResult,
  StorageStatus,
} from '@/types/storage';
import type { AIProviderSettings } from '@/lib/providerSettings';
import type { WebSearchSettings } from '@/types/webSearch';

const mongoStatus: StorageStatus = {
  deploymentMode: 'local',
  activeBackend: 'mongo',
  connected: true,
  mongoDbName: 'a2ui',
  canConnect: true,
  canDisconnect: true,
  canMigrate: true,
  localDataPresent: true,
};

const migrationResult: StorageMigrationResult = {
  collections: {
    learning_sessions: {
      rows: 1,
      matched: 0,
      upserted: 1,
      modified: 0,
    },
  },
  checkpoints: 2,
  checkpointWrites: 3,
  warnings: [],
};

const providerSettings = {
  activeProvider: 'openrouter',
  providers: {
    openrouter: {
      apiKey: 'k',
      model: 'm',
      modelTitle: 'M',
    },
    generalcompute: {
      apiKey: '',
      model: '',
      modelTitle: '',
    },
  },
} as AIProviderSettings;

const webSearchSettings: WebSearchSettings = {
  masterEnabled: false,
  providers: {
    tavily: { apiKey: '', enabled: false },
    exa: { apiKey: '', enabled: false },
    brave: { apiKey: '', enabled: false },
    serpapi: { apiKey: '', enabled: false },
  },
};

describe('storageApi', () => {
  beforeEach(() => {
    mocks.instance.get.mockReset();
    mocks.instance.post.mockReset();
    mocks.instance.put.mockReset();
  });

  it('gets storage status', async () => {
    mocks.instance.get.mockResolvedValue({ data: mongoStatus });
    await expect(getStorageStatus()).resolves.toEqual(mongoStatus);
    expect(mocks.instance.get).toHaveBeenCalledWith('/settings/storage/status');
  });

  it('posts Mongo credentials only to connect', async () => {
    mocks.instance.post.mockResolvedValue({ data: mongoStatus });
    await connectStorage({ uri: 'mongodb://host', dbName: 'a2ui' });
    expect(mocks.instance.post).toHaveBeenCalledWith(
      '/settings/storage/connect',
      { uri: 'mongodb://host', dbName: 'a2ui' },
      { timeout: 15_000 },
    );
  });

  it('posts disconnect without a body', async () => {
    mocks.instance.post.mockResolvedValue({ data: mongoStatus });
    await disconnectStorage();
    expect(mocks.instance.post).toHaveBeenCalledWith(
      '/settings/storage/disconnect',
    );
  });

  it('sends complete browser snapshots to migrate', async () => {
    mocks.instance.post.mockResolvedValue({ data: migrationResult });
    await migrateStorage(providerSettings, webSearchSettings);
    expect(mocks.instance.post).toHaveBeenCalledWith(
      '/settings/storage/migrate',
      { providerSettings, webSearchSettings },
      { timeout: 300_000 },
    );
  });

  it('uses extended timeout for migrate requests', async () => {
    mocks.instance.post.mockResolvedValue({ data: migrationResult });
    await migrateStorage(providerSettings, webSearchSettings);
    const config = mocks.instance.post.mock.calls[0]?.[2] as {
      timeout?: number;
    };
    expect(config.timeout).toBeGreaterThanOrEqual(120_000);
    expect(config.timeout).toBeLessThanOrEqual(300_000);
  });

  it('gets app settings snapshot with default timeout', async () => {
    const snapshot: AppSettingsSnapshot = {
      providerSettings,
      webSearchSettings,
    };
    mocks.instance.get.mockResolvedValue({ data: snapshot });
    await expect(getAppSettings()).resolves.toEqual(snapshot);
    expect(mocks.instance.get).toHaveBeenCalledWith(
      '/settings/storage/app-settings',
    );
  });

  it('puts complete app settings snapshot', async () => {
    const snapshot: AppSettingsSnapshot = {
      providerSettings,
      webSearchSettings,
    };
    mocks.instance.put.mockResolvedValue({ data: snapshot });
    await putAppSettings(snapshot);
    expect(mocks.instance.put).toHaveBeenCalledWith(
      '/settings/storage/app-settings',
      snapshot,
    );
  });
});
