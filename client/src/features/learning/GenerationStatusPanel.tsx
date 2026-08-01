/**
 * ============================================================================
 * FILE: GenerationStatusPanel.tsx
 * LOCATION: client/src/features/learning/GenerationStatusPanel.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Stage, counts, warning, and generation control strip.
 *
 * ROLE IN PROJECT:
 *    Shows progressive generation status under the course header with Stop,
 *    Resume, and Delete controls for retained lifecycle management.
 *
 * KEY COMPONENTS:
 *    - GenerationStatusPanel: Live stage panel
 *    - STAGE_COPY: Academic/professional stage labels
 *
 * DEPENDENCIES:
 *    - External: lucide-react
 *    - Internal: @/types/generation, @/lib/utils
 *
 * USAGE:
 *    <GenerationStatusPanel generation={g} onCancel={...} onResume={...} onDelete={...} />
 * ============================================================================
 */

import { AlertTriangle, Loader2, Pause, Play, Square, Trash2 } from 'lucide-react';

import type { GenerationJobPublic, GenerationStage } from '@/types/generation';
import { cn } from '@/lib/utils';
import { isTerminalGenerationStage } from './generationEvents';

const STAGE_COPY: Record<GenerationStage, string> = {
  INITIALIZING: 'Initializing course generation',
  RESEARCHING: 'Researching current sources',
  OUTLINING: 'Building table of contents',
  PLANNING_PREVIEW: 'Planning first 3 topics',
  GENERATING_PREVIEW: 'Generating preview topics',
  PLANNING_BATCH: 'Planning next topic batch',
  GENERATING_BATCH: 'Generating next topic batch',
  PAUSED: 'Generation paused',
  CANCELLED: 'Generation stopped',
  COMPLETE: 'Course generation complete',
  COMPLETE_DEGRADED: 'Course complete with research warning',
  FAILED: 'Course generation failed',
};

export interface GenerationStatusPanelProps {
  generation: GenerationJobPublic;
  onCancel: () => void;
  onResume: () => void;
  onDelete: () => void;
  isCancelling?: boolean;
  isResuming?: boolean;
  isDeleting?: boolean;
  className?: string;
}

export function GenerationStatusPanel({
  generation,
  onCancel,
  onResume,
  onDelete,
  isCancelling = false,
  isResuming = false,
  isDeleting = false,
  className,
}: GenerationStatusPanelProps) {
  const stage = generation.stage;
  const copy = STAGE_COPY[stage] ?? stage;
  const counts = generation.counts;
  const isActive = !isTerminalGenerationStage(stage) && stage !== 'PAUSED';
  const isDegraded =
    generation.grounding_status === 'DEGRADED' ||
    stage === 'COMPLETE_DEGRADED';
  const pending = isCancelling || isResuming || isDeleting;

  return (
    <section
      className={cn(
        'rounded-xl border border-border bg-card/80 backdrop-blur-md p-4 shadow-sm',
        className,
      )}
      aria-label="Generation status"
    >
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-1.5">
          <div className="flex items-center gap-2">
            {isActive && (
              <Loader2
                className="h-4 w-4 animate-pulse text-[#ffb74d] shrink-0"
                aria-hidden="true"
              />
            )}
            {stage === 'PAUSED' && (
              <Pause className="h-4 w-4 text-muted-foreground shrink-0" aria-hidden="true" />
            )}
            <p
              className="text-sm font-semibold text-foreground"
              role="status"
              aria-live="polite"
            >
              {copy}
            </p>
          </div>

          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {counts.research_sections > 0 && (
              <span>{counts.research_sections} sections</span>
            )}
            {counts.sources > 0 && <span>{counts.sources} sources</span>}
            {counts.topics_total > 0 && (
              <span>
                {counts.topics_ready}/{counts.topics_total} topics ready
              </span>
            )}
            {counts.topics_failed > 0 && (
              <span className="text-amber-600 dark:text-amber-400">
                {counts.topics_failed} failed
              </span>
            )}
          </div>

          {generation.warnings.length > 0 && (
            <ul className="space-y-1">
              {generation.warnings.map((w) => (
                <li
                  key={`${w.code}-${w.message}`}
                  className="text-xs text-amber-600 dark:text-amber-400 flex items-start gap-1.5"
                >
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                  {w.message}
                </li>
              ))}
            </ul>
          )}

          {isDegraded && (
            <p
              role="alert"
              className="text-xs text-amber-600 dark:text-amber-400 flex items-start gap-1.5"
            >
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              Web research was incomplete; this course is not fully
              web-grounded.
            </p>
          )}

          {stage === 'CANCELLED' && (
            <p className="text-xs text-muted-foreground">
              Partial course retained. Current report, outline, and cards remain.
              Resume sends fresh credentials for resumed work.
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 shrink-0">
          {generation.can_cancel && (
            <button
              type="button"
              onClick={onCancel}
              disabled={pending}
              aria-label="Stop generation"
              className={cn(
                'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium',
                'border border-border bg-muted hover:bg-muted/80',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ffb74d]',
                'disabled:opacity-50 disabled:cursor-not-allowed',
              )}
            >
              <Square className="h-3.5 w-3.5" aria-hidden="true" />
              {isCancelling ? 'Stopping...' : 'Stop'}
            </button>
          )}
          {generation.can_resume && (
            <button
              type="button"
              onClick={onResume}
              disabled={pending}
              aria-label="Resume generation"
              className={cn(
                'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium',
                'bg-[#ffb74d] text-black hover:bg-[#ffb74d]/90',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ffb74d]',
                'disabled:opacity-50 disabled:cursor-not-allowed',
              )}
            >
              <Play className="h-3.5 w-3.5" aria-hidden="true" />
              {isResuming ? 'Resuming...' : 'Resume'}
            </button>
          )}
          <button
            type="button"
            onClick={onDelete}
            disabled={pending}
            aria-label="Delete course permanently"
            className={cn(
              'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium',
              'border border-destructive/40 text-destructive hover:bg-destructive/10',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-destructive',
              'disabled:opacity-50 disabled:cursor-not-allowed',
            )}
          >
            <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            {isDeleting ? 'Deleting...' : 'Delete'}
          </button>
        </div>
      </div>
    </section>
  );
}
