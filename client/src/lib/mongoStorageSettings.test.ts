/**
 * ============================================================================
 * FILE: mongoStorageSettings.test.ts
 * LOCATION: client/src/lib/mongoStorageSettings.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Unit tests for browser-only Mongo connection settings persistence.
 *
 * ROLE IN PROJECT:
 *    Guards safe parse, trim round-trip, and isolated clear of Atlas URI/db.
 *
 * KEY COMPONENTS:
 *    - get/set/clear mongo storage settings tests
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: mongoStorageSettings
 *
 * USAGE:
 *    npm run test -- --run src/lib/mongoStorageSettings.test.ts
 * ============================================================================
 */

import { beforeEach, describe, expect, it } from 'vitest';
import {
  clearMongoStorageSettings,
  getMongoStorageSettings,
  setMongoStorageSettings,
} from '@/lib/mongoStorageSettings';

describe('mongoStorageSettings', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('returns null when settings are absent or malformed', () => {
    expect(getMongoStorageSettings()).toBeNull();
    localStorage.setItem('a2ui_mongo_storage', '{bad');
    expect(getMongoStorageSettings()).toBeNull();
  });

  it('round-trips a trimmed URI and database name', () => {
    setMongoStorageSettings({
      uri: ' mongodb+srv://user:secret@cluster ',
      dbName: ' a2ui ',
    });
    expect(getMongoStorageSettings()).toEqual({
      uri: 'mongodb+srv://user:secret@cluster',
      dbName: 'a2ui',
    });
  });

  it('clears only Mongo connection settings', () => {
    localStorage.setItem('agui-theme', 'dark');
    setMongoStorageSettings({ uri: 'mongodb://host', dbName: 'a2ui' });
    clearMongoStorageSettings();
    expect(getMongoStorageSettings()).toBeNull();
    expect(localStorage.getItem('agui-theme')).toBe('dark');
  });
});
