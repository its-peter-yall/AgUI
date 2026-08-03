/**
 * ============================================================================
 * FILE: storage.ts
 * LOCATION: client/src/types/storage.ts
 * ============================================================================
 *
 * PURPOSE:
 *    TypeScript contracts for storage lifecycle and app-settings APIs.
 *
 * ROLE IN PROJECT:
 *    Shared client types matching server camelCase storage responses.
 *
 * KEY COMPONENTS:
 *    - StorageStatus, AppSettingsSnapshot, StorageMigrationResult
 *
 * DEPENDENCIES:
 *    - External: None
 *    - Internal: providerSettings, webSearch types
 *
 * USAGE:
 *    import type { StorageStatus } from '@/types/storage';
 * ============================================================================
 */

import type { AIProviderSettings } from '@/lib/providerSettings';
import type { WebSearchSettings } from '@/types/webSearch';

export type DeploymentMode = 'local' | 'cloud';
export type StorageBackend = 'sqlite' | 'mongo';

export interface StorageStatus {
  deploymentMode: DeploymentMode;
  activeBackend: StorageBackend;
  connected: boolean;
  mongoDbName: string | null;
  canConnect: boolean;
  canDisconnect: boolean;
  canMigrate: boolean;
  localDataPresent: boolean;
}

export interface AppSettingsSnapshot {
  providerSettings: AIProviderSettings | null;
  webSearchSettings: WebSearchSettings | null;
}

export interface CollectionMigrationResult {
  rows: number;
  matched: number;
  upserted: number;
  modified: number;
}

export interface StorageMigrationResult {
  collections: Record<string, CollectionMigrationResult>;
  checkpoints: number;
  checkpointWrites: number;
  warnings: string[];
}
