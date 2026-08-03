/**
 * ============================================================================
 * FILE: TopicInput.tsx
 * LOCATION: client/src/features/learning/TopicInput.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Form for entering a learning topic with optional per-course web search.
 *
 * ROLE IN PROJECT:
 *    Entry point on LearningHome. Calls generateCourse (202), seeds React Query
 *    cache, and navigates immediately to the progressive session shell.
 *
 * KEY COMPONENTS:
 *    - TopicInput: Form with depth picker, web-search toggle, submit
 *
 * DEPENDENCIES:
 *    - External: react-router-dom, @tanstack/react-query, lucide-react
 *    - Internal: learningApi, providerSettings, utils
 *
 * USAGE:
 *    <TopicInput />
 * ============================================================================
 */

import { useState, useId, useRef, useEffect } from 'react';
import type { FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, Globe2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { generateCourse } from '@/lib/learningApi';
import {
  areAgentModelsConfigured,
  getProviderSettings,
  hasWebSearchCapability,
} from '@/lib/providerSettings';
import type {
  GenerateCourseRequest,
  LearningDepthMode,
  LearningSessionWithNodes,
} from '@/types/learning';

interface TopicInputProps {
  className?: string;
  placeholder?: string;
  userId?: string;
  autoFocus?: boolean;
}

const TOPIC_SUGGESTIONS = [
  "Newton's Laws",
  'Photosynthesis',
  'Machine Learning Basics',
] as const;

const DEPTH_MODE_OPTIONS: Array<{
  value: LearningDepthMode;
  label: string;
}> = [
  { value: 'auto', label: 'Auto' },
  { value: 'lite', label: 'Lite' },
  { value: 'full', label: 'Full' },
];

export function TopicInput({
  className,
  placeholder = 'What do you want to learn today?',
  userId,
  autoFocus = false,
}: TopicInputProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<LearningDepthMode>('auto');
  const [modeOpen, setModeOpen] = useState(false);
  const [webSearchEnabled, setWebSearchEnabled] = useState(false);
  const inputId = useId();
  const modeListboxId = useId();
  const modePickerRef = useRef<HTMLDivElement>(null);

  const canUseWebSearch = hasWebSearchCapability();

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        modePickerRef.current &&
        !modePickerRef.current.contains(event.target as Node)
      ) {
        setModeOpen(false);
      }
    }

    if (modeOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [modeOpen]);

  const generateMutation = useMutation({
    mutationFn: (data: GenerateCourseRequest) =>
      generateCourse(data, { webSearchEnabled }),
    onSuccess: (accepted) => {
      const shell = accepted.session;
      const session: LearningSessionWithNodes = {
        id: String(shell.id),
        user_id:
          typeof shell.user_id === 'string' || shell.user_id === null
            ? (shell.user_id as string | null)
            : null,
        query: String(shell.query ?? ''),
        course_title: String(shell.course_title ?? shell.query ?? ''),
        total_nodes:
          typeof shell.total_nodes === 'number' ? shell.total_nodes : 0,
        completed_nodes:
          typeof shell.completed_nodes === 'number'
            ? shell.completed_nodes
            : 0,
        last_active_node_id: null,
        title_finalized:
          typeof shell.title_finalized === 'boolean'
            ? shell.title_finalized
            : false,
        created_at:
          typeof shell.created_at === 'string'
            ? shell.created_at
            : new Date().toISOString(),
        updated_at: null,
        nodes: Array.isArray(shell.nodes)
          ? (shell.nodes as LearningSessionWithNodes['nodes'])
          : [],
        generation: accepted.generation,
      };
      queryClient.setQueryData(['learningSession', session.id], session);
      queryClient.invalidateQueries({ queryKey: ['courses'] });
      navigate(`/learn/${session.id}`);
    },
  });

  const settings = getProviderSettings();
  const activeConfig = settings.providers[settings.activeProvider];
  const hasApiKey = Boolean(activeConfig.apiKey);
  const agentsReady = areAgentModelsConfigured(activeConfig);
  const canStart = hasApiKey && agentsReady;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (query.trim() && !generateMutation.isPending && canStart) {
      generateMutation.mutate({
        query: query.trim(),
        user_id: userId,
        mode,
      });
    }
  };

  const handleSuggestionClick = (suggestion: string) => {
    setQuery(suggestion);
  };

  const isLoading = generateMutation.isPending;
  const error = generateMutation.error;
  const selectedModeLabel =
    DEPTH_MODE_OPTIONS.find((option) => option.value === mode)?.label ?? 'Auto';

  return (
    <div className={cn('w-full max-w-2xl', className)}>
      <form onSubmit={handleSubmit} className="relative" role="search">
        <label htmlFor={inputId} className="sr-only">
          Enter a topic to learn
        </label>
        <input
          id={inputId}
          type="search"
          role="searchbox"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoFocus={autoFocus}
          placeholder={placeholder}
          disabled={isLoading || !canStart}
          aria-describedby={error ? `${inputId}-error` : undefined}
          aria-invalid={error ? 'true' : undefined}
          className={cn(
            'w-full px-4 py-3 pr-56 text-lg rounded-lg border',
            'bg-background text-foreground',
            'placeholder:text-muted-foreground',
            'focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent',
            'disabled:opacity-50 disabled:cursor-not-allowed',
            'transition-colors duration-200',
            error && 'border-destructive focus:ring-destructive',
          )}
        />
        <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1.5 sm:gap-2">
          {canUseWebSearch && (
            <button
              type="button"
              aria-label="Use web search for this course"
              aria-pressed={webSearchEnabled}
              title={
                webSearchEnabled
                  ? 'Web search on for this course'
                  : 'Web search off for this course'
              }
              onClick={() => setWebSearchEnabled((v) => !v)}
              disabled={isLoading || !canStart}
              className={cn(
                'inline-flex items-center justify-center h-8 w-8 rounded-md shrink-0',
                'border transition-colors duration-200',
                'focus:outline-none focus:ring-2 focus:ring-primary',
                'disabled:opacity-50 disabled:cursor-not-allowed',
                webSearchEnabled
                  ? 'bg-[#ffb74d]/15 border-[#ffb74d] text-[#ffb74d]'
                  : 'bg-muted border-border text-muted-foreground hover:text-foreground',
              )}
            >
              <Globe2 className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
          <div ref={modePickerRef} className="relative">
            <button
              type="button"
              onClick={() => {
                if (!isLoading && canStart) {
                  setModeOpen((open) => !open);
                }
              }}
              disabled={isLoading || !canStart}
              aria-label="Learning depth mode"
              aria-haspopup="listbox"
              aria-expanded={modeOpen}
              aria-controls={modeListboxId}
              className={cn(
                'inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm',
                'bg-muted text-foreground border border-border',
                'hover:border-border/80 hover:bg-muted/80',
                'focus:outline-none focus:ring-2 focus:ring-primary',
                'disabled:opacity-50 disabled:cursor-not-allowed',
                'transition-colors duration-200',
                modeOpen && 'ring-2 ring-primary border-transparent',
              )}
            >
              <span className="leading-none">{selectedModeLabel}</span>
              <ChevronDown
                className={cn(
                  'h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform duration-200',
                  modeOpen && 'rotate-180',
                )}
                aria-hidden="true"
              />
            </button>

            {modeOpen && (
              <div
                id={modeListboxId}
                role="listbox"
                aria-label="Learning depth mode"
                className={cn(
                  'absolute right-0 top-full z-50 mt-1 min-w-full',
                  'rounded-md border border-border bg-popover text-popover-foreground',
                  'shadow-lg overflow-hidden',
                )}
              >
                {DEPTH_MODE_OPTIONS.map((option) => {
                  const isSelected = option.value === mode;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      role="option"
                      aria-selected={isSelected}
                      onClick={() => {
                        setMode(option.value);
                        setModeOpen(false);
                      }}
                      className={cn(
                        'w-full text-left px-3 py-2 text-sm transition-colors',
                        'hover:bg-muted focus:outline-none focus:bg-muted',
                        isSelected &&
                          'bg-primary/10 text-primary font-semibold',
                      )}
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
          <button
            type="submit"
            disabled={!query.trim() || isLoading || !canStart}
            aria-label={isLoading ? 'Starting...' : 'Start learning'}
            className={cn(
              'px-4 py-1.5 rounded-md text-sm font-medium',
              'bg-primary text-primary-foreground hover:bg-primary/90 focus:ring-primary',
              'transition-colors duration-200',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              'focus:outline-none focus:ring-2 focus:ring-offset-2',
            )}
          >
            {isLoading ? 'Starting...' : 'Learn'}
          </button>
        </div>
      </form>

      {isLoading && (
        <div className="mt-3 text-center" role="status" aria-live="polite">
          <p className="text-sm text-muted-foreground animate-pulse">
            Starting your course...
          </p>
        </div>
      )}

      {error && (
        <p
          id={`${inputId}-error`}
          className="mt-3 text-sm text-destructive text-center"
          role="alert"
        >
          Failed to start course. Please try again.
        </p>
      )}

      {!hasApiKey && (
        <p
          className="mt-3 text-sm text-amber-600 dark:text-amber-400 text-center"
          role="alert"
        >
          Enter your API key in the settings page to start learning.
        </p>
      )}

      {hasApiKey && !agentsReady && (
        <p
          className="mt-3 text-sm text-amber-600 dark:text-amber-400 text-center"
          role="alert"
        >
          Set Researcher, Planner, Generator, and Quizzer models in Settings
          before starting a course.
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2 justify-center">
        <span className="text-sm text-muted-foreground">Try:</span>
        {TOPIC_SUGGESTIONS.map((suggestion) => (
          <button
            key={suggestion}
            type="button"
            onClick={() => handleSuggestionClick(suggestion)}
            disabled={isLoading || !canStart}
            className={cn(
              'px-3 py-1 text-sm rounded-full',
              'bg-muted hover:bg-muted/80 text-muted-foreground',
              'transition-colors duration-200',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              'focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2',
            )}
          >
            {suggestion}
          </button>
        ))}
      </div>
    </div>
  );
}
