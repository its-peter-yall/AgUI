/**
 * ============================================================================
 * FILE: RevisionConceptCard.tsx
 * LOCATION: client/src/features/learning/RevisionConceptCard.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Card component for revision mode that renders content or quiz based on mode.
 *
 * ROLE IN PROJECT:
 *    Replaces ConceptCard in revision sessions. Adapts its layout for
 *    full_review (shows content + mark-reviewed button + quiz) or quiz_only
 *    (shows quiz immediately). All nodes are unlocked — no sequential gating.
 *
 * KEY COMPONENTS:
 *    - RevisionConceptCard: Main card component with mode-aware rendering
 *    - statusBadges: Config map for pending/reviewed/quiz_passed/quiz_failed states
 *    - renderQuizSection: Inline quiz renderer with feedback display
 *
 * DEPENDENCIES:
 *    - External: react, lucide-react
 *    - Internal: @/lib/utils, @/types/learning, ./MarkdownRenderer
 *
 * USAGE:
 *    <RevisionConceptCard
 *      node={conceptNode}
 *      revisionMode="full_review"
 *      revisionProgress={progressData}
 *      onMarkReviewed={handleMarkReviewed}
 *      onQuizSubmit={handleQuizSubmit}
 *    />
 * ============================================================================
 */

// RevisionConceptCard.tsx
// Card component for revision mode that adapts rendering based on
// full_review or quiz_only mode, with status badges and no sequential locking.

// @see: ConceptCard.tsx (original learning card)
// @see: useRevisionMutations.ts (mutation handlers)

import { useState } from "react";
import { cn } from "@/lib/utils";
import type {
	ConceptNode,
	RevisionNodeProgressWithDetails,
	RevisionMode,
	RevisionNodeStatus,
	RevisionQuizResponse,
} from "@/types/learning";
import { MarkdownRenderer, InlineMarkdown } from "./MarkdownRenderer";

interface RevisionConceptCardProps {
	/** Original concept node with content and quiz data */
	node: ConceptNode;
	/** Current revision mode */
	revisionMode: RevisionMode;
	/** Revision-specific progress for this node */
	revisionProgress: RevisionNodeProgressWithDetails;
	/** Callback when user marks node as reviewed (full_review only) */
	onMarkReviewed: (nodeId: string) => void;
	/** Callback when user submits a quiz answer */
	onQuizSubmit: (nodeId: string, optionIds: string[], quizIndex?: number) => void;
	/** Whether the mark-reviewed mutation is loading */
	isMarkingReviewed?: boolean;
	/** Whether the quiz submit mutation is loading */
	isSubmitting?: boolean;
	/** Last quiz result for showing feedback */
	quizResult?: RevisionQuizResponse;
}

/**
 * Status badge configuration for revision node states.
 */
const statusBadges: Record<
	RevisionNodeStatus,
	{ icon: string; label: string; className: string }
> = {
	pending: {
		icon: "\u23F3",
		label: "Pending",
		className: "bg-muted text-muted-foreground",
	},
	reviewed: {
		icon: "\u2705",
		label: "Reviewed",
		className:
			"bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300",
	},
	quiz_passed: {
		icon: "\u2705",
		label: "Passed",
		className:
			"bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300",
	},
	quiz_failed: {
		icon: "\u274C",
		label: "Try Again",
		className: "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300",
	},
};

export function RevisionConceptCard({
	node,
	revisionMode,
	revisionProgress,
	onMarkReviewed,
	onQuizSubmit,
	isMarkingReviewed = false,
	isSubmitting = false,
	quizResult,
}: RevisionConceptCardProps) {
	const [selectedOptions, setSelectedOptions] = useState<Set<string>>(new Set());
	const [currentQuizIndex, setCurrentQuizIndex] = useState(0);

	const badge = statusBadges[revisionProgress.status];

	// Determine card border style based on status
	const borderStyle = (() => {
		switch (revisionProgress.status) {
			case "quiz_passed":
			case "reviewed":
				return "border-green-500 border-l-4 border-l-green-500 bg-card";
			case "quiz_failed":
				return "border-red-500 border-l-4 border-l-red-500 bg-card";
			default:
				// Default revision style: subtle blue left border
				return "border-border border-l-4 border-l-blue-500/50 bg-card";
		}
	})();

	const handleQuizSubmit = (quizIndex: number) => {
		if (selectedOptions.size > 0) {
			onQuizSubmit(node.id, Array.from(selectedOptions), quizIndex);
			setSelectedOptions(new Set());
		}
	};

	const renderStatusBadge = () => (
		<span
			className={cn(
				"inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium",
				badge.className,
			)}
			data-testid="revision-status-badge"
		>
			<span aria-hidden="true">{badge.icon}</span>
			{badge.label}
		</span>
	);

	const renderQuizSection = () => {
		// Use quiz data from original node: first try quiz_set, then single quiz
		const quizData =
			node.quiz_set ??
			(node.quiz
				? { quizzes: [node.quiz], current_index: 0, shuffle_seed: null }
				: null);
		if (!quizData || quizData.quizzes.length === 0) return null;

		const safeQuizIndex = Math.min(currentQuizIndex, quizData.quizzes.length - 1);
		const currentQuiz = quizData.quizzes[safeQuizIndex];
		if (!currentQuiz) return null;

		const isMultipleChoice =
			"question_type" in currentQuiz &&
			(currentQuiz as { question_type?: string }).question_type ===
				"multiple_choice";

		// Build sets for efficient lookup
		const feedbackSelectedSet = new Set(quizResult?.selected_option_ids ?? []);
		const feedbackCorrectSet = new Set(quizResult?.correct_option_ids ?? []);

		// Show feedback if quiz has been submitted
		const showFeedback =
			quizResult &&
			(revisionProgress.status === "quiz_passed" ||
				revisionProgress.status === "quiz_failed");

		return (
			<div
				className="space-y-4 mt-4 pt-4 border-t"
				data-testid="revision-quiz-section"
			>
				{quizData.quizzes.length > 1 && (
					<div className="flex items-center justify-between text-sm text-muted-foreground pb-2 border-b">
						<button
							onClick={() => {
								setCurrentQuizIndex((prev) => Math.max(0, prev - 1));
								setSelectedOptions(new Set());
							}}
							disabled={safeQuizIndex === 0}
							className="px-2 py-1 rounded hover:bg-muted disabled:opacity-30 disabled:pointer-events-none cursor-pointer transition-colors text-xs font-medium"
							aria-label="Previous quiz"
						>
							&larr; Previous Quiz
						</button>
						<span className="font-medium">
							Quiz {safeQuizIndex + 1} of {quizData.quizzes.length}
						</span>
						<button
							onClick={() => {
								setCurrentQuizIndex((prev) =>
									Math.min(quizData.quizzes.length - 1, prev + 1),
								);
								setSelectedOptions(new Set());
							}}
							disabled={safeQuizIndex === quizData.quizzes.length - 1}
							className="px-2 py-1 rounded hover:bg-muted disabled:opacity-30 disabled:pointer-events-none cursor-pointer transition-colors text-xs font-medium"
							aria-label="Next quiz"
						>
							Next Quiz &rarr;
						</button>
					</div>
				)}
			<div id={`revision-quiz-question-${node.id}`}>
				<MarkdownRenderer
					className="font-medium text-lg [&>div]:!mt-0"
					content={currentQuiz.question_text}
				/>
			</div>
			<fieldset
				className="space-y-2"
				role={isMultipleChoice ? "group" : "radiogroup"}
				aria-describedby={`revision-quiz-question-${node.id}`}
			>
				<legend className="sr-only">Quiz options</legend>
				{currentQuiz.options.map((option) => {
					const isSelected =
						showFeedback &&
						feedbackSelectedSet.has(option.option_id);
					const isCorrectOption =
						showFeedback &&
						feedbackCorrectSet.has(option.option_id);

					return (
						<div
							key={option.option_id}
							className={cn(
								"p-3 rounded-md border transition-colors",
								showFeedback &&
									isCorrectOption &&
									"border-green-500 bg-green-50 dark:bg-green-900/20",
								showFeedback &&
									isSelected &&
									!isCorrectOption &&
									"border-red-500 bg-red-50 dark:bg-red-900/20",
								showFeedback &&
									!isSelected &&
									!isCorrectOption &&
									"border-muted bg-muted/30",
								!showFeedback &&
									selectedOptions.has(option.option_id) &&
									"border-primary bg-primary/10",
								!showFeedback &&
									!selectedOptions.has(option.option_id) &&
									"border-muted hover:border-primary/50",
							)}
						>
							<label className="flex items-center gap-3 cursor-pointer">
								<input
									type={isMultipleChoice ? "checkbox" : "radio"}
									name={isMultipleChoice ? undefined : `revision-quiz-${node.id}`}
									value={option.option_id}
									checked={selectedOptions.has(option.option_id)}
									onChange={() => {
										if (isMultipleChoice) {
											setSelectedOptions((prev) => {
												const next = new Set(prev);
												if (next.has(option.option_id)) {
													next.delete(option.option_id);
												} else {
													next.add(option.option_id);
												}
												return next;
											});
										} else {
											setSelectedOptions(new Set([option.option_id]));
										}
									}}
									disabled={showFeedback}
									className="w-4 h-4"
								/>
								<span className="font-mono text-sm text-muted-foreground">
									{option.display_label}.
								</span>
								<InlineMarkdown content={option.text} />
							</label>

								{/* Show explanation from quiz result */}
								{showFeedback && isCorrectOption && (
									<div className="mt-2 pl-7">
										<span className="text-xs text-green-600 dark:text-green-400 font-medium block mb-1">
											✓ Correct answer
										</span>
										<MarkdownRenderer
											className="text-sm text-green-700 dark:text-green-300 [&>div]:!mt-0"
											content={quizResult?.explanation ?? ""}
										/>
									</div>
								)}
								{showFeedback &&
									isSelected &&
									!isCorrectOption && (
										<div className="mt-2 pl-7">
											<span className="text-xs text-red-500 dark:text-red-400 font-medium block mb-1">
												Why this is incorrect:
											</span>
											<MarkdownRenderer
												className="text-sm text-red-600 dark:text-red-300 [&>div]:!mt-0"
												content={option.explanation}
											/>
										</div>
									)}
							</div>
						);
					})}
				</fieldset>

				{/* Result header when feedback is shown */}
				{showFeedback && (
					<div
						className={cn(
							"flex items-center gap-3 p-3 rounded-lg mt-4",
							quizResult.is_correct
								? "bg-green-100 dark:bg-green-900/30 text-green-800 dark:text-green-200"
								: "bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-200",
						)}
					>
						<span className="text-xl">
							{quizResult.is_correct ? "✅" : "❌"}
						</span>
						<div>
							<p className="font-semibold">
								{quizResult.is_correct ? "Correct!" : "Incorrect"}
							</p>
							<p className="text-sm opacity-80">
								Score: {quizResult.score_percent}%
							</p>
						</div>
					</div>
				)}

				<div className="flex justify-between items-center pt-2">
					{quizData.quizzes.length > 1 && safeQuizIndex < quizData.quizzes.length - 1 ? (
						<button
							onClick={() => {
								setCurrentQuizIndex((prev) => prev + 1);
								setSelectedOptions(new Set());
							}}
							className="px-3 py-1.5 text-xs font-medium rounded-md border border-input hover:bg-muted transition-colors cursor-pointer"
						>
							Skip / Next Quiz &rarr;
						</button>
					) : (
						<div />
					)}
					<button
						onClick={() => handleQuizSubmit(safeQuizIndex)}
						disabled={selectedOptions.size === 0 || isSubmitting || showFeedback}
						className={cn(
							"px-4 py-2 rounded-md transition-colors",
							selectedOptions.size > 0 && !isSubmitting && !showFeedback
								? "bg-primary text-primary-foreground hover:bg-primary/90"
								: "bg-muted text-muted-foreground cursor-not-allowed",
						)}
						data-testid="revision-quiz-submit"
					>
						{isSubmitting ? "Submitting..." : "Submit Answer"}
					</button>
				</div>
			</div>
		);
	};

	return (
		<article
			className={cn("border rounded-lg overflow-hidden topic-card-content", borderStyle)}
			data-testid="revision-concept-card"
		>
			{/* Card Header */}
			<div className="flex items-center gap-3 p-4 border-b bg-card/50">
				<div className="flex-1">
					<h3 className="font-semibold">{node.title}</h3>
					<span className="text-xs text-muted-foreground">
						Topic #{node.sequence_index + 1}
					</span>
				</div>
				{renderStatusBadge()}
			</div>

			{/* Card Body */}
			<div className="p-4">
				{revisionMode === "full_review" && (
					<div className="space-y-4" data-testid="revision-full-review-content">
						{/* Always show explanation content in full_review */}
						<MarkdownRenderer content={node.content_markdown} />

						{/* Mark as Reviewed button */}
						{revisionProgress.status === "pending" && (
							<div className="flex justify-end pt-4 border-t">
								<button
									onClick={() => onMarkReviewed(node.id)}
									disabled={isMarkingReviewed}
									className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
									data-testid="mark-reviewed-button"
								>
									{isMarkingReviewed ? "Marking..." : "Mark as Reviewed"}
								</button>
							</div>
						)}

						{/* Quiz section below content */}
						{renderQuizSection()}
					</div>
				)}

				{revisionMode === "quiz_only" && (
					<div data-testid="revision-quiz-only-content">
						{/* Show only topic title as context, no explanation */}
						<p className="text-sm text-muted-foreground mb-2">
							Test your knowledge on this topic:
						</p>

						{/* Quiz immediately visible */}
						{renderQuizSection()}

						{/* If no quiz available */}
						{!node.quiz && !node.quiz_set && (
							<p className="text-muted-foreground text-center py-4">
								No quiz available for this topic.
							</p>
						)}
					</div>
				)}
			</div>
		</article>
	);
}
