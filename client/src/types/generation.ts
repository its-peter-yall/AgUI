/**
 * ============================================================================
 * FILE: generation.ts
 * LOCATION: client/src/types/generation.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Client mirrors of generation, research, source, citation, and progress
 *    event contracts exposed by the server API.
 *
 * ROLE IN PROJECT:
 *    Provides snake_case API payload types matching FastAPI JSON exactly so
 *    staged course generation can be consumed by the learning UI.
 *
 * KEY COMPONENTS:
 *    - GenerationStage, GroundingStatus: Workflow enums
 *    - ResearchReport family: Persisted research artifacts
 *    - GenerationEvent: Typed progress event envelope
 *
 * DEPENDENCIES:
 *    - External: None
 *    - Internal: None
 *
 * USAGE:
 *    import type { GenerationStage, GenerationEvent } from '@/types/generation';
 * ============================================================================
 */

export type GenerationStage =
  | 'INITIALIZING'
  | 'RESEARCHING'
  | 'OUTLINING'
  | 'PLANNING_PREVIEW'
  | 'GENERATING_PREVIEW'
  | 'PLANNING_BATCH'
  | 'GENERATING_BATCH'
  | 'PAUSED'
  | 'CANCELLED'
  | 'COMPLETE'
  | 'COMPLETE_DEGRADED'
  | 'FAILED';

export type GroundingStatus = 'DISABLED' | 'PENDING' | 'GROUNDED' | 'DEGRADED';

export type WebSearchProviderId =
  | 'tavily'
  | 'exa'
  | 'brave'
  | 'serpapi';

export interface GenerationCounts {
  topics_total: number;
  briefs_ready: number;
  topics_ready: number;
  topics_failed: number;
  research_sections: number;
  sources: number;
}

export interface GenerationWarning {
  code: string;
  message: string;
  provider_id: WebSearchProviderId | null;
}

export type ResearchStatus =
  | 'NOT_REQUESTED'
  | 'PENDING'
  | 'RESEARCHING'
  | 'COMPLETE'
  | 'DEGRADED'
  | 'CANCELLED';

export type ResearchProviderState =
  | 'READY'
  | 'USED'
  | 'RATE_LIMITED'
  | 'QUOTA_EXHAUSTED'
  | 'TIMED_OUT'
  | 'UNAVAILABLE'
  | 'AUTH_FAILED'
  | 'INVALID_REQUEST'
  | 'POLICY_REJECTED';

export interface ResearchSource {
  id: string;
  title: string;
  url: string;
  publisher: string | null;
  published_at: string | null;
  retrieved_at: string;
  provider_id: WebSearchProviderId;
  snippet: string;
  excerpt: string;
  relevance_score: number | null;
}

export interface ResearchSection {
  id: string;
  sequence_index: number;
  theme: string;
  markdown: string;
  source_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface ResearchProviderStatus {
  provider_id: WebSearchProviderId;
  state: ResearchProviderState;
  search_calls: number;
  result_count: number;
  error_class: string | null;
}

export interface ResearchReport {
  id: string;
  session_id: string;
  status: ResearchStatus;
  summary: string | null;
  limitations: string[];
  freshness_note: string | null;
  sections: ResearchSection[];
  sources: ResearchSource[];
  provider_statuses: ResearchProviderStatus[];
  warnings: GenerationWarning[];
  created_at: string;
  updated_at: string;
}

export interface NodeCitation {
  source_id: string;
  claim: string;
}

export type ProgressEventType =
  | 'stage_changed'
  | 'research_section_ready'
  | 'research_degraded'
  | 'outline_ready'
  | 'module_ready'
  | 'module_failed'
  | 'generation_paused'
  | 'generation_cancelled'
  | 'generation_complete';

export type GenerationEventPayload =
  | { previous_stage: GenerationStage; stage: GenerationStage }
  | {
      report_id: string;
      section_id: string;
      sequence_index: number;
      source_count: number;
    }
  | { warning: GenerationWarning }
  | { course_title: string; topic_count: number }
  | { node_id: string; sequence_index: number }
  | {
      node_id: string;
      sequence_index: number;
      failed_step: string;
      warning: GenerationWarning;
    }
  | { stage: GenerationStage; warning: GenerationWarning }
  | { stage: GenerationStage }
  | {
      stage: GenerationStage;
      counts: GenerationCounts;
      grounding_status: GroundingStatus;
    };

export interface GenerationEvent {
  id: number;
  session_id: string;
  event_type: ProgressEventType;
  payload: GenerationEventPayload;
  generation?: GenerationJobPublic | null;
  created_at: string;
}

export interface GenerationJobPublic {
  id: string;
  session_id: string;
  stage: GenerationStage;
  web_search_requested: boolean;
  grounding_status: GroundingStatus;
  counts: GenerationCounts;
  warnings: GenerationWarning[];
  cancel_requested: boolean;
  can_cancel: boolean;
  can_resume: boolean;
  last_event_id: number;
  created_at: string;
  updated_at: string;
}

export interface GenerateCourseAcceptedResponse {
  session: {
    id: string;
    query: string;
    course_title: string;
    title_finalized?: boolean;
    total_nodes?: number;
    completed_nodes?: number;
    nodes?: unknown[];
    [key: string]: unknown;
  };
  generation: GenerationJobPublic;
}

export interface GenerationControlResponse {
  generation: GenerationJobPublic;
}
