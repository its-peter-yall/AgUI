/**
 * ============================================================================
 * FILE: learningApi.test.ts
 * LOCATION: client/src/lib/learningApi.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Tests progressive learning API endpoints and secret header scope.
 *
 * ROLE IN PROJECT:
 *    Guards that AI/search keys attach only to generate/resume paths.
 *
 * KEY COMPONENTS:
 *    - Endpoint secret-scope matrix
 *    - generate/resume header attachment
 *
 * DEPENDENCIES:
 *    - External: vitest, axios
 *    - Internal: learningApi, providerSettings
 *
 * USAGE:
 *    npm run test -- --run src/lib/learningApi.test.ts
 * ============================================================================
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { InternalAxiosRequestConfig } from 'axios';

const mocks = vi.hoisted(() => {
  let lastConfig: InternalAxiosRequestConfig | undefined;
  const handlers: {
    get?: (url: string, config?: InternalAxiosRequestConfig) => Promise<unknown>;
    post?: (
      url: string,
      data?: unknown,
      config?: InternalAxiosRequestConfig,
    ) => Promise<unknown>;
    delete?: (
      url: string,
      config?: InternalAxiosRequestConfig,
    ) => Promise<unknown>;
    patch?: (
      url: string,
      data?: unknown,
      config?: InternalAxiosRequestConfig,
    ) => Promise<unknown>;
  } = {};

  const record = (config?: InternalAxiosRequestConfig) => {
    lastConfig = config;
  };

  const instance = {
    get: vi.fn(async (url: string, config?: InternalAxiosRequestConfig) => {
      record(config);
      if (handlers.get) return handlers.get(url, config);
      return { data: { id: 'session-1', nodes: [] } };
    }),
    post: vi.fn(
      async (
        url: string,
        data?: unknown,
        config?: InternalAxiosRequestConfig,
      ) => {
        record(config);
        if (handlers.post) return handlers.post(url, data, config);
        if (url === '/learning/generate') {
          return {
            data: {
              session: { id: 'session-1', query: 'Topic', course_title: 'Topic' },
              generation: { id: 'job-1', stage: 'INITIALIZING', last_event_id: 0 },
            },
          };
        }
        if (url.includes('/resume') || url.includes('/cancel')) {
          return {
            data: {
              generation: { id: 'job-1', stage: 'PAUSED', last_event_id: 1 },
            },
          };
        }
        return { data: {} };
      },
    ),
    delete: vi.fn(async (url: string, config?: InternalAxiosRequestConfig) => {
      record(config);
      if (handlers.delete) return handlers.delete(url, config);
      return { data: undefined };
    }),
    patch: vi.fn(
      async (
        url: string,
        data?: unknown,
        config?: InternalAxiosRequestConfig,
      ) => {
        record(config);
        if (handlers.patch) return handlers.patch(url, data, config);
        return { data: {} };
      },
    ),
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  };

  return {
    instance,
    lastRequestConfig: () => lastConfig,
    resetLast: () => {
      lastConfig = undefined;
    },
  };
});

vi.mock('axios', () => ({
  default: {
    create: () => mocks.instance,
    isAxiosError: () => false,
  },
}));

vi.mock('./providerSettings', () => ({
  getProviderSettings: () => ({
    activeProvider: 'openrouter',
    providers: {
      openrouter: {
        apiKey: 'llm-secret',
        model: 'test/model',
        modelTitle: 'Test',
        thinking: { enabled: false, effort: 'high' },
        agentModels: {
          researcher: {
            modelId: 'r-model',
            modelProvider: 'openrouter',
          },
          planner: {
            modelId: 'p-model',
            modelProvider: 'openrouter',
          },
          generator: {
            modelId: 'g-model',
            modelProvider: 'openrouter',
          },
          quizzer: {
            modelId: 'q-model',
            modelProvider: 'openrouter',
          },
        },
      },
      generalcompute: { apiKey: '', model: '', modelTitle: '' },
    },
  }),
  areAgentModelsConfigured: () => true,
  getWebSearchSettings: () => ({
    masterEnabled: true,
    providers: {
      tavily: { apiKey: 'tvly-secret', enabled: true },
      exa: { apiKey: '', enabled: false },
      brave: { apiKey: '', enabled: false },
      serpapi: { apiKey: '', enabled: false },
    },
  }),
}));

import {
  cancelGeneration,
  deleteSession,
  generateCourse,
  getCourseResearch,
  getLearningSession,
  resumeGeneration,
} from './learningApi';

function lastRequestConfig() {
  return mocks.lastRequestConfig();
}

describe('learningApi secret scope', () => {
  beforeEach(() => {
    mocks.resetLast();
    mocks.instance.get.mockClear();
    mocks.instance.post.mockClear();
    mocks.instance.delete.mockClear();
  });

  it.each([
    ['getLearningSession', () => getLearningSession('session-1')],
    ['getCourseResearch', () => getCourseResearch('session-1')],
    ['cancelGeneration', () => cancelGeneration('session-1')],
    ['deleteSession', () => deleteSession('session-1')],
  ])('%s sends no AI or search key headers', async (_name, invoke) => {
    await invoke();
    const headers = lastRequestConfig()?.headers ?? {};
    expect(JSON.stringify(headers)).not.toMatch(
      /X-OpenRouter-Key|X-GeneralCompute-Key|X-Tavily-Key|X-Exa-Key|X-Brave-Key|X-SerpApi-Key/i,
    );
  });

  it('generate and resume attach fresh AI and selected search headers', async () => {
    await generateCourse({ query: 'Topic' }, { webSearchEnabled: true });
    expect(lastRequestConfig()?.headers).toMatchObject({
      'X-OpenRouter-Key': 'llm-secret',
      'X-Web-Search': 'true',
      'X-Tavily-Key': 'tvly-secret',
    });
    await resumeGeneration('session-1', { webSearchEnabled: true });
    expect(lastRequestConfig()?.headers).toMatchObject({
      'X-OpenRouter-Key': 'llm-secret',
      'X-Web-Search': 'true',
      'X-Tavily-Key': 'tvly-secret',
    });
  });

  it('generate attaches per-role agent model headers', async () => {
    await generateCourse({ query: 'Topic' }, { webSearchEnabled: false });
    const headers = lastRequestConfig()?.headers ?? {};
    expect(headers).toMatchObject({
      'X-Researcher-Model': expect.any(String),
      'X-Planner-Model': expect.any(String),
      'X-Generator-Model': expect.any(String),
      'X-Quizzer-Model': expect.any(String),
    });
  });
});
