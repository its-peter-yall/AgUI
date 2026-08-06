/**
 * ============================================================================
 * FILE: RevisionPage.test.tsx
 * LOCATION: client/src/features/learning/RevisionPage.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Unit tests for RevisionPage and RevisionConceptCard multi-quiz behavior.
 *
 * ROLE IN PROJECT:
 *    Verifies rendering and interactivity of Table of Contents button,
 *    Concept Chatbot FAB, and multi-quiz pagination in Revision mode.
 *
 * KEY COMPONENTS:
 *    - RevisionPage component tests
 *    - RevisionConceptCard multi-quiz tests
 *
 * DEPENDENCIES:
 *    - External: @testing-library/react, vitest, react-router-dom, @tanstack/react-query
 *    - Internal: ./RevisionPage, ./RevisionConceptCard
 *
 * USAGE:
 *    npx vitest run src/features/learning/RevisionPage.test.tsx
 * ============================================================================
 */

import type { ReactNode, ComponentPropsWithoutRef } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, test, expect, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RevisionPage } from "./RevisionPage";
import { RevisionConceptCard } from "./RevisionConceptCard";
import type {
	ConceptNode,
	LearningSessionWithNodes,
	RevisionSessionWithProgress,
} from "@/types/learning";

// Mock framer-motion to avoid animation issues in jsdom environment
vi.mock("framer-motion", () => ({
	motion: {
		div: ({ children, ...props }: ComponentPropsWithoutRef<"div">) => <div {...props}>{children}</div>,
		article: ({ children, ...props }: ComponentPropsWithoutRef<"article">) => <article {...props}>{children}</article>,
	},
	AnimatePresence: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

const mockNodeWithQuizSet: ConceptNode = {
	id: "node-1",
	learning_session_id: "session-1",
	sequence_index: 0,
	title: "Knowledge Graphs 101",
	content_markdown: "Knowledge graph overview...",
	status: "COMPLETED",
	error_message: null,
	retry_available: false,
	complexity: "Basic",
	created_at: "2026-08-01T00:00:00Z",
	updated_at: "2026-08-01T00:00:00Z",
	quiz: null,
	quiz_set: {
		quizzes: [
			{
				question_text: "What is an entity?",
				question_type: "single_choice",
				difficulty: "easy",
				options: [
					{ option_id: "opt-1", text: "A node", display_label: "A", explanation: "Correct", is_correct: true },
					{ option_id: "opt-2", text: "A line", display_label: "B", explanation: "Incorrect", is_correct: false },
				],
			},
			{
				question_text: "What is a relation?",
				question_type: "single_choice",
				difficulty: "easy",
				options: [
					{ option_id: "opt-3", text: "An edge", display_label: "A", explanation: "Correct", is_correct: true },
					{ option_id: "opt-4", text: "A vertex", display_label: "B", explanation: "Incorrect", is_correct: false },
				],
			},
		],
		current_index: 0,
		shuffle_seed: null,
	},
	quiz_hidden: null,
	quiz_set_hidden: null,
};

const mockOriginalSession: LearningSessionWithNodes = {
	id: "session-1",
	query: "Knowledge Graphs",
	course_title: "Mastering Knowledge Graphs",
	user_id: "user-1",
	total_nodes: 1,
	completed_nodes: 1,
	last_active_node_id: "node-1",
	created_at: "2026-08-01T00:00:00Z",
	updated_at: "2026-08-01T00:00:00Z",
	nodes: [mockNodeWithQuizSet],
};

const mockRevisionSession: RevisionSessionWithProgress = {
	id: "rev-1",
	original_session_id: "session-1",
	mode: "full_review",
	status: "in_progress",
	revision_number: 1,
	progress_percent: 0,
	total_quiz_score_percent: null,
	started_at: "2026-08-06T00:00:00Z",
	completed_at: null,
	nodes: [
		{
			id: "rev-node-1",
			node_id: "node-1",
			node_title: "Knowledge Graphs 101",
			sequence_index: 0,
			status: "pending",
			reviewed_at: null,
		},
	],
};

vi.mock("@/lib/learningApi", () => ({
	getLearningSession: vi.fn(() => Promise.resolve(mockOriginalSession)),
	getRevisionSummary: vi.fn(),
	createRevisionSession: vi.fn(),
	markNodeReviewed: vi.fn(),
	submitRevisionQuiz: vi.fn(),
}));

vi.mock("./useRevisionSession", () => ({
	useRevisionSession: () => ({
		data: mockRevisionSession,
		isLoading: false,
		isError: false,
	}),
	revisionQueryKeys: {
		session: (id: string) => ["revisionSession", id],
	},
}));

function renderWithProviders(ui: ReactNode) {
	const queryClient = new QueryClient({
		defaultOptions: { queries: { retry: false } },
	});
	return render(
		<QueryClientProvider client={queryClient}>
			{ui}
		</QueryClientProvider>,
	);
}

describe("RevisionConceptCard Multi-Quiz Navigation", () => {
	test("renders multi-quiz pagination and allows stepping between Quiz 1 and Quiz 2", () => {
		const handleQuizSubmit = vi.fn();
		renderWithProviders(
			<RevisionConceptCard
				node={mockNodeWithQuizSet}
				revisionMode="full_review"
				revisionProgress={mockRevisionSession.nodes[0]}
				onMarkReviewed={vi.fn()}
				onQuizSubmit={handleQuizSubmit}
			/>,
		);

		// Verify Quiz 1 of 2 header is visible
		expect(screen.getByText(/Quiz 1 of 2/i)).toBeInTheDocument();
		expect(screen.getByText(/What is an entity\?/i)).toBeInTheDocument();

		// Click Next Quiz button
		const nextBtn = screen.getByRole("button", { name: "Next quiz" });
		fireEvent.click(nextBtn);

		// Verify Quiz 2 of 2 is displayed
		expect(screen.getByText(/Quiz 2 of 2/i)).toBeInTheDocument();
		expect(screen.getByText(/What is a relation\?/i)).toBeInTheDocument();

		// Click Previous Quiz button
		const prevBtn = screen.getByRole("button", { name: "Previous quiz" });
		fireEvent.click(prevBtn);

		// Verify back on Quiz 1 of 2
		expect(screen.getByText(/Quiz 1 of 2/i)).toBeInTheDocument();
	});
});

describe("RevisionPage UI Components", () => {
	test("renders Table of Contents button and Chat FAB button", async () => {
		renderWithProviders(
			<MemoryRouter initialEntries={["/learn/session-1/revise/rev-1"]}>
				<Routes>
					<Route
						path="/learn/:sessionId/revise/:revisionId"
						element={<RevisionPage />}
					/>
				</Routes>
			</MemoryRouter>,
		);

		// Verify TOC button is present
		const tocBtn = await screen.findByTestId("toc-button");
		expect(tocBtn).toBeInTheDocument();
		expect(screen.getByText("Table of Contents")).toBeInTheDocument();

		// Verify Chat FAB button is present
		const chatFab = screen.getByTestId("revision-chat-fab");
		expect(chatFab).toBeInTheDocument();
	});
});
