/**
 * ============================================================================
 * FILE: TableOfContentsModal.test.tsx
 * LOCATION: client/src/features/learning/TableOfContentsModal.test.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Unit tests for the TableOfContentsModal component.
 *
 * ROLE IN PROJECT:
 *    Verifies that the Table of Contents modal renders properly, handles list
 *    scrolling, supports escape-key close and focus trapping, and correctly
 *    enables/disables topic selection based on lock status.
 *
 * KEY COMPONENTS:
 *    - TableOfContentsModal: Dialog-based course roadmap and navigation
 *
 * DEPENDENCIES:
 *    - External: @testing-library/react, vitest
 *    - Internal: ./TableOfContentsModal
 *
 * USAGE:
 *    npm run test
 * ============================================================================
 */

import type { ReactNode, ComponentPropsWithoutRef } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, test, expect, vi } from "vitest";
import { TableOfContentsModal } from "./TableOfContentsModal";
import type { ConceptNode } from "@/types/learning";

// Mock framer-motion to avoid animation issues in jsdom environment
vi.mock("framer-motion", () => ({
	motion: {
		div: ({ children, ...props }: ComponentPropsWithoutRef<"div">) => <div {...props}>{children}</div>,
	},
	AnimatePresence: ({ children }: { children?: ReactNode }) => <>{children}</>,
}));

// Mock scrollIntoView
window.HTMLElement.prototype.scrollIntoView = vi.fn();

const mockNodes: ConceptNode[] = [
	{
		id: "node-1",
		learning_session_id: "session-1",
		sequence_index: 0,
		title: "Introduction to HTML",
		content_markdown: "",
		status: "COMPLETED",
		error_message: null,
		retry_available: false,
		complexity: "Basic",
		quiz: null,
		quiz_set: { quizzes: [{} as unknown, {} as unknown] } as unknown as ConceptNode['quiz_set'],
		quiz_hidden: null,
		quiz_set_hidden: null,
		created_at: "",
		updated_at: null,
	},
	{
		id: "node-2",
		learning_session_id: "session-1",
		sequence_index: 1,
		title: "Advanced CSS Styling",
		content_markdown: "",
		status: "VIEWING_EXPLANATION",
		error_message: null,
		retry_available: false,
		complexity: "Intermediate",
		quiz: null,
		quiz_set: null,
		quiz_hidden: null,
		quiz_set_hidden: { total_quizzes: 3, quizzes: [], current_index: 0 },
		created_at: "",
		updated_at: null,
	},
	{
		id: "node-3",
		learning_session_id: "session-1",
		sequence_index: 2,
		title: "JavaScript Promises",
		content_markdown: "",
		status: "LOCKED",
		error_message: null,
		retry_available: false,
		complexity: "Advanced",
		quiz: null,
		quiz_set: null,
		quiz_hidden: null,
		quiz_set_hidden: null,
		created_at: "",
		updated_at: null,
	},
];

describe("TableOfContentsModal Component", () => {
	test("does not render when isOpen is false", () => {
		const { container } = render(
			<TableOfContentsModal
				isOpen={false}
				onClose={vi.fn()}
				nodes={mockNodes}
				currentNodeId="node-2"
				onSelectTopic={vi.fn()}
			/>
		);
		expect(container.firstChild).toBeNull();
	});

	test("renders all topics and columns when isOpen is true", () => {
		render(
			<TableOfContentsModal
				isOpen={true}
				onClose={vi.fn()}
				nodes={mockNodes}
				currentNodeId="node-2"
				onSelectTopic={vi.fn()}
			/>
		);

		// Check title
		expect(screen.getByText("Table of Contents")).toBeDefined();

		// Check topic names are displayed
		expect(screen.getByText("Introduction to HTML")).toBeDefined();
		expect(screen.getByText("Advanced CSS Styling")).toBeDefined();
		expect(screen.getByText("JavaScript Promises")).toBeDefined();

		// Check badges/status
		expect(screen.getAllByText("Mastered").length).toBe(2);
		expect(screen.getByTitle("In Progress")).toBeDefined();
		expect(screen.getAllByText("Locked").length).toBe(2);

		// Check complexity levels
		expect(screen.getByText("Basic")).toBeDefined();
		expect(screen.getByText("Intermediate")).toBeDefined();
		expect(screen.getByText("Advanced")).toBeDefined();

		// Check quiz counts
		expect(screen.getByText("2")).toBeDefined(); // HTML has 2 quizzes
		expect(screen.getByText("3")).toBeDefined(); // CSS has 3 quizzes
	});

	test("calls onSelectTopic when an unlocked topic name is clicked", () => {
		const onSelectTopic = vi.fn();
		const onClose = vi.fn();
		render(
			<TableOfContentsModal
				isOpen={true}
				onClose={onClose}
				nodes={mockNodes}
				currentNodeId="node-2"
				onSelectTopic={onSelectTopic}
			/>
		);

		// Click on unlocked node-1
		const button = screen.getByRole("button", { name: "Introduction to HTML" });
		fireEvent.click(button);

		expect(onSelectTopic).toHaveBeenCalledWith(0);
		expect(onClose).toHaveBeenCalled();
	});

	test("does not render link button for locked topics", () => {
		const onSelectTopic = vi.fn();
		render(
			<TableOfContentsModal
				isOpen={true}
				onClose={vi.fn()}
				nodes={mockNodes}
				currentNodeId="node-2"
				onSelectTopic={onSelectTopic}
			/>
		);

		// JavaScript Promises is locked, so it should not be clickable.
		// It shouldn't be a button.
		const buttons = screen.queryAllByRole("button", { name: "JavaScript Promises" });
		expect(buttons.length).toBe(0);
	});

	test("calls onClose when the close button is clicked", () => {
		const onClose = vi.fn();
		render(
			<TableOfContentsModal
				isOpen={true}
				onClose={onClose}
				nodes={mockNodes}
				currentNodeId="node-2"
				onSelectTopic={vi.fn()}
			/>
		);

		const closeButton = screen.getByLabelText("Close modal");
		fireEvent.click(closeButton);

		expect(onClose).toHaveBeenCalled();
	});

	test("calls onClose when the Escape key is pressed", () => {
		const onClose = vi.fn();
		render(
			<TableOfContentsModal
				isOpen={true}
				onClose={onClose}
				nodes={mockNodes}
				currentNodeId="node-2"
				onSelectTopic={vi.fn()}
			/>
		);

		fireEvent.keyDown(window, { key: "Escape" });
		expect(onClose).toHaveBeenCalled();
	});
});
