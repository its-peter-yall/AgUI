/**
 * ============================================================================
 * FILE: StorageSettingsPanel.test.tsx
 * LOCATION: client/src/features/settings/StorageSettingsPanel.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Component tests for Atlas storage settings local/cloud controls.
 *
 * ROLE IN PROJECT:
 *    Guards rendering modes, action enablement, and connect/migrate flows.
 *
 * KEY COMPONENTS:
 *    - Local/cloud render tests
 *    - Save/connect/disconnect/migrate interaction tests
 *
 * DEPENDENCIES:
 *    - External: @testing-library/react, vitest, axios
 *    - Internal: StorageSettingsPanel
 *
 * USAGE:
 *    npm run test -- --run src/features/settings/StorageSettingsPanel.test.tsx
 * ============================================================================
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import axios, { type AxiosError } from 'axios';

const getStorageStatusMock = vi.fn();
const connectStorageMock = vi.fn();
const disconnectStorageMock = vi.fn();
const migrateStorageMock = vi.fn();
const getMongoStorageSettingsMock = vi.fn();
const setMongoStorageSettingsMock = vi.fn();
const hydrateAndEnableCloudSettingsMock = vi.fn();
const disableCloudSettingsSyncMock = vi.fn();
const getProviderSettingsMock = vi.fn();
const getWebSearchSettingsMock = vi.fn();

vi.mock('@/lib/storageApi', () => ({
  getStorageStatus: (...args: unknown[]) => getStorageStatusMock(...args),
  connectStorage: (...args: unknown[]) => connectStorageMock(...args),
  disconnectStorage: (...args: unknown[]) => disconnectStorageMock(...args),
  migrateStorage: (...args: unknown[]) => migrateStorageMock(...args),
}));

vi.mock('@/lib/mongoStorageSettings', () => ({
  getMongoStorageSettings: (...args: unknown[]) =>
    getMongoStorageSettingsMock(...args),
  setMongoStorageSettings: (...args: unknown[]) =>
    setMongoStorageSettingsMock(...args),
}));

vi.mock('@/lib/storageBoot', () => ({
  hydrateAndEnableCloudSettings: (...args: unknown[]) =>
    hydrateAndEnableCloudSettingsMock(...args),
  disableCloudSettingsSync: (...args: unknown[]) =>
    disableCloudSettingsSyncMock(...args),
}));

vi.mock('@/lib/providerSettings', () => ({
  getProviderSettings: (...args: unknown[]) => getProviderSettingsMock(...args),
  getWebSearchSettings: (...args: unknown[]) =>
    getWebSearchSettingsMock(...args),
}));

import { StorageSettingsPanel } from './StorageSettingsPanel';
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

const connectedStatus: StorageStatus = {
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
  mongoDbName: 'prod',
  canConnect: false,
  canDisconnect: false,
  canMigrate: false,
  localDataPresent: false,
};

const providerSettings = {
  activeProvider: 'openrouter' as const,
  providers: {
    openrouter: { apiKey: 'k', model: 'm', modelTitle: 'M' },
    generalcompute: { apiKey: '', model: '', modelTitle: '' },
  },
};

const webSearchSettings = {
  masterEnabled: false,
  providers: {
    tavily: { apiKey: '', enabled: false },
    exa: { apiKey: '', enabled: false },
    brave: { apiKey: '', enabled: false },
    serpapi: { apiKey: '', enabled: false },
  },
};

describe('StorageSettingsPanel', () => {
  beforeEach(() => {
    getStorageStatusMock.mockReset();
    connectStorageMock.mockReset();
    disconnectStorageMock.mockReset();
    migrateStorageMock.mockReset();
    getMongoStorageSettingsMock.mockReset();
    setMongoStorageSettingsMock.mockReset();
    hydrateAndEnableCloudSettingsMock.mockReset();
    disableCloudSettingsSyncMock.mockReset();
    getProviderSettingsMock.mockReset();
    getWebSearchSettingsMock.mockReset();
    getMongoStorageSettingsMock.mockReturnValue(null);
    getProviderSettingsMock.mockReturnValue(providerSettings);
    getWebSearchSettingsMock.mockReturnValue(webSearchSettings);
    hydrateAndEnableCloudSettingsMock.mockResolvedValue(undefined);
  });

  it('renders local connection controls and status', async () => {
    getStorageStatusMock.mockResolvedValue(localStatus);
    render(<StorageSettingsPanel />);
    expect(await screen.findByText('Local SQLite')).toBeInTheDocument();
    expect(screen.getByLabelText('MongoDB URI')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Connect' })).toBeEnabled();
  });

  it('renders cloud status without secret or mutation controls', async () => {
    getStorageStatusMock.mockResolvedValue(cloudStatus);
    render(<StorageSettingsPanel />);
    expect(await screen.findByText('Cloud storage')).toBeInTheDocument();
    expect(screen.queryByLabelText('MongoDB URI')).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Disconnect' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Migrate/ }),
    ).not.toBeInTheDocument();
  });

  it('disables migrate until connected with local data', async () => {
    getStorageStatusMock.mockResolvedValue(localStatus);
    render(<StorageSettingsPanel />);
    expect(
      await screen.findByRole('button', { name: 'Migrate local data' }),
    ).toBeDisabled();
  });

  it('saves connection details to the browser helper', async () => {
    getStorageStatusMock.mockResolvedValue(localStatus);
    render(<StorageSettingsPanel />);
    await screen.findByText('Local SQLite');
    fireEvent.change(screen.getByLabelText('MongoDB URI'), {
      target: { value: 'mongodb://host/db' },
    });
    fireEvent.change(screen.getByLabelText('Database name'), {
      target: { value: 'a2ui' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save connection' }));
    expect(setMongoStorageSettingsMock).toHaveBeenCalledWith({
      uri: 'mongodb://host/db',
      dbName: 'a2ui',
    });
  });

  it('connects, persists credentials after success, and hydrates', async () => {
    getStorageStatusMock.mockResolvedValue(localStatus);
    connectStorageMock.mockResolvedValue(connectedStatus);
    render(<StorageSettingsPanel />);
    await screen.findByText('Local SQLite');
    fireEvent.change(screen.getByLabelText('MongoDB URI'), {
      target: { value: 'mongodb://host' },
    });
    fireEvent.change(screen.getByLabelText('Database name'), {
      target: { value: 'a2ui' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
    await waitFor(() => {
      expect(connectStorageMock).toHaveBeenCalledWith({
        uri: 'mongodb://host',
        dbName: 'a2ui',
      });
    });
    expect(setMongoStorageSettingsMock).toHaveBeenCalledWith({
      uri: 'mongodb://host',
      dbName: 'a2ui',
    });
    expect(hydrateAndEnableCloudSettingsMock).toHaveBeenCalledTimes(1);
    expect(await screen.findByText('MongoDB · a2ui')).toBeInTheDocument();
  });

  it('disconnects and stops sync without clearing saved URI', async () => {
    getMongoStorageSettingsMock.mockReturnValue({
      uri: 'mongodb://host',
      dbName: 'a2ui',
    });
    getStorageStatusMock.mockResolvedValue(connectedStatus);
    disconnectStorageMock.mockResolvedValue(localStatus);
    render(<StorageSettingsPanel />);
    fireEvent.click(
      await screen.findByRole('button', { name: 'Disconnect' }),
    );
    await waitFor(() => {
      expect(disconnectStorageMock).toHaveBeenCalledTimes(1);
    });
    expect(disableCloudSettingsSyncMock).toHaveBeenCalledTimes(1);
    expect(setMongoStorageSettingsMock).not.toHaveBeenCalled();
  });

  it('migrates current snapshots and renders counts and warnings', async () => {
    getStorageStatusMock
      .mockResolvedValueOnce(connectedStatus)
      .mockResolvedValue(connectedStatus);
    migrateStorageMock.mockResolvedValue({
      collections: {
        learning_sessions: {
          rows: 4,
          matched: 1,
          upserted: 3,
          modified: 0,
        },
      },
      checkpoints: 2,
      checkpointWrites: 5,
      warnings: ['checkpoint already present'],
    });
    render(<StorageSettingsPanel />);
    const migrate = await screen.findByRole('button', {
      name: 'Migrate local data',
    });
    expect(migrate).toBeEnabled();
    fireEvent.click(migrate);
    await waitFor(() => {
      expect(migrateStorageMock).toHaveBeenCalledWith(
        providerSettings,
        webSearchSettings,
      );
    });
    expect(await screen.findByText(/learning_sessions/)).toBeInTheDocument();
    expect(screen.getByText(/checkpoint already present/)).toBeInTheDocument();
  });

  it('maps 409 conflict detail to cancel-or-wait guidance', async () => {
    getStorageStatusMock.mockResolvedValue(connectedStatus);
    disconnectStorageMock.mockRejectedValue(
      Object.assign(new Error('conflict'), {
        isAxiosError: true,
        response: {
          status: 409,
          data: {
            detail: {
              code: 'storage_switch_requires_idle_jobs',
              message:
                'Cancel or wait for active generation before switching storage',
              sessionIds: ['s1', 's2'],
            },
          },
        },
      }),
    );
    vi.spyOn(axios, 'isAxiosError').mockImplementation(
      (error: unknown): error is AxiosError =>
        Boolean(
          error &&
            typeof error === 'object' &&
            'isAxiosError' in error &&
            (error as { isAxiosError?: boolean }).isAxiosError,
        ),
    );
    render(<StorageSettingsPanel />);
    fireEvent.click(
      await screen.findByRole('button', { name: 'Disconnect' }),
    );
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /Cancel or wait/,
    );
    expect(screen.getByRole('alert')).toHaveTextContent(/s1/);
  });
});
