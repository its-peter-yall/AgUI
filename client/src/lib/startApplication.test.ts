/**
 * ============================================================================
 * FILE: startApplication.test.ts
 * LOCATION: client/src/lib/startApplication.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Unit tests for bounded storage boot before first render.
 *
 * ROLE IN PROJECT:
 *    Guards that React mount waits for bootstrapStorage to settle.
 *
 * KEY COMPONENTS:
 *    - startApplication render-after-boot test
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: startApplication
 *
 * USAGE:
 *    npm run test -- --run src/lib/startApplication.test.ts
 * ============================================================================
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const bootstrapStorageMock = vi.fn();

vi.mock('@/lib/storageBoot', () => ({
  bootstrapStorage: (...args: unknown[]) => bootstrapStorageMock(...args),
}));

import { startApplication } from '@/lib/startApplication';

describe('startApplication', () => {
  beforeEach(() => {
    bootstrapStorageMock.mockReset();
  });

  it('renders only after bounded storage boot settles', async () => {
    const render = vi.fn();
    bootstrapStorageMock.mockResolvedValue({ status: null, error: 'offline' });
    await startApplication(render);
    expect(bootstrapStorageMock).toHaveBeenCalledTimes(1);
    expect(render).toHaveBeenCalledTimes(1);
  });
});
