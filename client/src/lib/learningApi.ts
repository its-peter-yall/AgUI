/**
 * ============================================================================
 * FILE: learningApi.ts
 * LOCATION: client/src/lib/learningApi.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Typed API client for learning endpoints with explicit secret scoping.
 *
 * ROLE IN PROJECT:
 *    Single source of truth for learning HTTP calls. LLM and search keys attach
 *    only to generate/resume (and regenerateNode keeps LLM headers). Session,
 *    quiz, research, cancel, and delete calls send no provider secrets.
 *
 * KEY COMPONENTS:
 *    - api: Standard axios instance (30s timeout, no secret interceptor)
 *    - generateCourse / resumeGeneration: Explicit LLM + web headers
 *    - getCourseResearch / cancelGeneration / deleteSession
 *
 * DEPENDENCIES:
 *    - External: axios
 *    - Internal: providerSettings, providerApi, webSearchHeaders, types
 *
 * USAGE:
 *    const accepted = await generateCourse({ query: 'CSS' }, { webSearchEnabled: true });
 * ============================================================================
 */

import axios from 'axios';
import { getProviderSettings, getWebSearchSettings } from './providerSettings';
import { buildAgentModelHeaders } from './agentModelHeaders';
import { buildWebSearchHeaders } from './webSearchHeaders';
import type {
  ConceptNode,
  ConceptNodeWithVisibility,
  GenerateCourseRequest,
  LearningSessionWithNodes,
  QuizAttemptHistory,
  RevisionCreateRequest,
  RevisionSessionResponse,
  RevisionSessionWithProgress,
  RevisionNodeProgressWithDetails,
  RevisionSummary,
  RevisionQuizResponse,
  RevisionListResponse,
  QuizSubmitRequest,
  QuizSubmitResponse,
  SessionListResponse,
  TransitionRequest,
  NodeStatus,
  GenerateCourseAcceptedResponse,
  GenerationControlResponse,
} from '../types/learning';
import type { ResearchReport } from '../types/generation';

const baseURL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
  baseURL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000,
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error(
      'API Request Failed:',
      error.config?.url,
      error.response?.data || error.message,
    );
    return Promise.reject(error);
  },
);

export interface GenerateCourseOptions {
  webSearchEnabled?: boolean;
}

function buildLlmHeaders(): Record<string, string> {
  const settings = getProviderSettings();
  const activeConfig = settings.providers[settings.activeProvider];
  if (!activeConfig.apiKey) {
    return { 'Content-Type': 'application/json' };
  }
  return buildAgentModelHeaders(settings);
}

// --- Learning Session ---

export const generateCourse = async (
  data: GenerateCourseRequest,
  options: GenerateCourseOptions = {},
): Promise<GenerateCourseAcceptedResponse> => {
  const webSearchEnabled = options.webSearchEnabled ?? false;
  const headers = {
    ...buildLlmHeaders(),
    ...buildWebSearchHeaders(webSearchEnabled, getWebSearchSettings()),
  };
  const response = await api.post<GenerateCourseAcceptedResponse>(
    '/learning/generate',
    data,
    { headers },
  );
  return response.data;
};

export const getLearningSession = async (
  sessionId: string,
): Promise<LearningSessionWithNodes> => {
  const response = await api.get<LearningSessionWithNodes>(
    `/learning/sessions/${sessionId}`,
  );
  return response.data;
};

export const getCourseResearch = async (
  sessionId: string,
): Promise<ResearchReport> => {
  const response = await api.get<ResearchReport>(
    `/learning/sessions/${sessionId}/research`,
  );
  return response.data;
};

export const cancelGeneration = async (
  sessionId: string,
): Promise<GenerationControlResponse> => {
  const response = await api.post<GenerationControlResponse>(
    `/learning/sessions/${sessionId}/cancel`,
  );
  return response.data;
};

export const resumeGeneration = async (
  sessionId: string,
  options: GenerateCourseOptions = {},
): Promise<GenerationControlResponse> => {
  const webSearchEnabled = options.webSearchEnabled ?? false;
  const headers = {
    ...buildLlmHeaders(),
    ...buildWebSearchHeaders(webSearchEnabled, getWebSearchSettings()),
  };
  const response = await api.post<GenerationControlResponse>(
    `/learning/sessions/${sessionId}/resume`,
    null,
    { headers },
  );
  return response.data;
};

export const createRevisionSession = async (
  sessionId: string,
  data: RevisionCreateRequest,
): Promise<RevisionSessionResponse> => {
  const response = await api.post<RevisionSessionResponse>(
    `/learning/sessions/${sessionId}/revisions`,
    data,
  );
  return response.data;
};

// --- Concept Nodes ---

export const getConceptNode = async (
  nodeId: string,
): Promise<ConceptNodeWithVisibility> => {
  const response = await api.get<ConceptNodeWithVisibility>(
    `/learning/nodes/${nodeId}`,
  );
  return response.data;
};

export const transitionNode = async (
  nodeId: string,
  targetStatus: NodeStatus,
): Promise<ConceptNode> => {
  const response = await api.post<ConceptNode>(
    `/learning/nodes/${nodeId}/transition`,
    { target_status: targetStatus } as TransitionRequest,
  );
  return response.data;
};

// --- Quiz ---

export const submitQuiz = async (
  nodeId: string,
  selectedOptionIds: string[],
  quizIndex?: number,
): Promise<QuizSubmitResponse> => {
  const data: QuizSubmitRequest = {
    selected_option_ids: selectedOptionIds,
    quiz_index: quizIndex ?? 0,
  };
  const response = await api.post<QuizSubmitResponse>(
    `/learning/nodes/${nodeId}/submit-quiz`,
    data,
  );
  return response.data;
};

export const retryQuiz = async (nodeId: string): Promise<ConceptNode> => {
  const response = await api.post<ConceptNode>(
    `/learning/nodes/${nodeId}/retry-quiz`,
  );
  return response.data;
};

export const previousQuiz = async (nodeId: string): Promise<ConceptNode> => {
  const response = await api.post<ConceptNode>(
    `/learning/nodes/${nodeId}/previous-quiz`,
  );
  return response.data;
};

export const getQuizAttempts = async (
  nodeId: string,
): Promise<QuizAttemptHistory> => {
  const response = await api.get<QuizAttemptHistory>(
    `/learning/nodes/${nodeId}/attempts`,
  );
  return response.data;
};

// --- Regenerate ---

export const regenerateNode = async (
  nodeId: string,
  signal?: AbortSignal,
): Promise<ConceptNode> => {
  const response = await api.post<ConceptNode>(
    `/learning/nodes/${nodeId}/regenerate`,
    null,
    { signal, headers: buildLlmHeaders() },
  );
  return response.data;
};

// --- Last Active Node ---

export const updateLastActiveNode = async (
  sessionId: string,
  nodeId: string,
): Promise<void> => {
  await api.patch(`/learning/sessions/${sessionId}/last-active`, {
    node_id: nodeId,
  });
};

// --- Session Listing ---

export interface SessionListParams {
  status?: string;
  sort_by?: string;
  sort_order?: string;
  limit?: number;
  offset?: number;
}

export const getSessionsList = async (
  params?: SessionListParams,
): Promise<SessionListResponse> => {
  const response = await api.get<SessionListResponse>('/learning/sessions', {
    params,
  });
  return response.data;
};

// --- Revision Sessions ---

export const getRevisionSession = async (
  revisionId: string,
): Promise<RevisionSessionWithProgress> => {
  const response = await api.get<RevisionSessionWithProgress>(
    `/learning/revisions/${revisionId}`,
  );
  return response.data;
};

export const markNodeReviewed = async (
  revisionId: string,
  nodeId: string,
): Promise<RevisionNodeProgressWithDetails> => {
  const response = await api.post<RevisionNodeProgressWithDetails>(
    `/learning/revisions/${revisionId}/nodes/${nodeId}/mark-reviewed`,
  );
  return response.data;
};

export const submitRevisionQuiz = async (
  revisionId: string,
  nodeId: string,
  selectedOptionIds: string[],
  quizIndex?: number,
): Promise<RevisionQuizResponse> => {
  const response = await api.post<RevisionQuizResponse>(
    `/learning/revisions/${revisionId}/nodes/${nodeId}/submit-quiz`,
    { selected_option_ids: selectedOptionIds, quiz_index: quizIndex ?? 0 },
  );
  return response.data;
};

export const getRevisionSummary = async (
  revisionId: string,
): Promise<RevisionSummary> => {
  const response = await api.get<RevisionSummary>(
    `/learning/revisions/${revisionId}/summary`,
  );
  return response.data;
};

export const getRevisionsList = async (
  sessionId: string,
  limit?: number,
  offset?: number,
): Promise<RevisionListResponse> => {
  const response = await api.get<RevisionListResponse>(
    `/learning/sessions/${sessionId}/revisions`,
    { params: { limit, offset } },
  );
  return response.data;
};

// --- Delete Session ---

export const deleteSession = async (sessionId: string): Promise<void> => {
  await api.delete(`/learning/sessions/${sessionId}`);
};
