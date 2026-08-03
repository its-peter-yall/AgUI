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
  hydrateAndEnableCloudSettings,
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
    const consoleError = vi
      .spyOn(console, 'error')
      .mockImplementation(() => undefined);
    getStorageStatusMock.mockRejectedValue(new Error('offline'));
    await expect(bootstrapStorage()).resolves.toEqual(
      expect.objectContaining({ error: expect.any(String) }),
    );
    consoleError.mockRestore();
  });

  it('logs boot failure once when status request fails', async () => {
    const consoleError = vi
      .spyOn(console, 'error')
      .mockImplementation(() => undefined);
    getStorageStatusMock.mockRejectedValue(new Error('offline'));
    await bootstrapStorage();
    expect(consoleError).toHaveBeenCalledWith(
      expect.stringContaining('Storage boot failed'),
      expect.anything(),
    );
    consoleError.mockRestore();
  });
});

describe('hydrateAndEnableCloudSettings secret safety', () => {
  const localProvider = {
    activeProvider: 'openrouter' as const,
    providers: {
      openrouter: {
        apiKey: 'local-or-key',
        model: 'local-model',
        modelTitle: 'Local',
      },
      generalcompute: {
        apiKey: 'local-gc-key',
        model: '',
        modelTitle: '',
      },
    },
  };

  const localWebSearch = {
    masterEnabled: true,
    providers: {
      tavily: { apiKey: 'local-tavily', enabled: true },
      exa: { apiKey: 'local-exa', enabled: false },
      brave: { apiKey: '', enabled: false },
      serpapi: { apiKey: '', enabled: false },
    },
  };

  beforeEach(() => {
    resetStorageBootForTests();
    getAppSettingsMock.mockReset();
    putAppSettingsMock.mockReset();
    setProviderSettingsMock.mockReset();
    setWebSearchSettingsMock.mockReset();
    getProviderSettingsMock.mockReset();
    getWebSearchSettingsMock.mockReset();
    getProviderSettingsMock.mockReturnValue(localProvider);
    getWebSearchSettingsMock.mockReturnValue(localWebSearch);
    putAppSettingsMock.mockResolvedValue({
      providerSettings: localProvider,
      webSearchSettings: localWebSearch,
    });
  });

  it('pushes local snapshot when cloud settings are null', async () => {
    getAppSettingsMock.mockResolvedValue({
      providerSettings: null,
      webSearchSettings: null,
    });

    await hydrateAndEnableCloudSettings();

    expect(setProviderSettingsMock).not.toHaveBeenCalled();
    expect(setWebSearchSettingsMock).not.toHaveBeenCalled();
    expect(putAppSettingsMock).toHaveBeenCalledWith({
      providerSettings: localProvider,
      webSearchSettings: localWebSearch,
    });
  });

  it('does not wipe local secrets when cloud secrets are empty strings', async () => {
    getAppSettingsMock.mockResolvedValue({
      providerSettings: {
        activeProvider: 'openrouter' as const,
        providers: {
          openrouter: {
            apiKey: '',
            model: 'cloud-model',
            modelTitle: 'Cloud',
          },
          generalcompute: {
            apiKey: '',
            model: '',
            modelTitle: '',
          },
        },
      },
      webSearchSettings: {
        masterEnabled: false,
        providers: {
          tavily: { apiKey: '', enabled: false },
          exa: { apiKey: '', enabled: false },
          brave: { apiKey: '', enabled: false },
          serpapi: { apiKey: '', enabled: false },
        },
      },
    });

    await hydrateAndEnableCloudSettings();

    expect(setProviderSettingsMock).toHaveBeenCalledWith(
      expect.objectContaining({
        providers: expect.objectContaining({
          openrouter: expect.objectContaining({
            apiKey: 'local-or-key',
            model: 'cloud-model',
          }),
          generalcompute: expect.objectContaining({
            apiKey: 'local-gc-key',
          }),
        }),
      }),
    );
    expect(setWebSearchSettingsMock).toHaveBeenCalledWith(
      expect.objectContaining({
        providers: expect.objectContaining({
          tavily: expect.objectContaining({ apiKey: 'local-tavily' }),
          exa: expect.objectContaining({ apiKey: 'local-exa' }),
        }),
      }),
    );
  });

  it('skips hydrate wipe when cloud provider payload is empty object', async () => {
    getAppSettingsMock.mockResolvedValue({
      providerSettings: {} as never,
      webSearchSettings: {} as never,
    });

    await hydrateAndEnableCloudSettings();

    const providerArg = setProviderSettingsMock.mock.calls[0]?.[0] as
      | { providers?: { openrouter?: { apiKey?: string } } }
      | undefined;
    if (providerArg?.providers?.openrouter) {
      expect(providerArg.providers.openrouter.apiKey).not.toBe('');
    }
    const webArg = setWebSearchSettingsMock.mock.calls[0]?.[0] as
      | { providers?: { tavily?: { apiKey?: string } } }
      | undefined;
    if (webArg?.providers?.tavily) {
      expect(webArg.providers.tavily.apiKey).not.toBe('');
    }
  });

  it('applies non-empty cloud secrets over local', async () => {
    getAppSettingsMock.mockResolvedValue(cloudSnapshot);

    await hydrateAndEnableCloudSettings();

    expect(setProviderSettingsMock).toHaveBeenCalledWith(
      expect.objectContaining({
        providers: expect.objectContaining({
          openrouter: expect.objectContaining({
            apiKey: 'cloud-key',
          }),
        }),
      }),
    );
    expect(setWebSearchSettingsMock).toHaveBeenCalledWith(
      expect.objectContaining({
        providers: expect.objectContaining({
          tavily: expect.objectContaining({ apiKey: 't' }),
        }),
      }),
    );
  });
});
