/**
 * ============================================================================
 * FILE: ConceptCard.test.tsx
 * LOCATION: client/src/features/learning/ConceptCard.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Unit tests for the ConceptCard component.
 *
 * ROLE IN PROJECT:
 *    Verifies rendering and interactivity of the ConceptCard component,
 *    specifically checking confirmation dialogs and skeleton loading.
 *
 * KEY COMPONENTS:
 *    - ConceptCard rendering tests
 *
 * DEPENDENCIES:
 *    - External: @testing-library/react, vitest
 *    - Internal: ./ConceptCard
 *
 * USAGE:
 *    npm run test
 * ============================================================================
 */

import type { ReactNode, ComponentPropsWithoutRef } from "react";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, test, expect, vi } from "vitest";
import { ConceptCard } from "./ConceptCard";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ConceptNode } from "@/types/learning";

// Mock framer-motion to avoid animation issues in jsdom environment
vi.mock("framer-motion", () => ({
	motion: {
		div: ({ children, ...props }: ComponentPropsWithoutRef<"div">) => <div {...props}>{children}</div>,
		article: ({ children, ...props }: ComponentPropsWithoutRef<"article">) => <article {...props}>{children}</article>,
	},
	AnimatePresence: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

// Mock the streamRegenerateNode API
vi.mock("@/lib/regenApi", () => ({
	streamRegenerateNode: vi.fn(),
}));

const mockNode: ConceptNode = {
	id: "node-1",
	learning_session_id: "session-1",
	sequence_index: 0,
	title: "Introduction to AI",
	content_markdown: "Artificial Intelligence is...",
	status: "VIEWING_EXPLANATION",
	error_message: null,
	retry_available: false,
	complexity: "Basic",
	quiz: null,
	quiz_set: null,
	quiz_hidden: null,
	quiz_set_hidden: null,
	created_at: "2026-01-01T00:00:00Z",
	updated_at: null,
};

function renderWithProviders(ui: React.ReactElement) {
	const queryClient = new QueryClient({
		defaultOptions: {
			queries: {
				retry: false,
			},
		},
	});
	return render(
		<QueryClientProvider client={queryClient}>
			{ui}
		</QueryClientProvider>
	);
}

describe("ConceptCard Component", () => {
	test("renders the concept node title", () => {
		renderWithProviders(<ConceptCard node={mockNode} isActive={true} />);
		expect(screen.getByText("Introduction to AI")).toBeDefined();
	});

	test("shows the confirmation dialog when the refresh button is clicked", () => {
		renderWithProviders(<ConceptCard node={mockNode} isActive={true} />);
		
		// Find refresh button by title
		const refreshButton = screen.getByLabelText("Regenerate the content");
		expect(refreshButton).toBeDefined();

		// Click the refresh button
		fireEvent.click(refreshButton);

		// Confirmation dialog should appear
		expect(screen.getByText("Regenerate Topic Content?")).toBeDefined();
		expect(
			screen.getByText(
				"This will overwrite the current explanation and quizzes. You will need to complete the quiz again to master this topic."
			)
		).toBeDefined();

		// Click cancel
		const cancelButton = screen.getByText("Cancel");
		fireEvent.click(cancelButton);

		// Confirmation dialog should disappear
		expect(screen.queryByText("Regenerate Topic Content?")).toBeNull();
	});

	test("regenerate icon only appears on in-progress nodes", () => {
		const inProgressStatuses: ("VIEWING_EXPLANATION" | "IN_QUIZ" | "SHOWING_FEEDBACK")[] = [
			"VIEWING_EXPLANATION",
			"IN_QUIZ",
			"SHOWING_FEEDBACK",
		];
		// M12: ERROR also shows per-card regen; LOCKED/COMPLETED do not.
		const regenStatuses = [...inProgressStatuses, "ERROR" as const];
		const otherStatuses: ("LOCKED" | "COMPLETED")[] = ["LOCKED", "COMPLETED"];

		regenStatuses.forEach((status) => {
			const { unmount } = renderWithProviders(
				<ConceptCard node={{ ...mockNode, status }} isActive={true} />
			);
			expect(screen.queryByLabelText("Regenerate the content")).not.toBeNull();
			unmount();
		});

		otherStatuses.forEach((status) => {
			const { unmount } = renderWithProviders(
				<ConceptCard node={{ ...mockNode, status }} isActive={true} />
			);
			expect(screen.queryByLabelText("Regenerate the content")).toBeNull();
			unmount();
		});
	});

	test("adds dark:bg-black class when regenerating", () => {
		const { container } = renderWithProviders(
			<ConceptCard node={mockNode} isActive={true} isRegenerating={true} />
		);
		const article = container.querySelector("article");
		const header = container.querySelector(".border-b");
		expect(article?.className).toContain("dark:bg-black");
		expect(header?.className).toContain("dark:bg-black");
	});

	test("adds dark:bg-black class when in loading phase, but removes it when streaming starts", async () => {
		const { streamRegenerateNode } = await import("@/lib/regenApi");
		const mockedStreamRegenerateNode = vi.mocked(streamRegenerateNode);

		let triggerDelta: (delta: string) => void = () => {};
		mockedStreamRegenerateNode.mockImplementation(async (params) => {
			triggerDelta = params.onDelta;
			return new Promise(() => {});
		});

		const { container } = renderWithProviders(<ConceptCard node={mockNode} isActive={true} />);

		fireEvent.click(screen.getByLabelText("Regenerate the content"));
		fireEvent.click(screen.getByText("Regenerate"));

		const article = container.querySelector("article");
		const header = container.querySelector(".border-b");

		expect(article?.className).toContain("dark:bg-black");
		expect(header?.className).toContain("dark:bg-black");

		// Start streaming
		await act(async () => {
			triggerDelta("Some content");
		});

		expect(article?.className).not.toContain("dark:bg-black");
		expect(header?.className).not.toContain("dark:bg-black");
	});

	test("displays Generating quiz... button when explanation finishes and quizzes start generating", async () => {
		const { streamRegenerateNode } = await import("@/lib/regenApi");
		const mockedStreamRegenerateNode = vi.mocked(streamRegenerateNode);
		
		mockedStreamRegenerateNode.mockImplementation(async (params) => {
			params.onDelta("This is regenerated content.");
			params.onStatusChange?.("generating_quizzes");
			return new Promise(() => {});
		});

		renderWithProviders(<ConceptCard node={mockNode} isActive={true} />);

		fireEvent.click(screen.getByLabelText("Regenerate the content"));
		fireEvent.click(screen.getByText("Regenerate"));

		expect(screen.getByText("This is regenerated content.")).toBeDefined();
		expect(screen.getByText("Generating quiz...")).toBeDefined();
	});
});
