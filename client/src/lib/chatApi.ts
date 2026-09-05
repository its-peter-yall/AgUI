/**
 * ============================================================================
 * FILE: chatApi.ts
 * LOCATION: client/src/lib/chatApi.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Provides fetch-based SSE streaming client for the concept chat endpoint.
 *    Uses native fetch() with ReadableStream to consume server-sent events.
 *
 * ROLE IN PROJECT:
 *    Dedicated API module for the concept chatbot feature. Separate from the
 *    Axios-based learningApi.ts because SSE streaming requires direct
 *    ReadableStream consumption, which Axios does not support natively.
 *
 * KEY COMPONENTS:
 *    - streamConceptChat(): Streams chat deltas from the backend SSE endpoint
 *    - webSearchEnabled: Optional globe flag; attaches X-Web-Search* headers
 *
 * DEPENDENCIES:
 *    - External: None (native fetch API)
 *    - Internal: @/types/learning, @/lib/providerSettings, @/lib/providerApi,
 *      @/lib/webSearchHeaders
 *
 * USAGE:
 *    ```ts
 *    await streamConceptChat({
 *      sessionId: 'abc',
 *      nodeId: 'def',
 *      message: 'Explain this',
 *      history: [],
 *      selectedHeadingIds: ['h-1'],
 *      webSearchEnabled: true,
 *      onDelta: (text) => setBuffer((prev) => prev + text),
 *      signal: abortController.signal,
 *    });
 *    ```
 * ============================================================================
 */

import { getProviderSettings } from "./providerSettings";
import { buildProviderHeaders } from "./providerApi";
import type { ConceptChatMessage } from "@/types/learning";
import {
	buildWebSearchHeaders,
	WebSearchConfigurationError,
} from "./webSearchHeaders";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

interface StreamConceptChatParams {
	sessionId: string;
	nodeId: string;
	message: string;
	history: ConceptChatMessage[];
	selectedHeadingIds: string[];
	onDelta: (delta: string) => void;
	webSearchEnabled?: boolean;
	onStatus?: (status: string) => void;
	onSearch?: (
		search: NonNullable<ConceptChatMessage["search"]>,
	) => void;
	onWarning?: (warning: string) => void;
	signal?: AbortSignal;
}

/**
 * Streams a concept chat response from the backend SSE endpoint.
 *
 * Uses native fetch() to consume text/event-stream frames. Each frame
 * contains a JSON payload with a `delta` string. Reading stops when
 * the server sends the `[DONE]` sentinel.
 */
export async function streamConceptChat({
	sessionId,
	nodeId,
	message,
	history,
	selectedHeadingIds,
	onDelta,
	webSearchEnabled = false,
	signal,
}: StreamConceptChatParams): Promise<void> {
	const settings = getProviderSettings();
	const activeConfig = settings.providers[settings.activeProvider];

	const chatProvider = activeConfig.chatModelProvider ?? settings.activeProvider;
	const chatProviderConfig = settings.providers[chatProvider];

	const chatModel =
		activeConfig.chatModel ||
		chatProviderConfig.model ||
		settings.providers[settings.activeProvider].model ||
		"";

	const chatThinking =
		chatProvider === "openrouter" ? activeConfig.chatThinking : undefined;

	const providerHeaders = buildProviderHeaders(
		chatProvider,
		chatProviderConfig.apiKey,
		chatModel || chatProviderConfig.model || undefined,
		chatThinking,
		chatProviderConfig.maxCompletionTokens,
	);

	const url = `${BASE_URL}/learning/sessions/${sessionId}/nodes/${nodeId}/chat`;

	const headers: Record<string, string> = {
		"Content-Type": "application/json",
		...providerHeaders,
		"X-Provider-Api-Key": chatProviderConfig.apiKey,
		"X-Model": chatProviderConfig.model || "",
		"X-Chat-Model": chatModel,
	};

	if (webSearchEnabled) {
		try {
			Object.assign(headers, buildWebSearchHeaders(true));
		} catch (err) {
			if (err instanceof WebSearchConfigurationError) {
				throw err;
			}
			throw err;
		}
	}

	const response = await fetch(url, {
		method: "POST",
		headers,
		body: JSON.stringify({
			message,
			history,
			selected_heading_ids: selectedHeadingIds,
		}),
		signal,
	});

	if (!response.ok) {
		throw new Error(
			`Chat request failed: ${response.status} ${response.statusText}`,
		);
	}

	const reader = response.body?.getReader();
	if (!reader) {
		throw new Error("Response body is not readable");
	}

	const decoder = new TextDecoder();
	let buffer = "";

	try {
		while (true) {
			const { done, value } = await reader.read();
			if (done) break;

			buffer += decoder.decode(value, { stream: true });
			const lines = buffer.split("\n");
			// Keep last incomplete line in buffer
			buffer = lines.pop() ?? "";

			for (const line of lines) {
				const trimmed = line.trim();
				if (!trimmed || !trimmed.startsWith("data: ")) continue;

				const payload = trimmed.slice(6);
				if (payload === "[DONE]") return;

				try {
					const parsed = JSON.parse(payload) as {
						delta?: string;
						error?: string;
					};
					if (parsed.error) {
						throw new Error(parsed.error);
					}
					if (parsed.delta) {
						onDelta(parsed.delta);
					}
				} catch (e) {
					// Re-throw streaming errors, skip malformed JSON
					if (
						e instanceof Error &&
						e.message !== "Unexpected end of JSON input"
					) {
						throw e;
					}
				}
			}
		}
	} finally {
		reader.releaseLock();
	}
}
