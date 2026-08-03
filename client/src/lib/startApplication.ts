/**
 * ============================================================================
 * FILE: startApplication.ts
 * LOCATION: client/src/lib/startApplication.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Await storage boot before invoking the React renderer.
 *
 * ROLE IN PROJECT:
 *    Entry seam so Mongo connect/hydrate finishes once before app mount and
 *    learning queries cannot race SQLite/Mongo backend switches.
 *
 * KEY COMPONENTS:
 *    - startApplication: boot then render callback
 *
 * DEPENDENCIES:
 *    - External: None
 *    - Internal: storageBoot
 *
 * USAGE:
 *    void startApplication(renderApplication);
 * ============================================================================
 */

import { bootstrapStorage } from '@/lib/storageBoot';

export async function startApplication(render: () => void): Promise<void> {
  await bootstrapStorage();
  render();
}
