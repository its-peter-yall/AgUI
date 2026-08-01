/**
 * ============================================================================
 * FILE: SourceCitations.tsx
 * LOCATION: client/src/features/learning/SourceCitations.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Validated card citation footer for READY/ERROR concept cards.
 *
 * ROLE IN PROJECT:
 *    Renders numbered external links from server-validated citation metadata.
 *    Never constructs URLs from model Markdown.
 *
 * KEY COMPONENTS:
 *    - SourceCitations: Compact numbered citation list
 *
 * DEPENDENCIES:
 *    - External: None
 *    - Internal: @/types/learning, @/lib/utils
 *
 * USAGE:
 *    <SourceCitations citations={node.citations} />
 * ============================================================================
 */

import type { NodeCitation } from '@/types/learning';
import { cn } from '@/lib/utils';

function isSafeHttpUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:';
  } catch {
    return false;
  }
}

export interface SourceCitationsProps {
  citations: NodeCitation[];
  className?: string;
}

export function SourceCitations({ citations, className }: SourceCitationsProps) {
  const valid = citations.filter(
    (c) => c.title && c.url && isSafeHttpUrl(c.url),
  );
  if (valid.length === 0) {
    return null;
  }

  const sorted = [...valid].sort(
    (a, b) => a.citation_number - b.citation_number,
  );

  return (
    <footer
      className={cn(
        'mt-4 pt-3 border-t border-border/60',
        className,
      )}
      aria-label="Source citations"
    >
      <p className="text-xs font-semibold text-muted-foreground mb-1.5">
        Sources
      </p>
      <ol className="flex flex-col gap-1">
        {sorted.map((citation) => (
          <li key={`${citation.source_id}-${citation.citation_number}`}>
            <a
              href={citation.url}
              target="_blank"
              rel="noreferrer noopener"
              className="text-xs text-primary hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
            >
              {citation.citation_number}. {citation.title}
              {citation.publisher ? ` — ${citation.publisher}` : ''}
            </a>
          </li>
        ))}
      </ol>
    </footer>
  );
}
