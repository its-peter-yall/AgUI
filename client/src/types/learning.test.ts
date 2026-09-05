/**
 * ============================================================================
 * FILE: learning.test.ts
 * LOCATION: client/src/types/learning.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Contract tests for concept-chat search blobs and stream chunks.
 *
 * ROLE IN PROJECT:
 *    Locks the client TypeScript shapes that mirror ConceptChatMessage
 *    and additive SSE fields before chatApi / ChatPanel consume them.
 *
 * KEY COMPONENTS:
 *    - ConceptChatMessage search optional blob
 *    - ConceptChatStreamChunk status / search / warning
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: ./learning
 *
 * USAGE:
 *    npx vitest run src/types/learning.test.ts
 * ============================================================================
 */

import { describe, expect, it } from 'vitest';
import type {
  ConceptChatMessage,
  ConceptChatSearch,
  ConceptChatSearchSource,
  ConceptChatStreamChunk,
} from './learning';

const sampleSource: ConceptChatSearchSource = {
  title: 'LangChain docs',
  url: 'https://python.langchain.com',
};

const sampleSearch: ConceptChatSearch = {
  query: 'LangChain BaseTool documentation',
  tool_call_id: 'call_abc123',
  results: 'WEB SEARCH RESULTS for: "LangChain BaseTool documentation"',
  sources: [sampleSource],
};

describe('ConceptChatMessage search contract', () => {
  it('accepts optional search on an assistant message', () => {
    const msg: ConceptChatMessage = {
      role: 'assistant',
      content: 'Here is the answer.',
      search: sampleSearch,
    };
    expect(msg.role).toBe('assistant');
    expect(msg.content).toBe('Here is the answer.');
    expect(msg.search?.query).toBe(
      'LangChain BaseTool documentation',
    );
    expect(msg.search?.tool_call_id).toBe('call_abc123');
    expect(msg.search?.results).toContain('WEB SEARCH RESULTS');
    expect(msg.search?.sources).toEqual([
      {
        title: 'LangChain docs',
        url: 'https://python.langchain.com',
      },
    ]);
  });

  it('parses old localStorage messages without search', () => {
    const raw = JSON.parse(
      '{"role":"user","content":"hello"}',
    ) as ConceptChatMessage;
    expect(raw.role).toBe('user');
    expect(raw.content).toBe('hello');
    expect(raw.search).toBeUndefined();
  });

  it('keeps role and content when unknown extras are present', () => {
    const raw = JSON.parse(
      '{"role":"user","content":"hello","timestamp":1}',
    ) as ConceptChatMessage;
    expect(raw.role).toBe('user');
    expect(raw.content).toBe('hello');
    expect(raw.search).toBeUndefined();
  });

  it('does not allow a tool role on the message type', () => {
    const msg: ConceptChatMessage = {
      role: 'user',
      content: 'question',
    };
    expect(msg.role === 'user' || msg.role === 'assistant').toBe(
      true,
    );
    expect(msg.role).not.toBe('tool');
  });
});

describe('ConceptChatStreamChunk additive fields', () => {
  it('keeps existing delta and error fields', () => {
    const deltaChunk: ConceptChatStreamChunk = { delta: 'Hello' };
    const errorChunk: ConceptChatStreamChunk = { error: 'boom' };
    expect(deltaChunk.delta).toBe('Hello');
    expect(errorChunk.error).toBe('boom');
  });

  it('accepts optional status searching', () => {
    const chunk: ConceptChatStreamChunk = { status: 'searching' };
    expect(chunk.status).toBe('searching');
  });

  it('accepts optional search payload', () => {
    const chunk: ConceptChatStreamChunk = { search: sampleSearch };
    expect(chunk.search?.query).toBe(
      'LangChain BaseTool documentation',
    );
    expect(chunk.search?.sources[0]?.title).toBe('LangChain docs');
  });

  it('accepts optional warning string', () => {
    const chunk: ConceptChatStreamChunk = {
      warning:
        'Web search unavailable; answering from the concept.',
    };
    expect(chunk.warning).toBe(
      'Web search unavailable; answering from the concept.',
    );
  });
});
