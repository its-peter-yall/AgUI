/**
 * ============================================================================
 * FILE: mongoStorageSettings.ts
 * LOCATION: client/src/lib/mongoStorageSettings.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Browser-only persistence for MongoDB Atlas URI and database name.
 *
 * ROLE IN PROJECT:
 *    Keeps connection target in localStorage so boot and Settings can reconnect
 *    without storing secrets on the server in local deployment mode.
 *
 * KEY COMPONENTS:
 *    - getMongoStorageSettings: Safe parse of stored URI/dbName
 *    - setMongoStorageSettings: Trim and persist connection target
 *    - clearMongoStorageSettings: Remove only the Mongo key
 *
 * DEPENDENCIES:
 *    - External: None
 *    - Internal: None
 *
 * USAGE:
 *    const saved = getMongoStorageSettings();
 *    setMongoStorageSettings({ uri, dbName });
 * ============================================================================
 */

const MONGO_STORAGE_KEY = 'a2ui_mongo_storage';

export interface MongoStorageSettings {
  uri: string;
  dbName: string;
}

export function getMongoStorageSettings(): MongoStorageSettings | null {
  try {
    const raw = localStorage.getItem(MONGO_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    const value = parsed as Record<string, unknown>;
    if (typeof value.uri !== 'string' || typeof value.dbName !== 'string') {
      return null;
    }
    const uri = value.uri.trim();
    const dbName = value.dbName.trim();
    return uri && dbName ? { uri, dbName } : null;
  } catch {
    return null;
  }
}

export function setMongoStorageSettings(
  settings: MongoStorageSettings,
): void {
  localStorage.setItem(
    MONGO_STORAGE_KEY,
    JSON.stringify({
      uri: settings.uri.trim(),
      dbName: settings.dbName.trim(),
    }),
  );
}

export function clearMongoStorageSettings(): void {
  localStorage.removeItem(MONGO_STORAGE_KEY);
}
