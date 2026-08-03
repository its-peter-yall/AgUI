/**
 * ============================================================================
 * FILE: regenApi.ts
 * LOCATION: client/src/lib/regenApi.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Fetch-based SSE streaming client for the node regeneration endpoint.
 *
 * ROLE IN PROJECT:
 *    Dedicated API module for streaming topic content regeneration.
 *    Connects to POST /learning/nodes/{nodeId}/regenerate/stream and streams deltas.
 *
 * KEY COMPONENTS:
 *    - streamRegenerateNode: Connects to streaming endpoint, parses deltas,
 *      handles done and error frames, and invokes callbacks.
 *
 * DEPENDENCIES:
 *    - External: None (native fetch API)
 *    - Internal: @/types/learning, @/lib/providerSettings, @/lib/providerApi
 *
 * USAGE:
 *    ```ts
 *    await streamRegenerateNode({
 *      nodeId: 'node-123',
 *      onDelta: (text) => {},
 *      onDone: (node) => {},
 *      onError: (err) => {},
 *    });
 *    ```
 * ============================================================================
 */

import { getProviderSettings } from "./providerSettings";
import { buildAgentModelHeaders } from "./agentModelHeaders";
import type { ConceptNode } from "@/types/learning";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

interface StreamRegenerateParams {
	nodeId: string;
	onDelta: (delta: string) => void;
	onDone: (updatedNode: ConceptNode) => void;
	onError: (error: Error) => void;
	onStatusChange?: (status: string) => void;
	signal?: AbortSignal;
}

/**
 * Streams a topic content regeneration response from the backend SSE endpoint.
 *
 * Uses native fetch() to consume text/event-stream frames. Each frame
 * contains a JSON payload. Delta frames append text. Done frames return
 * the final node. Error frames raise exceptions.
 */
export async function streamRegenerateNode({
	nodeId,
	onDelta,
	onDone,
	onError,
	onStatusChange,
	signal,
}: StreamRegenerateParams): Promise<void> {
	try {
		const settings = getProviderSettings();
		const providerHeaders = buildAgentModelHeaders(settings);

		const url = `${BASE_URL}/learning/nodes/${nodeId}/regenerate/stream`;

		const response = await fetch(url, {
			method: "POST",
			headers: {
				"Content-Type": "application/json",
				...providerHeaders,
			},
			signal,
		});

		if (!response.ok) {
			throw new Error(
				`Regeneration failed: ${response.status} ${response.statusText}`,
			);
		}

		const reader = response.body?.getReader();
		if (!reader) {
			throw new Error("Response body is not readable");
		}

		const decoder = new TextDecoder();
		let buffer = "";

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
						done?: boolean;
						node?: ConceptNode;
						status?: string;
					};
					if (parsed.error) {
						throw new Error(parsed.error);
					}
					if (parsed.delta) {
						onDelta(parsed.delta);
					}
					if (parsed.status) {
						onStatusChange?.(parsed.status);
					}
					if (parsed.done && parsed.node) {
						onDone(parsed.node);
					}
				} catch (err) {
					console.error("Error parsing SSE line:", err);
					throw err;
				}
			}
		}
	} catch (error: unknown) {
		const err = error instanceof Error ? error : new Error(String(error));
		if (err.name === "AbortError") {
			return;
		}
		onError(err);
	}
}
