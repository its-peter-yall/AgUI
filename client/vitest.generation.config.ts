/**
 * ============================================================================
 * FILE: vitest.generation.config.ts
 * LOCATION: client/vitest.generation.config.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Enforces focused per-file coverage for new progressive generation modules.
 *
 * ROLE IN PROJECT:
 *    Supplements full Vitest execution with Phase 7 release thresholds.
 *
 * KEY COMPONENTS:
 *    - V8 include list and per-file thresholds
 *
 * DEPENDENCIES:
 *    - External: vitest/config
 *    - Internal: vite.config.ts
 *
 * USAGE:
 *    npm run test:generation:coverage
 * ============================================================================
 */

import { defineConfig, mergeConfig } from 'vitest/config';

import baseConfig from './vite.config';

export default mergeConfig(
  baseConfig,
  defineConfig({
    test: {
      coverage: {
        provider: 'v8',
        include: [
          'src/lib/webSearchProviders.ts',
          'src/lib/webSearchHeaders.ts',
          'src/features/settings/WebSearchSettingsPanel.tsx',
          'src/features/learning/generationEvents.ts',
          'src/features/learning/useSessionEvents.ts',
          'src/features/learning/GenerationStatusPanel.tsx',
          'src/features/learning/CourseSourcesPanel.tsx',
          'src/features/learning/SourceCitations.tsx',
        ],
        thresholds: {
          perFile: true,
          branches: 81,
          functions: 81,
          lines: 81,
          statements: 81,
        },
      },
    },
  }),
);
