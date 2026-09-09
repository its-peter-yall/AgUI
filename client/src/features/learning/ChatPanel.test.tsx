/**
 * ============================================================================
 * FILE: ChatPanel.test.tsx
 * LOCATION: client/src/features/learning/ChatPanel.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Tests concept-chat globe toggle, searching status, source chips, and
 *    non-fatal web-search warning in ChatPanel.
 *
 * ROLE IN PROJECT:
 *    Guards Plan 6 UI against TopicInput globe drift and against rendering
 *    cleaned search.results as chat text.
 *
 * KEY COMPONENTS:
 *    - ChatPanel web-search interaction tests
 *
 * DEPENDENCIES:
 *    - External: @testing-library/react, vitest
 *    - Internal: ChatPanel, mocked useConceptChat, mocked hasWebSearchCapability
 *
 * USAGE:
 *    npx vitest run src/features/learning/ChatPanel.test.tsx
 * ============================================================================
 */

import type { ReactNode, ComponentPropsWithoutRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChatPanel } from "./ChatPanel";
import type { ConceptChatMessage } from "@/types/learning";

const mocks = vi.hoisted(() => ({
	capability: true,
	hook: {
		messages: [] as ConceptChatMessage[],
		isStreaming: false,
		error: null as string | null,
		sendMessage: vi.fn(),
		clearChat: vi.fn(),
		resetChat: vi.fn(),
		stopStreaming: vi.fn(),
		webSearchEnabled: false,
		setWebSearchEnabled: vi.fn(),
		streamingStatus: null as "searching" | null,
		streamingWarning: null as string | null,
	},
}));

vi.mock("framer-motion", () => ({
	motion: {
		div: ({
			children,
			...props
		}: ComponentPropsWithoutRef<"div">) => <div {...props}>{children}</div>,
	},
	AnimatePresence: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/providerSettings", () => ({
	hasWebSearchCapability: () => mocks.capability,
}));

vi.mock("./useConceptChat", () => ({
	useConceptChat: () => mocks.hook,
}));

vi.mock("./MarkdownRenderer", () => ({
	MarkdownRenderer: ({ content }: { content: string }) => (
		<div data-testid="markdown">{content}</div>
	),
}));

window.HTMLElement.prototype.scrollIntoView = vi.fn();

function renderPanel() {
	return render(
		<ChatPanel
			isOpen={true}
			onClose={vi.fn()}
			sessionId="session-1"
			nodeId="node-1"
		/>,
	);
}

describe("ChatPanel web search", () => {
	beforeEach(() => {
		mocks.capability = true;
		mocks.hook.messages = [];
		mocks.hook.isStreaming = false;
		mocks.hook.error = null;
		mocks.hook.webSearchEnabled = false;
		mocks.hook.streamingStatus = null;
		mocks.hook.streamingWarning = null;
		mocks.hook.sendMessage.mockReset();
		mocks.hook.clearChat.mockReset();
		mocks.hook.resetChat.mockReset();
		mocks.hook.stopStreaming.mockReset();
		mocks.hook.setWebSearchEnabled.mockReset();
	});

	it("hides the globe when web search capability is unavailable", () => {
		mocks.capability = false;
		renderPanel();
		expect(
			screen.queryByRole("button", { name: "Use web search for this chat" }),
		).not.toBeInTheDocument();
	});

	it("shows the globe unpressed when capability exists and hook starts OFF", () => {
		renderPanel();
		const globe = screen.getByRole("button", {
			name: "Use web search for this chat",
		});
		expect(globe).toHaveAttribute("aria-pressed", "false");
		expect(globe).toHaveAttribute("title", "Web search off for this chat");
	});

	it("restores pressed globe from hook persist without reading localStorage", () => {
		mocks.hook.webSearchEnabled = true;
		renderPanel();
		const globe = screen.getByRole("button", {
			name: "Use web search for this chat",
		});
		expect(globe).toHaveAttribute("aria-pressed", "true");
		expect(globe).toHaveAttribute("title", "Web search on for this chat");
	});

	it("places the globe left of the textarea and toggles via the hook setter", () => {
		renderPanel();
		const globe = screen.getByRole("button", {
			name: "Use web search for this chat",
		});
		const textarea = screen.getByPlaceholderText("Ask a question...");
		const row = textarea.parentElement;
		expect(row).not.toBeNull();
		const children = Array.from(row ? row.children : []);
		expect(children.indexOf(globe)).toBeGreaterThan(-1);
		expect(children.indexOf(textarea)).toBeGreaterThan(-1);
		expect(children.indexOf(globe)).toBeLessThan(children.indexOf(textarea));
		fireEvent.click(globe);
		expect(mocks.hook.setWebSearchEnabled).toHaveBeenCalledWith(true);
	});

	it("disables the globe while streaming", () => {
		mocks.hook.isStreaming = true;
		renderPanel();
		expect(
			screen.getByRole("button", { name: "Use web search for this chat" }),
		).toBeDisabled();
	});

	it("shows Searching the web... when status is searching and assistant content is empty", () => {
		mocks.hook.streamingStatus = "searching";
		mocks.hook.isStreaming = true;
		mocks.hook.messages = [
			{ role: "user", content: "What is the current API?" },
			{ role: "assistant", content: "" },
		];
		renderPanel();
		expect(screen.getByText("Searching the web...")).toBeInTheDocument();
		expect(screen.queryByLabelText("Thinking")).not.toBeInTheDocument();
	});

	it("keeps typing dots when streaming without searching status", () => {
		mocks.hook.streamingStatus = null;
		mocks.hook.isStreaming = true;
		mocks.hook.messages = [
			{ role: "user", content: "Explain this heading" },
			{ role: "assistant", content: "" },
		];
		renderPanel();
		expect(screen.getByLabelText("Thinking")).toBeInTheDocument();
		expect(screen.queryByText("Searching the web...")).not.toBeInTheDocument();
	});

	it("does not show Searching the web... once assistant content exists", () => {
		mocks.hook.streamingStatus = "searching";
		mocks.hook.messages = [
			{ role: "user", content: "What is the current API?" },
			{ role: "assistant", content: "The current API uses widgets." },
		];
		renderPanel();
		expect(screen.queryByText("Searching the web...")).not.toBeInTheDocument();
		expect(screen.getByTestId("markdown")).toHaveTextContent(
			"The current API uses widgets.",
		);
	});

	it("renders source chips from search.sources and never shows search.results as chat text", () => {
		mocks.hook.messages = [
			{ role: "user", content: "What is the current API?" },
			{
				role: "assistant",
				content: "The current API uses widgets.",
				search: {
					query: "widgets current API",
					tool_call_id: "call_1",
					results:
						"WEB SEARCH RESULTS for: \"widgets current API\"\nUNIQUE_SEARCH_BLOB_NOT_FOR_UI",
					sources: [
						{
							title: "Widgets docs",
							url: "https://example.com/widgets",
						},
						{
							title: "API changelog",
							url: "https://example.com/changelog",
						},
					],
				},
			},
		];
		renderPanel();
		const docs = screen.getByRole("link", { name: "Widgets docs" });
		expect(docs).toHaveAttribute("href", "https://example.com/widgets");
		expect(docs).toHaveAttribute("target", "_blank");
		expect(docs).toHaveAttribute("rel", "noreferrer noopener");
		expect(
			screen.getByRole("link", { name: "API changelog" }),
		).toHaveAttribute("href", "https://example.com/changelog");
		expect(screen.getByTestId("markdown")).toHaveTextContent(
			"The current API uses widgets.",
		);
		expect(screen.getByTestId("markdown")).not.toHaveTextContent(
			"UNIQUE_SEARCH_BLOB_NOT_FOR_UI",
		);
		expect(
			screen.queryByText(/UNIQUE_SEARCH_BLOB_NOT_FOR_UI/),
		).not.toBeInTheDocument();
		expect(
			screen.queryByText(/WEB SEARCH RESULTS/),
		).not.toBeInTheDocument();
	});

	it("does not render unsafe or empty source chips", () => {
		mocks.hook.messages = [
			{
				role: "assistant",
				content: "Answer from the concept.",
				search: {
					query: "q",
					tool_call_id: "call_2",
					results: "UNIQUE_SEARCH_BLOB_NOT_FOR_UI",
					sources: [
						{
							title: "Evil",
							url: "javascript:alert(1)",
						},
						{
							title: "",
							url: "https://example.com/ok",
						},
						{
							title: "Safe source",
							url: "https://example.com/safe",
						},
					],
				},
			},
		];
		renderPanel();
		expect(screen.getByRole("link", { name: "Safe source" })).toHaveAttribute(
			"href",
			"https://example.com/safe",
		);
		expect(screen.queryByRole("link", { name: "Evil" })).not.toBeInTheDocument();
		expect(
			screen.queryByRole("link", { name: "" }),
		).not.toBeInTheDocument();
	});

	it("shows the non-fatal web search warning without treating it as a stream error", () => {
		mocks.hook.streamingWarning =
			"Web search unavailable; answering from the concept.";
		mocks.hook.error = null;
		mocks.hook.messages = [
			{ role: "user", content: "What is the current API?" },
			{ role: "assistant", content: "Answering from the concept card." },
		];
		renderPanel();
		expect(
			screen.getByRole("status", {
				name: "Web search unavailable; answering from the concept.",
			}),
		).toBeInTheDocument();
		expect(screen.getByTestId("markdown")).toHaveTextContent(
			"Answering from the concept card.",
		);
		expect(screen.queryByText("Chat request failed")).not.toBeInTheDocument();
	});

	it("still shows a fatal stream error separately from the warning", () => {
		mocks.hook.streamingWarning =
			"Web search unavailable; answering from the concept.";
		mocks.hook.error = "Chat request failed";
		renderPanel();
		expect(
			screen.getByText("Web search unavailable; answering from the concept."),
		).toBeInTheDocument();
		expect(screen.getByText("Chat request failed")).toBeInTheDocument();
	});
});
