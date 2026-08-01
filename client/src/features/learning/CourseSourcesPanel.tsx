/**
 * ============================================================================
 * FILE: CourseSourcesPanel.tsx
 * LOCATION: client/src/features/learning/CourseSourcesPanel.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Course research report modal with sections, sources, and providers.
 *
 * ROLE IN PROJECT:
 *    Displays structured ResearchReport artifacts. Links use server-validated
 *    HTTP(S) URLs only. Shows Brave attribution when required.
 *
 * KEY COMPONENTS:
 *    - CourseSourcesPanel: Responsive modal/drawer
 *
 * DEPENDENCIES:
 *    - External: react, lucide-react, framer-motion
 *    - Internal: MarkdownRenderer, types/generation, utils
 *
 * USAGE:
 *    <CourseSourcesPanel isOpen report={report} onClose={...} />
 * ============================================================================
 */

import { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { AlertTriangle, X } from 'lucide-react';

import type { ResearchReport } from '@/types/generation';
import { cn } from '@/lib/utils';
import { MarkdownRenderer } from './MarkdownRenderer';

function isSafeHttpUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:';
  } catch {
    return false;
  }
}

export interface CourseSourcesPanelProps {
  isOpen: boolean;
  onClose: () => void;
  report: ResearchReport | null | undefined;
}

export function CourseSourcesPanel({
  isOpen,
  onClose,
  report,
}: CourseSourcesPanelProps) {
  const modalRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
        return;
      }
      if (event.key !== 'Tab' || !modalRef.current) return;
      const focusable = modalRef.current.querySelectorAll<HTMLElement>(
        'button, [href], [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    modalRef.current?.focus();
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      previous?.focus();
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const hasBrave = report?.sources.some((s) => s.provider_id === 'brave');
  const isDegraded = report?.status === 'DEGRADED';
  const sections = [...(report?.sections ?? [])].sort(
    (a, b) => a.sequence_index - b.sequence_index,
  );

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm p-0 sm:p-4"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={(e) => e.target === e.currentTarget && onClose()}
      >
        <motion.div
          ref={modalRef}
          role="dialog"
          aria-modal="true"
          aria-label="Course sources"
          tabIndex={-1}
          className={cn(
            'relative w-full sm:max-w-3xl max-h-[90dvh] overflow-y-auto',
            'bg-card/95 backdrop-blur-md border border-border shadow-2xl',
            'rounded-t-xl sm:rounded-xl p-5 sm:p-6 flex flex-col gap-4',
            'focus:outline-none',
          )}
          initial={{ y: 40, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 40, opacity: 0 }}
        >
          <button
            type="button"
            onClick={onClose}
            className="absolute top-4 right-4 p-2 rounded-md hover:bg-muted text-muted-foreground transition-colors cursor-pointer"
            aria-label="Close course sources"
          >
            <X className="w-5 h-5" />
          </button>

          <header className="pr-10">
            <h2 className="text-xl font-bold text-foreground">Course Sources</h2>
            {report && (
              <p className="text-sm text-muted-foreground mt-1">
                Status: {report.status}
                {report.sources.length > 0 &&
                  ` · ${report.sources.length} sources`}
                {sections.length > 0 && ` · ${sections.length} sections`}
              </p>
            )}
          </header>

          {!report && (
            <p className="text-sm text-muted-foreground">
              Research report not available yet.
            </p>
          )}

          {report?.summary && (
            <p className="text-sm text-foreground/90 whitespace-pre-wrap">
              {report.summary}
            </p>
          )}

          {report && isDegraded && (
            <div
              role="alert"
              className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300"
            >
              <p className="font-semibold flex items-center gap-1.5">
                <AlertTriangle className="h-4 w-4" />
                Research incomplete
              </p>
              <p className="mt-1">
                This course is not fully web-grounded.
              </p>
              {report.limitations.length > 0 && (
                <ul className="mt-2 list-disc pl-5 space-y-0.5 text-xs">
                  {report.limitations.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {/* N3: warnings independent of degraded block */}
          {report && report.warnings.length > 0 && (
            <ul className="space-y-1">
              {report.warnings.map((w) => (
                <li
                  key={`${w.code}-${w.message}`}
                  className="text-xs text-amber-700 dark:text-amber-300 flex items-start gap-1.5"
                >
                  <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                  {w.message}
                </li>
              ))}
            </ul>
          )}

          {report?.freshness_note && (
            <p className="text-xs text-muted-foreground">
              {report.freshness_note}
            </p>
          )}

          {report && report.provider_statuses.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold mb-2">Providers</h3>
              <ul className="flex flex-wrap gap-2">
                {report.provider_statuses.map((p) => (
                  <li
                    key={p.provider_id}
                    className="text-xs px-2 py-1 rounded-full border border-border bg-muted/40"
                  >
                    {p.provider_id}: {p.state}
                    {p.search_calls > 0 && ` (${p.search_calls} calls)`}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {sections.length > 0 && (
            <div className="space-y-4">
              <h3 className="text-sm font-semibold">Report sections</h3>
              {sections.map((section) => (
                <article
                  key={section.id}
                  className="rounded-lg border border-border/60 p-3 bg-muted/20"
                >
                  <h4 className="text-sm font-semibold mb-2">
                    {section.theme}
                  </h4>
                  <MarkdownRenderer content={section.markdown} />
                </article>
              ))}
            </div>
          )}

          {report && report.sources.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold">
                  Sources ({report.sources.length})
                </h3>
                {hasBrave && (
                  <span className="text-xs text-muted-foreground">
                    Powered by Brave
                  </span>
                )}
              </div>
              <ul className="space-y-3">
                {report.sources.map((source) => (
                  <li
                    key={source.id}
                    className="rounded-lg border border-border/60 p-3 bg-card"
                  >
                    {isSafeHttpUrl(source.url) ? (
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-sm font-medium text-primary hover:underline"
                      >
                        {source.title}
                      </a>
                    ) : (
                      <span className="text-sm font-medium">{source.title}</span>
                    )}
                    <p className="text-xs text-muted-foreground mt-1">
                      {[
                        source.publisher,
                        source.provider_id,
                        source.published_at
                          ? `Published ${source.published_at}`
                          : null,
                        source.retrieved_at
                          ? `Retrieved ${source.retrieved_at}`
                          : null,
                      ]
                        .filter(Boolean)
                        .join(' · ')}
                    </p>
                    {(source.excerpt || source.snippet) && (
                      <p className="text-xs text-muted-foreground mt-1.5 line-clamp-3">
                        {source.excerpt || source.snippet}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {report &&
            !isDegraded &&
            report.limitations.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold mb-1">Limitations</h3>
                <ul className="list-disc pl-5 text-xs text-muted-foreground space-y-0.5">
                  {report.limitations.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
