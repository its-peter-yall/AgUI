/**
 * ============================================================================
 * FILE: storageBoot.test.ts
 * LOCATION: client/src/lib/storageBoot.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Unit tests for one-shot storage boot connect and hydration flow.
 *
 * ROLE IN PROJECT:
 *    Guards connect-once, cloud skip, failure tolerance, and hydrate order.
 *
 * KEY COMPONENTS:
 *    - bootstrapStorage singleton and path tests
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: storageBoot (mocked deps)
 *
 * USAGE:
 *    npm run test -- --run src/lib/storageBoot.test.ts
 * ============================================================================
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const getStorageStatusMock = vi.fn();
const connectStorageMock = vi.fn();
const getAppSettingsMock = vi.fn();
const putAppSettingsMock = vi.fn();
const getMongoStorageSettingsMock = vi.fn();
const setProviderSettingsMock = vi.fn();
const setWebSearchSettingsMock = vi.fn();
const getProviderSettingsMock = vi.fn();
const getWebSearchSettingsMock = vi.fn();

vi.mock('@/lib/storageApi', () => ({
  getStorageStatus: (...args: unknown[]) => getStorageStatusMock(...args),
  connectStorage: (...args: unknown[]) => connectStorageMock(...args),
  getAppSettings: (...args: unknown[]) => getAppSettingsMock(...args),
  putAppSettings: (...args: unknown[]) => putAppSettingsMock(...args),
}));

vi.mock('@/lib/mongoStorageSettings', () => ({
  getMongoStorageSettings: (...args: unknown[]) =>
    getMongoStorageSettingsMock(...args),
}));

vi.mock('@/lib/providerSettings', () => ({
  APP_SETTINGS_CHANGED_EVENT: 'a2ui-app-settings-changed',
  APP_SETTINGS_HYDRATED_EVENT: 'a2ui-app-settings-hydrated',
  setProviderSettings: (...args: unknown[]) => setProviderSettingsMock(...args),
  setWebSearchSettings: (...args: unknown[]) =>
    setWebSearchSettingsMock(...args),
  getProviderSettings: (...args: unknown[]) => getProviderSettingsMock(...args),
  getWebSearchSettings: (...args: unknown[]) =>
    getWebSearchSettingsMock(...args),
}));

import {
  bootstrapStorage,
  resetStorageBootForTests,
} from '@/lib/storageBoot';
import type { StorageStatus } from '@/types/storage';

const localStatus: StorageStatus = {
  deploymentMode: 'local',
  activeBackend: 'sqlite',
  connected: false,
  mongoDbName: null,
  canConnect: true,
  canDisconnect: false,
  canMigrate: false,
  localDataPresent: true,
};

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

const cloudStatus: StorageStatus = {
  deploymentMode: 'cloud',
  activeBackend: 'mongo',
  connected: true,
  mongoDbName: 'a2ui',
  canConnect: false,
  canDisconnect: false,
  canMigrate: false,
  localDataPresent: false,
};

const connection = {
  uri: 'mongodb://host',
  dbName: 'a2ui',
};

const cloudSnapshot = {
  providerSettings: {
    activeProvider: 'openrouter' as const,
    providers: {
      openrouter: {
        apiKey: 'cloud-key',
        model: 'm',
        modelTitle: 'M',
      },
      generalcompute: {
        apiKey: '',
        model: '',
        modelTitle: '',
      },
    },
  },
  webSearchSettings: {
    masterEnabled: true,
    providers: {
      tavily: { apiKey: 't', enabled: true },
      exa: { apiKey: '', enabled: false },
      brave: { apiKey: '', enabled: false },
      serpapi: { apiKey: '', enabled: false },
    },
  },
};

describe('bootstrapStorage', () => {
  beforeEach(() => {
    resetStorageBootForTests();
    getStorageStatusMock.mockReset();
    connectStorageMock.mockReset();
    getAppSettingsMock.mockReset();
    putAppSettingsMock.mockReset();
    getMongoStorageSettingsMock.mockReset();
    setProviderSettingsMock.mockReset();
    setWebSearchSettingsMock.mockReset();
    getProviderSettingsMock.mockReset();
    getWebSearchSettingsMock.mockReset();
    getProviderSettingsMock.mockReturnValue(cloudSnapshot.providerSettings);
    getWebSearchSettingsMock.mockReturnValue(cloudSnapshot.webSearchSettings);
    putAppSettingsMock.mockResolvedValue(cloudSnapshot);
  });

  it('connects once then hydrates when local credentials exist', async () => {
    getStorageStatusMock.mockResolvedValue(localStatus);
    getMongoStorageSettingsMock.mockReturnValue(connection);
    connectStorageMock.mockResolvedValue(mongoStatus);
    getAppSettingsMock.mockResolvedValue(cloudSnapshot);

    const first = bootstrapStorage();
    const second = bootstrapStorage();
    await Promise.all([first, second]);

    expect(first).toBe(second);
    expect(connectStorageMock).toHaveBeenCalledTimes(1);
    expect(connectStorageMock).toHaveBeenCalledWith(connection);
    expect(setProviderSettingsMock).toHaveBeenCalledWith(
      cloudSnapshot.providerSettings,
    );
    expect(setWebSearchSettingsMock).toHaveBeenCalledWith(
      cloudSnapshot.webSearchSettings,
    );
  });

  it('does not post connect in cloud deployment', async () => {
    getStorageStatusMock.mockResolvedValue(cloudStatus);
    getAppSettingsMock.mockResolvedValue(cloudSnapshot);
    await bootstrapStorage();
    expect(connectStorageMock).not.toHaveBeenCalled();
    expect(getAppSettingsMock).toHaveBeenCalledTimes(1);
  });

  it('continues boot when status request fails', async () => {
    getStorageStatusMock.mockRejectedValue(new Error('offline'));
    await expect(bootstrapStorage()).resolves.toEqual(
      expect.objectContaining({ error: expect.any(String) }),
    );
  });
});
