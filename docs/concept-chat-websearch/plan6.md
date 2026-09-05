# Concept Chat Web Search Implementation Plan — Plan 6: ChatPanel Globe, Status, Source Chips

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the TopicInput-style Globe2 toggle, searching status row, source chips, and non-fatal web-search warning to concept-chat `ChatPanel` only.

**Architecture:** `ChatPanel` stays a view. It reads `webSearchEnabled`, `setWebSearchEnabled`, `status`, `warning`, and `messages[].search` from Plan 5 `useConceptChat`. It gates the globe with `hasWebSearchCapability()` (same helper as TopicInput). It does not persist, does not send headers, and does not parse SSE. Empty assistant + `status === "searching"` replaces typing dots with `Searching the web...`. Assistant `search.sources` render as chips; `search.results` never renders.

**Tech Stack:** React 19, TypeScript strict, Vitest, Testing Library, jsdom, Tailwind 4.x, Lucide `Globe2`, framer-motion (already in ChatPanel).

---

## Scope lock

**In scope**

- `client/src/features/learning/ChatPanel.tsx`
- `client/src/features/learning/ChatPanel.test.tsx` (create; no ChatPanel tests exist today)

**Out of scope (do not touch)**

- `useConceptChat.ts`, `chatApi.ts`, `webSearchHeaders.ts`, `types/learning.ts`
- TopicInput, Researcher, Planner, Generator, course Sources panel
- Server files

Plan 5 must already expose the hook contract below. This plan mocks that contract. Do not re-implement persist or SSE here.

## Plan 5 hook contract (consume, do not change)

`useConceptChat(sessionId, nodeId, isCourseComplete)` returns existing fields plus:

```ts
webSearchEnabled: boolean;
setWebSearchEnabled: (next: boolean) => void;
status: "searching" | null;
warning: string | null;
messages: ConceptChatMessage[]; // Plan 1 optional search on assistant
```

```ts
interface ConceptChatMessage {
  role: "user" | "assistant";
  content: string;
  search?: {
    query: string;
    tool_call_id: string;
    results: string;
    sources: { title: string; url: string }[];
  };
}
```

Locked UI rules:

- Globe hidden unless `hasWebSearchCapability()` is true.
- Globe starts from hook value. New node → Plan 5 returns `false` → `aria-pressed="false"`. Reload/restore → Plan 5 returns stored boolean → ChatPanel reflects it. ChatPanel never reads `localStorage`.
- Globe2 left of textarea. Copy TopicInput classes/ARIA pattern. Exact `aria-label`: `Use web search for this chat`. `aria-pressed`. `title` on/off for this chat.
- Searching row: exact text `Searching the web...` when `status === "searching"` and that assistant `content` is empty. Do not show typing dots at the same time.
- Source chips under that assistant message from `search.sources` `{title, url}`. Cleaned `search.results` must not appear as chat text (not in MarkdownRenderer, not as its own bubble).
- Warning visible, non-fatal, exact copy from hook (server string): `Web search unavailable; answering from the concept.`
- Named export only (`export function ChatPanel`). No default export.
- Match ChatPanel source style: tabs, double quotes, existing file header. Tests: tabs, double quotes, named import `{ ChatPanel }`, framer-motion mock like `ConceptCard.test.tsx`.

## File map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `client/src/features/learning/ChatPanel.tsx` | Globe2, searching row, source chips, warning |
| Create | `client/src/features/learning/ChatPanel.test.tsx` | Capability gate, ARIA, searching, chips vs blob, warning |

## Test command

From `client/`:

```bash
npx vitest run src/features/learning/ChatPanel.test.tsx
```

---

### Task 1: Globe2 toggle (capability, ARIA, position, restore)

**Files:**

- Create: `client/src/features/learning/ChatPanel.test.tsx`
- Modify: `client/src/features/learning/ChatPanel.tsx`

- [ ] **Step 1: Write the failing globe tests**

Create `client/src/features/learning/ChatPanel.test.tsx` with this full file (no ChatPanel tests exist; copy ConceptCard motion mock + TopicInput `vi.hoisted` capability mock):

```tsx
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
		status: null as "searching" | null,
		warning: null as string | null,
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
		mocks.hook.status = null;
		mocks.hook.warning = null;
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
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd client
npx vitest run src/features/learning/ChatPanel.test.tsx
```

Expected: FAIL. The unpressed-globe test cannot find `button` name `Use web search for this chat` (`TestingLibraryElementError`). Hidden-capability test may pass on current UI (no globe at all); file still fails on the visible-globe tests. Do not implement yet.

- [ ] **Step 3: Write minimal globe implementation**

In `client/src/features/learning/ChatPanel.tsx`:

1. Add `Globe2` to the lucide import.
2. Import `hasWebSearchCapability` from `@/lib/providerSettings`.
3. Destructure Plan 5 fields from `useConceptChat`.
4. Compute `canUseWebSearch`.
5. Insert Globe2 button left of the textarea. Copy TopicInput classes, swap copy to “this chat”, disable while `isStreaming`.

Import block becomes:

```tsx
import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Send, MessageCircle, Trash2, Globe2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { hasWebSearchCapability } from "@/lib/providerSettings";
import { useConceptChat } from "./useConceptChat";
import { MarkdownRenderer } from "./MarkdownRenderer";
```

Hook destructure + capability (replace the existing `useConceptChat` destructure):

```tsx
	const {
		messages,
		isStreaming,
		error,
		sendMessage,
		clearChat,
		stopStreaming,
		webSearchEnabled,
		setWebSearchEnabled,
	} = useConceptChat(sessionId, nodeId, isCourseComplete);

	const canUseWebSearch = hasWebSearchCapability();
```

Do not destructure `status` or `warning` yet (`noUnusedLocals`). Task 2 adds `status`. Task 4 adds `warning`.

Replace the input row (`<div className="flex items-end gap-2">` that currently starts with `<textarea`) so the globe is the first child:

```tsx
						<div className="flex items-end gap-2">
							{canUseWebSearch && (
								<button
									type="button"
									aria-label="Use web search for this chat"
									aria-pressed={webSearchEnabled}
									title={
										webSearchEnabled
											? "Web search on for this chat"
											: "Web search off for this chat"
									}
									onClick={() => setWebSearchEnabled(!webSearchEnabled)}
									disabled={isStreaming}
									className={cn(
										"inline-flex items-center justify-center h-8 w-8 rounded-md shrink-0",
										"border transition-colors duration-200",
										"focus:outline-none focus:ring-2 focus:ring-primary",
										"disabled:opacity-50 disabled:cursor-not-allowed",
										webSearchEnabled
											? "bg-[#ffb74d]/15 border-[#ffb74d] text-[#ffb74d]"
											: "bg-muted border-border text-muted-foreground hover:text-foreground",
									)}
								>
									<Globe2 className="h-4 w-4" aria-hidden="true" />
								</button>
							)}
							<textarea
								id="chat-input"
								ref={textareaRef}
								value={input}
								onChange={handleInputChange}
								onKeyDown={handleKeyDown}
								placeholder="Ask a question..."
								rows={1}
								className={cn(
									"flex-1 resize-none rounded-lg px-3 py-2 text-sm",
									"bg-muted border border-border text-foreground",
									"placeholder:text-muted-foreground",
									"focus:outline-none focus:ring-2 focus:ring-primary/50",
									"max-h-30",
								)}
								disabled={isStreaming}
							/>
```

Keep the existing send/stop button after the textarea. Do not restyle send. Do not put the globe inside the textarea (TopicInput does; ChatPanel does not).

Update the file header KEY COMPONENTS / DEPENDENCIES to mention Globe2 and `@/lib/providerSettings`. Keep named `export function ChatPanel`. No default export.

Use `#ffb74d` (TopicInput), not `bg-(--cyber-yellow)`, for the globe on-state.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd client
npx vitest run src/features/learning/ChatPanel.test.tsx
```

Expected: PASS. All five Task 1 tests green.

- [ ] **Step 5: Commit**

```bash
git add client/src/features/learning/ChatPanel.test.tsx client/src/features/learning/ChatPanel.tsx
git commit -m "feat(concept-chat): add ChatPanel web-search globe toggle"
```

---

### Task 2: Searching the web row

**Files:**

- Modify: `client/src/features/learning/ChatPanel.test.tsx`
- Modify: `client/src/features/learning/ChatPanel.tsx`

- [ ] **Step 1: Write the failing searching tests**

Append inside `describe("ChatPanel web search")` in `client/src/features/learning/ChatPanel.test.tsx` (same mocks / `renderPanel` / `beforeEach` already in that file):

```tsx
	it("shows Searching the web... when status is searching and assistant content is empty", () => {
		mocks.hook.status = "searching";
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
		mocks.hook.status = null;
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
		mocks.hook.status = "searching";
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd client
npx vitest run src/features/learning/ChatPanel.test.tsx
```

Expected: FAIL on `shows Searching the web...` — `Unable to find an element with the text: Searching the web...`. Typing-dots test should still pass (existing `TypingIndicator` `aria-label="Thinking"`).

- [ ] **Step 3: Write minimal searching-row implementation**

In `client/src/features/learning/ChatPanel.tsx`, add `status` to the `useConceptChat` destructure:

```tsx
	const {
		messages,
		isStreaming,
		error,
		sendMessage,
		clearChat,
		stopStreaming,
		webSearchEnabled,
		setWebSearchEnabled,
		status,
	} = useConceptChat(sessionId, nodeId, isCourseComplete);
```

Inside the `messages.map` assistant branch, replace the empty-content `TypingIndicator` so searching wins only for the last empty assistant when `status === "searching"`.

Replace the assistant inner content block (the `msg.content ? MarkdownRenderer : TypingIndicator` ternary) with:

```tsx
							) : (
								<div className="w-full text-[15px] bg-white dark:bg-muted rounded-lg px-4 py-3 border border-border/10 chat-message-content">
									{msg.content ? (
										<MarkdownRenderer
											content={msg.content}
											className="text-[15px] leading-relaxed max-w-none"
										/>
									) : i === messages.length - 1 &&
									  status === "searching" ? (
										<div
											className="text-sm text-muted-foreground py-1"
											role="status"
										>
											Searching the web...
										</div>
									) : (
										<TypingIndicator />
									)}
								</div>
							)}
```

Do not emit answer text from `search.results`. Do not change user bubbles. Keep `TypingIndicator` for globe-off / no-tool streaming.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd client
npx vitest run src/features/learning/ChatPanel.test.tsx
```

Expected: PASS. Task 1 and Task 2 tests green.

- [ ] **Step 5: Commit**

```bash
git add client/src/features/learning/ChatPanel.test.tsx client/src/features/learning/ChatPanel.tsx
git commit -m "feat(concept-chat): show searching the web status in ChatPanel"
```

---

### Task 3: Source chips and hidden search.results blob

**Files:**

- Modify: `client/src/features/learning/ChatPanel.test.tsx`
- Modify: `client/src/features/learning/ChatPanel.tsx`

- [ ] **Step 1: Write the failing source-chip tests**

Append inside `describe("ChatPanel web search")` in `client/src/features/learning/ChatPanel.test.tsx`:

```tsx
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd client
npx vitest run src/features/learning/ChatPanel.test.tsx
```

Expected: FAIL — `Unable to find an accessible element with the role "link" and name "Widgets docs"`.

- [ ] **Step 3: Write minimal chips implementation**

In `client/src/features/learning/ChatPanel.tsx`, add a module-level helper after `ChatPanelProps` (do not export it):

```tsx
function isSafeHttpUrl(url: string): boolean {
	try {
		const parsed = new URL(url);
		return parsed.protocol === "http:" || parsed.protocol === "https:";
	} catch {
		return false;
	}
}
```

Same idea as `SourceCitations.tsx`. Do not import `SourceCitations` (numbered course citations, different shape).

Under the assistant markdown / searching / typing block, still inside the assistant card `div`, render chips when `msg.search?.sources` has safe titled URLs:

```tsx
								<div className="w-full text-[15px] bg-white dark:bg-muted rounded-lg px-4 py-3 border border-border/10 chat-message-content">
									{msg.content ? (
										<MarkdownRenderer
											content={msg.content}
											className="text-[15px] leading-relaxed max-w-none"
										/>
									) : i === messages.length - 1 &&
									  status === "searching" ? (
										<div
											className="text-sm text-muted-foreground py-1"
											role="status"
										>
											Searching the web...
										</div>
									) : (
										<TypingIndicator />
									)}
									{msg.search && msg.search.sources.length > 0 && (
										<div
											className="mt-2 flex flex-wrap gap-1.5"
											aria-label="Web search sources"
										>
											{msg.search.sources
												.filter(
													(source) =>
														Boolean(source.title) &&
														isSafeHttpUrl(source.url),
												)
												.map((source, sourceIndex) => (
													<a
														key={`${source.url}-${sourceIndex}`}
														href={source.url}
														target="_blank"
														rel="noreferrer noopener"
														className={cn(
															"inline-flex max-w-full items-center truncate rounded-full",
															"border border-border bg-muted px-2 py-0.5 text-xs",
															"text-muted-foreground hover:text-foreground",
															"focus:outline-none focus-visible:ring-2 focus-visible:ring-primary",
														)}
													>
														{source.title}
													</a>
												))}
										</div>
									)}
								</div>
```

Pass only `msg.content` into `MarkdownRenderer`. Never pass `msg.search.results`, `msg.search.query`, or `tool_call_id` into visible text. Do not render a `tool` role. User messages stay content-only.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd client
npx vitest run src/features/learning/ChatPanel.test.tsx
```

Expected: PASS. Blob string absent. Two http(s) chips present. `javascript:` chip absent.

- [ ] **Step 5: Commit**

```bash
git add client/src/features/learning/ChatPanel.test.tsx client/src/features/learning/ChatPanel.tsx
git commit -m "feat(concept-chat): render ChatPanel search source chips"
```

---

### Task 4: Non-fatal web-search warning

**Files:**

- Modify: `client/src/features/learning/ChatPanel.test.tsx`
- Modify: `client/src/features/learning/ChatPanel.tsx`

- [ ] **Step 1: Write the failing warning tests**

Append inside `describe("ChatPanel web search")` in `client/src/features/learning/ChatPanel.test.tsx`:

```tsx
	it("shows the non-fatal web search warning without treating it as a stream error", () => {
		mocks.hook.warning =
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
		mocks.hook.warning =
			"Web search unavailable; answering from the concept.";
		mocks.hook.error = "Chat request failed";
		renderPanel();
		expect(
			screen.getByText("Web search unavailable; answering from the concept."),
		).toBeInTheDocument();
		expect(screen.getByText("Chat request failed")).toBeInTheDocument();
	});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd client
npx vitest run src/features/learning/ChatPanel.test.tsx
```

Expected: FAIL — cannot find `status` / text `Web search unavailable; answering from the concept.`

- [ ] **Step 3: Write minimal warning implementation**

In `client/src/features/learning/ChatPanel.tsx`, add `warning` to the `useConceptChat` destructure:

```tsx
	const {
		messages,
		isStreaming,
		error,
		sendMessage,
		clearChat,
		stopStreaming,
		webSearchEnabled,
		setWebSearchEnabled,
		status,
		warning,
	} = useConceptChat(sessionId, nodeId, isCourseComplete);
```

In the messages log, render `warning` next to the existing `error` block. Warning is not `text-destructive`. Keep error styling unchanged.

Replace:

```tsx
						{error && (
							<div className="text-center text-xs text-destructive py-2">
								{error}
							</div>
						)}
```

with:

```tsx
						{warning && (
							<div
								className="text-center text-xs text-amber-600 dark:text-amber-400 py-2"
								role="status"
							>
								{warning}
							</div>
						)}

						{error && (
							<div className="text-center text-xs text-destructive py-2">
								{error}
							</div>
						)}
```

Render `{warning}` from the hook. Do not hardcode the sentence in the component (tests use the locked server string; the hook supplies it). Do not map warning into `error`. Do not abort the assistant bubble when warning is set.

`getByRole("status", { name: ... })` uses the element text as the accessible name. Warning tests do not set `status === "searching"`, so the warning node is the only `role="status"`.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd client
npx vitest run src/features/learning/ChatPanel.test.tsx
```

Expected: PASS. Entire ChatPanel web-search describe block green.

- [ ] **Step 5: Commit**

```bash
git add client/src/features/learning/ChatPanel.test.tsx client/src/features/learning/ChatPanel.tsx
git commit -m "feat(concept-chat): show ChatPanel web-search warning"
```

---

## Done when

- Globe hidden unless `hasWebSearchCapability()`; unpressed when hook is false; pressed when hook is true.
- Globe2 is left of textarea; TopicInput on/off colors; `aria-label` `Use web search for this chat`; `aria-pressed`; titles `Web search on for this chat` / `Web search off for this chat`; click calls `setWebSearchEnabled(!webSearchEnabled)`; disabled while streaming.
- `Searching the web...` only for last empty assistant + `status === "searching"`; typing dots otherwise.
- Chips from `{title, url}` under the assistant card; `search.results` never in the document.
- Warning string visible and non-fatal; fatal `error` still renders.
- Named `ChatPanel` export. No `chatApi` / hook persist code in this plan.
- `npx vitest run src/features/learning/ChatPanel.test.tsx` passes.
