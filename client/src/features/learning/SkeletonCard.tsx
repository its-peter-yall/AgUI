/**
 * ============================================================================
 * FILE: SkeletonCard.tsx
 * LOCATION: client/src/features/learning/SkeletonCard.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Topic-aware skeleton for progressive module generation.
 *
 * ROLE IN PROJECT:
 *    Loading-state UI for SKELETON/GENERATING modules. Static when paused or
 *    cancelled; animated while actively generating.
 *
 * KEY COMPONENTS:
 *    - SkeletonCard: Single titled skeleton
 *    - SkeletonPath: Multiple skeleton cards
 *
 * DEPENDENCIES:
 *    - External: None
 *    - Internal: @/lib/utils
 *
 * USAGE:
 *    <SkeletonCard title="Topic" sequenceIndex={0} animated />
 * ============================================================================
 */

import { cn } from '@/lib/utils';

interface SkeletonCardProps {
  className?: string;
  title?: string;
  sequenceIndex?: number;
  animated?: boolean;
}

export function SkeletonCard({
  className,
  title,
  sequenceIndex,
  animated = true,
}: SkeletonCardProps) {
  const label =
    title && title.trim().length > 0
      ? title
      : sequenceIndex !== undefined
        ? `Topic ${sequenceIndex + 1}`
        : 'Loading content...';

  return (
    <div
      className={cn(
        'border rounded-lg bg-card',
        animated && 'animate-pulse',
        className,
      )}
      aria-busy="true"
      data-module-skeleton={animated ? 'generating' : 'static'}
    >
      <span className="sr-only">
        {animated ? `Generating ${label}` : `Waiting: ${label}`}
      </span>

      <div className="flex items-center gap-3 p-4 border-b">
        <div className="w-8 h-8 bg-muted rounded-full shrink-0" />
        <div className="flex-1 min-w-0">
          {title ? (
            <p className="text-sm font-semibold text-foreground truncate">
              {title}
            </p>
          ) : (
            <div className="h-4 bg-muted rounded w-3/4" />
          )}
          <div className="h-3 bg-muted rounded w-1/4 mt-2" />
        </div>
        <div className="h-4 w-6 bg-muted rounded shrink-0" />
      </div>

      <div className="p-4 space-y-3">
        <div className="h-4 bg-muted rounded w-full" />
        <div className="h-4 bg-muted rounded w-5/6" />
        <div className="h-4 bg-muted rounded w-4/6" />
        <div className="h-4 bg-muted rounded w-full" />
        <div className="h-4 bg-muted rounded w-3/4" />
      </div>

      <div className="flex justify-end p-4 border-t">
        <div className="h-9 w-32 bg-muted rounded" />
      </div>
    </div>
  );
}

interface SkeletonPathProps {
  count?: number;
}

export function SkeletonPath({ count = 5 }: SkeletonPathProps) {
  return (
    <div className="flex flex-col gap-4">
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} sequenceIndex={i} />
      ))}
    </div>
  );
}
