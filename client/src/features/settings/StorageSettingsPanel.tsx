/**
 * ============================================================================
 * FILE: StorageSettingsPanel.tsx
 * LOCATION: client/src/features/settings/StorageSettingsPanel.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Settings controls for local Atlas connect/disconnect/migrate and cloud status.
 *
 * ROLE IN PROJECT:
 *    Lets local users manage Mongo storage from Settings; cloud deployments show
 *    read-only status without secret inputs or mutation controls.
 *
 * KEY COMPONENTS:
 *    - StorageSettingsPanel: status rail, fields, actions, migration result
 *
 * DEPENDENCIES:
 *    - External: react, axios, lucide-react
 *    - Internal: storageApi, storageBoot, mongoStorageSettings, providerSettings
 *
 * USAGE:
 *    import { StorageSettingsPanel } from './StorageSettingsPanel';
 *    <StorageSettingsPanel />
 * ============================================================================
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { Loader2 } from 'lucide-react';

import {
  getMongoStorageSettings,
  setMongoStorageSettings,
} from '@/lib/mongoStorageSettings';
import {
  getProviderSettings,
  getWebSearchSettings,
} from '@/lib/providerSettings';
import {
  connectStorage,
  disconnectStorage,
  getStorageStatus,
  migrateStorage,
} from '@/lib/storageApi';
import {
  disableCloudSettingsSync,
  hydrateAndEnableCloudSettings,
} from '@/lib/storageBoot';
import type {
  StorageMigrationResult,
  StorageStatus,
} from '@/types/storage';
import { cn } from '@/lib/utils';

function statusLabel(status: StorageStatus | null): string {
  if (!status) return 'Checking storage…';
  if (status.deploymentMode === 'cloud') return 'Cloud storage';
  if (status.connected && status.activeBackend === 'mongo') {
    return status.mongoDbName
      ? `MongoDB · ${status.mongoDbName}`
      : 'MongoDB';
  }
  return 'Local SQLite';
}

function mapStorageError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status;
    const detail = error.response?.data?.detail;
    if (status === 409 && detail && typeof detail === 'object') {
      const payload = detail as {
        message?: string;
        sessionIds?: string[];
      };
      const sessions = Array.isArray(payload.sessionIds)
        ? payload.sessionIds.filter((id) => typeof id === 'string')
        : [];
      const base =
        typeof payload.message === 'string' && payload.message.trim()
          ? payload.message
          : 'Cancel or wait for active generation before switching storage';
      if (sessions.length > 0) {
        return `${base} Active sessions: ${sessions.join(', ')}.`;
      }
      return base;
    }
    if (typeof detail === 'string' && detail.trim()) {
      return detail;
    }
    if (status === 403) {
      return 'Storage is managed by the deployment environment.';
    }
    if (status === 400) {
      return 'MongoDB connection is invalid or unauthorized. Check URI and database name.';
    }
    if (status === 503) {
      return 'MongoDB is unreachable. Check network and Atlas access.';
    }
    if (error.message) return error.message;
  }
  if (error instanceof Error && error.message) return error.message;
  return 'Storage action failed. Try again.';
}

export function StorageSettingsPanel() {
  const saved = getMongoStorageSettings();
  const [uri, setUri] = useState(saved?.uri ?? '');
  const [dbName, setDbName] = useState(saved?.dbName ?? 'a2ui');
  const [status, setStatus] = useState<StorageStatus | null>(null);
  const [pendingAction, setPendingAction] = useState<
    'connect' | 'disconnect' | 'migrate' | null
  >(null);
  const [error, setError] = useState<string | null>(null);
  const [migration, setMigration] =
    useState<StorageMigrationResult | null>(null);
  const [saveNotice, setSaveNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const next = await getStorageStatus();
        if (!cancelled) setStatus(next);
      } catch (err: unknown) {
        if (!cancelled) setError(mapStorageError(err));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const isCloud = status?.deploymentMode === 'cloud';
  const isLocal = !isCloud;
  const busy = pendingAction !== null;

  const statusBadgeClass = useMemo(() => {
    const base =
      'inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium border';
    if (!status) {
      return cn(base, 'border-border text-muted-foreground');
    }
    if (status.connected && status.activeBackend === 'mongo') {
      return cn(
        base,
        'border-[#ffb74d]/40 bg-[#ffb74d]/10 text-[#ffb74d]',
      );
    }
    return cn(base, 'border-border bg-muted/40 text-muted-foreground');
  }, [status]);

  const handleSave = useCallback(() => {
    setError(null);
    setSaveNotice(null);
    const trimmedUri = uri.trim();
    const trimmedDb = dbName.trim();
    if (!trimmedUri || !trimmedDb) {
      setError('Enter both MongoDB URI and database name before saving.');
      return;
    }
    setMongoStorageSettings({ uri: trimmedUri, dbName: trimmedDb });
    setSaveNotice('Connection saved in this browser.');
  }, [uri, dbName]);

  const handleConnect = useCallback(async () => {
    setError(null);
    setSaveNotice(null);
    setMigration(null);
    const trimmedUri = uri.trim();
    const trimmedDb = dbName.trim();
    if (!trimmedUri || !trimmedDb) {
      setError('Enter both MongoDB URI and database name before connecting.');
      return;
    }
    setPendingAction('connect');
    try {
      const next = await connectStorage({
        uri: trimmedUri,
        dbName: trimmedDb,
      });
      setMongoStorageSettings({ uri: trimmedUri, dbName: trimmedDb });
      setStatus(next);
      await hydrateAndEnableCloudSettings();
    } catch (err: unknown) {
      setError(mapStorageError(err));
    } finally {
      setPendingAction(null);
    }
  }, [uri, dbName]);

  const handleDisconnect = useCallback(async () => {
    setError(null);
    setSaveNotice(null);
    setMigration(null);
    setPendingAction('disconnect');
    try {
      const next = await disconnectStorage();
      disableCloudSettingsSync();
      setStatus(next);
    } catch (err: unknown) {
      setError(mapStorageError(err));
    } finally {
      setPendingAction(null);
    }
  }, []);

  const handleMigrate = useCallback(async () => {
    setError(null);
    setSaveNotice(null);
    setPendingAction('migrate');
    try {
      const result = await migrateStorage(
        getProviderSettings(),
        getWebSearchSettings(),
      );
      setMigration(result);
      setStatus(await getStorageStatus());
    } catch (err: unknown) {
      setError(mapStorageError(err));
    } finally {
      setPendingAction(null);
    }
  }, []);

  return (
    <div className="space-y-5" data-testid="storage-settings-panel">
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold">Data storage</p>
          <p className="text-xs text-muted-foreground">
            {isCloud
              ? 'Deployment environment owns the MongoDB target.'
              : 'Choose local SQLite or one MongoDB Atlas database.'}
          </p>
        </div>
        <span role="status" className={statusBadgeClass}>
          {statusLabel(status)}
        </span>
      </div>

      {isLocal && (
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="text-xs font-medium text-muted-foreground">
              MongoDB URI
            </span>
            <input
              type="password"
              autoComplete="off"
              value={uri}
              onChange={(event) => setUri(event.target.value)}
              placeholder="mongodb+srv://..."
              className={cn(
                'w-full rounded-lg border border-border bg-background px-3 py-2',
                'text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ffb74d]',
              )}
            />
          </label>
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="text-xs font-medium text-muted-foreground">
              Database name
            </span>
            <input
              type="text"
              autoComplete="off"
              value={dbName}
              onChange={(event) => setDbName(event.target.value)}
              placeholder="a2ui"
              className={cn(
                'w-full rounded-lg border border-border bg-background px-3 py-2',
                'text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ffb74d]',
              )}
            />
          </label>
        </div>
      )}

      {isLocal && (
        <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
          <button
            type="button"
            onClick={handleSave}
            disabled={busy}
            className={cn(
              'inline-flex items-center justify-center rounded-lg border border-border',
              'px-3 py-2 text-sm font-medium hover:bg-muted/50',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ffb74d]',
              'disabled:opacity-50 w-full sm:w-auto',
            )}
          >
            Save connection
          </button>
          <button
            type="button"
            onClick={() => void handleConnect()}
            disabled={busy || status?.canConnect === false}
            className={cn(
              'inline-flex items-center justify-center gap-2 rounded-lg',
              'bg-[#ffb74d] px-3 py-2 text-sm font-semibold text-black',
              'hover:bg-[#ffb74d]/90 focus:outline-none',
              'focus-visible:ring-2 focus-visible:ring-[#ffb74d]',
              'disabled:opacity-50 w-full sm:w-auto',
            )}
          >
            {pendingAction === 'connect' && (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            )}
            Connect
          </button>
          <button
            type="button"
            onClick={() => void handleDisconnect()}
            disabled={busy || !status?.canDisconnect}
            className={cn(
              'inline-flex items-center justify-center gap-2 rounded-lg border border-border',
              'px-3 py-2 text-sm font-medium hover:bg-muted/50',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ffb74d]',
              'disabled:opacity-50 w-full sm:w-auto',
            )}
          >
            {pendingAction === 'disconnect' && (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            )}
            Disconnect
          </button>
          <button
            type="button"
            onClick={() => void handleMigrate()}
            disabled={busy || !status?.canMigrate}
            className={cn(
              'inline-flex items-center justify-center gap-2 rounded-lg border border-border',
              'px-3 py-2 text-sm font-medium hover:bg-muted/50',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ffb74d]',
              'disabled:opacity-50 w-full sm:w-auto',
            )}
          >
            {pendingAction === 'migrate' && (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            )}
            Migrate local data
          </button>
        </div>
      )}

      {saveNotice && (
        <p role="status" className="text-xs text-emerald-500">
          {saveNotice}
        </p>
      )}

      {error && (
        <p
          role="alert"
          className="text-sm text-red-500 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2"
        >
          {error}
        </p>
      )}

      {migration && (
        <div className="space-y-2 rounded-lg border border-border bg-muted/20 p-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Migration result
          </p>
          <ul className="space-y-1 text-xs text-muted-foreground">
            {Object.entries(migration.collections).map(([name, counts]) => (
              <li key={name}>
                {name}: {counts.rows} rows · {counts.upserted} upserted ·{' '}
                {counts.matched} matched · {counts.modified} modified
              </li>
            ))}
            <li>
              checkpoints: {migration.checkpoints} · checkpoint writes:{' '}
              {migration.checkpointWrites}
            </li>
          </ul>
          {migration.warnings.length > 0 && (
            <ul className="space-y-1 text-xs text-amber-500">
              {migration.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        {isCloud
          ? 'Connection details are owned by the deployment environment. Atlas stores app data and plaintext provider keys while connected.'
          : 'Connection details stay in this browser. Atlas stores app data and plaintext provider keys while connected.'}
      </p>
    </div>
  );
}
