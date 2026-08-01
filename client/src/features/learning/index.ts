/**
 * ============================================================================
 * FILE: index.ts
 * LOCATION: client/src/features/learning/index.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Barrel export file for the entire learning feature module. Provides a
 *    centralized access point for all components, hooks, utilities, and types.
 *
 * ROLE IN PROJECT:
 *    Public API surface of the learning feature. Consumers import from this
 *    file rather than individual modules, enabling tree-shaking and keeping
 *    internal paths encapsulated.
 *
 * KEY COMPONENTS:
 *    - Components: LearningPage, LearningHome, LearningPathContainer,
 *                  ConceptCard, QuizFeedback, TopicInput, ProgressBar,
 *                  LearningErrorBoundary, ErrorState, NotFoundState, etc.
 *    - Hooks: useQuizFeedback, useNodeState, useLearningMutations, useErrorToast
 *    - Utilities: optimisticUpdates, learningQueryKeys
 *    - Animations: Confetti, MasteryCelebration, AnimatedCard, ContentTransition
 *
 * DEPENDENCIES:
 *    - External: (none — re-exports only)
 *    - Internal: All individual files in client/src/features/learning/,
 *                @/types/learning
 *
 * USAGE:
 *    ```tsx
 *    import { LearningPage } from '@/features/learning';
 *    import { LearningPathContainer, useLearningMutations } from '@/features/learning';
 *    import type { ConceptNode, NodeStatus } from '@/features/learning';
 *    ```
 * ============================================================================
 */

// Components
export { LearningPathContainer } from './LearningPathContainer';
export { ConceptCard } from './ConceptCard';
export { MarkdownRenderer } from './MarkdownRenderer';
export { SkeletonCard, SkeletonPath } from './SkeletonCard';
export { QuizFeedback } from './QuizFeedback';
export { TopicInput } from './TopicInput';
export { ProgressBar } from './ProgressBar';
export { LearningPage } from './LearningPage';
export { LearningHome } from './LearningHome';
export { RevisionPage } from './RevisionPage';
export { RevisionConceptCard } from './RevisionConceptCard';
export { LearningErrorBoundary } from './LearningErrorBoundary';
export { CourseCard } from './CourseCard';
export type { CourseCardProps } from './CourseCard';
export { CourseFilter } from './CourseFilter';
export type { CourseFilterProps, FilterStatus, SortField } from './CourseFilter';
export { CourseCardSkeleton } from './CourseCardSkeleton';
export { GenerationStatusPanel } from './GenerationStatusPanel';
export { CourseSourcesPanel } from './CourseSourcesPanel';
export { SourceCitations } from './SourceCitations';
export {
  ErrorState,
  NotFoundState,
  EmptyState,
  LoadingState,
  GeneratingState,
} from './ErrorStates';

// Hooks
export { useQuizFeedback } from './useQuizFeedback';
export { useNodeState, isValidTransition, getNextStatus } from './useNodeState';
export { useLearningMutations } from './useLearningMutations';
export { useErrorToast, ToastContainer } from './useErrorToast';
export { useCourseList } from './useCourseList';
export { useSessionEvents } from './useSessionEvents';
export { applyGenerationEvent, isTerminalGenerationStage } from './generationEvents';
export type { UseCourseListOptions } from './useCourseList';
export type { UseLearningMutationsProps } from './useLearningMutations';
export type { NodeActions, NodeStateResult } from './useNodeState';

// Utilities
export {
  optimisticStatusUpdate,
  optimisticCompletionUpdate,
  optimisticUnlockNext,
  optimisticMasteryUpdate,
  combineRollbacks,
  learningQueryKeys,
} from './optimisticUpdates';
export type { RollbackFn } from './optimisticUpdates';
export {
  Confetti,
  MasteryCelebration,
  AnimatedCard,
  ContentTransition,
} from './animations';
export type {
  LearningSession,
  LearningSessionWithNodes,
  LearningSessionSummary,
  SessionListResponse,
  ConceptNode,
  NodeStatus,
  QuizCard,
  QuizCardHidden,
  QuizOption,
  QuizOptionHidden,
  QuizSet,
  QuizSetHidden,
  QuizSubmitResponse,
  QuizAttemptHistory,
  getVisibleQuiz,
} from '@/types/learning';
