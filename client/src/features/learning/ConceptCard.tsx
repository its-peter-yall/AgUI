/**
 * ============================================================================
 * FILE: ConceptCard.tsx
 * LOCATION: client/src/features/learning/ConceptCard.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Visual card component that renders individual concept nodes in the learning
 *    path. Displays different content and actions based on the node's current
 *    status (LOCKED, VIEWING_EXPLANATION, IN_QUIZ, SHOWING_FEEDBACK, COMPLETED,
 *    ERROR). Enforces the sequential learning flow by only showing
 *    status-appropriate content.
 *
 * ROLE IN PROJECT:
 *    Core UI unit of the learning feature. Consumed by LearningPathContainer
 *    inside the carousel. Each node in the learning path is rendered as one
 *    ConceptCard, driving the read → quiz → feedback → mastery flow.
 *
 * KEY COMPONENTS:
 *    - ConceptCard: Main card wrapper with status-based styling and animations
 *    - Status Styles: Visual differentiation for each node status
 *    - Quiz Interface: Radio button quiz with submit/retry functionality
 *    - Review Mode: Expandable explanation in COMPLETED state
 *    - Error Handling: Regenerate/skip options for ERROR state
 *
 * DEPENDENCIES:
 *    - External: react, lucide-react
 *    - Internal: @/lib/utils, @/types/learning, ./MarkdownRenderer,
 *                ./QuizFeedback, ./useQuizFeedback, ./ErrorStates,
 *                ./animations/CardTransitions
 *
 * USAGE:
 *    ```tsx
 *    <ConceptCard
 *      node={conceptNode}
 *      isActive={currentSlideNode.id === activeNodeId}
 *      quizResult={quizResults[currentSlideNode.id]}
 *      onProceedToQuiz={(nodeId) => proceedToQuiz(nodeId)}
 *      onQuizSubmit={(nodeId, optionId) => submitAnswer(nodeId, optionId)}
 *      onRetryQuiz={(nodeId) => retry(nodeId)}
 *      onContinueToNext={(nodeId) => continueToNext(nodeId)}
 *      onRegenerate={(nodeId) => regenerate(nodeId)}
 *      isRegenerating={isRegenerating}
 *      isTransitioning={isTransitioning}
 *      canSkip={canGoNext}
 *      canPrevious={canGoPrev}
 *    />
 *    ```
 * ============================================================================
 */

import { useState, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { ChevronLeft, RefreshCw, List, BookOpen } from "lucide-react";
import type {
	ConceptNode,
	NodeStatus,
	QuizSubmitResponse,
	QuizCardHidden,
} from "@/types/learning";
import { getVisibleQuiz } from "@/types/learning";
import { useQueryClient } from "@tanstack/react-query";
import { streamRegenerateNode } from "@/lib/regenApi";
import {
	areAgentModelsConfigured,
	getProviderSettings,
} from "@/lib/providerSettings";
import { MarkdownRenderer, InlineMarkdown } from "./MarkdownRenderer";
import { QuizFeedback } from "./QuizFeedback";
import { useQuizFeedback } from "./useQuizFeedback";
import { ErrorState, LoadingState } from "./ErrorStates";
import { parseCuriosityQuestions } from "./curiosityParser";
import { CuriositySpark } from "./CuriositySpark";
import { SourceCitations } from "./SourceCitations";
import {
	AnimatedCard,
	ContentTransition,
	UnlockPulse,
} from "./animations/CardTransitions";

interface ConceptCardProps {
	node: ConceptNode;
	isActive?: boolean;
	quizResult?: QuizSubmitResponse;
	onProceedToQuiz?: (nodeId: string) => void;
	onQuizSubmit?: (nodeId: string, optionIds: string[], quizIndex: number) => void;
	onRetryQuiz?: (nodeId: string) => void;
	onContinueToNext?: (nodeId: string) => void;
	onNextQuiz?: () => void;
	onPreviousQuiz?: (nodeId: string) => void;
	onRegenerate?: (nodeId: string) => void;
	onSkipNode?: (nodeId: string) => void;
	onPrevious?: () => void;
	isRegenerating?: boolean;
	canSkip?: boolean;
	canPrevious?: boolean;
	isTransitioning?: boolean;
	selectedHeadingIds?: string[];
	onToggleHeadingChat?: (headingId: string) => void;
	onAskQuestion?: (question: string) => void;
	onOpenTOC?: () => void;
	onViewSources?: () => void;
}

const SkeletonLoader = () => (
	<div className="space-y-6 animate-pulse" aria-hidden="true">
		{/* Title skeleton */}
		<div className="space-y-2">
			<div className="h-6 bg-muted dark:bg-muted/60 rounded-md w-2/5" />
		</div>
		{/* Paragraph skeleton */}
		<div className="space-y-2.5">
			<div className="h-4 bg-muted dark:bg-muted/60 rounded w-full" />
			<div className="h-4 bg-muted dark:bg-muted/60 rounded w-11/12" />
			<div className="h-4 bg-muted dark:bg-muted/60 rounded w-5/6" />
		</div>
		{/* Points skeleton */}
		<div className="space-y-3 pl-1">
			<div className="flex items-center gap-3">
				<div className="h-2 w-2 bg-muted dark:bg-muted/60 rounded-full shrink-0" />
				<div className="h-4 bg-muted dark:bg-muted/60 rounded w-11/12" />
			</div>
			<div className="flex items-center gap-3">
				<div className="h-2 w-2 bg-muted dark:bg-muted/60 rounded-full shrink-0" />
				<div className="h-4 bg-muted dark:bg-muted/60 rounded w-4/5" />
			</div>
			<div className="flex items-center gap-3">
				<div className="h-2 w-2 bg-muted dark:bg-muted/60 rounded-full shrink-0" />
				<div className="h-4 bg-muted dark:bg-muted/60 rounded w-3/4" />
			</div>
		</div>
	</div>
);

export function ConceptCard({
	node,
	isActive = false,
	onProceedToQuiz,
	onQuizSubmit,
	onRetryQuiz,
	onContinueToNext,
	onNextQuiz,
	onPreviousQuiz,
	onSkipNode,
	onPrevious,
	isRegenerating = false,
	canSkip = false,
	canPrevious = false,
	isTransitioning = false,
	quizResult,
	selectedHeadingIds = [],
	onToggleHeadingChat,
	onAskQuestion,
	onOpenTOC,
	onViewSources,
}: ConceptCardProps) {
	const [selectedOptions, setSelectedOptions] = useState<Set<string>>(new Set());
	const [showRegenConfirm, setShowRegenConfirm] = useState(false);
	const [isRegeneratingLocal, setIsRegeneratingLocal] = useState(false);
	const [isGeneratingQuizzes, setIsGeneratingQuizzes] = useState(false);
	const [streamingMarkdown, setStreamingMarkdown] = useState("");
	const [localError, setLocalError] = useState<string | null>(null);
	const queryClient = useQueryClient();

	const agentSettings = getProviderSettings();
	const agentsReady = areAgentModelsConfigured(agentSettings);

	const startStreamingRegen = async () => {
		const settings = getProviderSettings();
		if (!areAgentModelsConfigured(settings)) {
			setLocalError(
				"Set Researcher, Planner, Generator, and Quizzer models in Settings before regenerating.",
			);
			return;
		}

		setIsRegeneratingLocal(true);
		setStreamingMarkdown("");
		setLocalError(null);
		setIsGeneratingQuizzes(false);

		await streamRegenerateNode({
			nodeId: node.id,
			onDelta: (delta) => {
				setStreamingMarkdown((prev) => prev + delta);
			},
			onStatusChange: (status) => {
				if (status === "generating_quizzes") {
					setIsGeneratingQuizzes(true);
				}
			},
			onDone: () => {
				setIsRegeneratingLocal(false);
				setStreamingMarkdown("");
				setLocalError(null);
				setIsGeneratingQuizzes(false);
				queryClient.invalidateQueries({
					queryKey: ["learningSession", node.learning_session_id],
				});
			},
			onError: (err) => {
				setIsRegeneratingLocal(false);
				setLocalError(err.message || "Failed to regenerate content.");
				setIsGeneratingQuizzes(false);
			},
		});
	};


	// Track previous status for animations

	// Track previous status for animations
	const prevStatusRef = useRef<NodeStatus>(node.status);
	const [previousStatus, setPreviousStatus] = useState<
		NodeStatus | undefined
	>();

	useEffect(() => {
		if (prevStatusRef.current !== node.status) {
			setPreviousStatus(prevStatusRef.current);
			prevStatusRef.current = node.status;
		}
	}, [node.status]);

	const isUnlocking =
		previousStatus === "LOCKED" && node.status === "VIEWING_EXPLANATION";

	const {
		result: feedbackResult,
		attemptCount,
		isLoading: isFeedbackLoading,
		error: feedbackError,
	} = useQuizFeedback({
		nodeId: node.id,
		latestResult: quizResult,
		enabled: node.status === "SHOWING_FEEDBACK",
		quiz: node.quiz,
		nodeStatus: node.status,
	});

	// Complexity badge styles
	const complexityStyles = {
		Basic:
			"bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300",
		Intermediate:
			"bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
		Advanced: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300",
	};

	// Difficulty label styles
	const difficultyStyles = {
		easy: "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300",
		medium:
			"bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
		hard: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300",
	};

	// Status-based styling
	const statusStyles: Record<NodeStatus, string> = {
		LOCKED: "opacity-50 bg-muted cursor-not-allowed",
		VIEWING_EXPLANATION: "border-primary bg-white dark:bg-muted",
		IN_QUIZ: "border-primary bg-card",
		SHOWING_FEEDBACK: "border-amber-500 bg-card",
		COMPLETED: "border-green-500 bg-white dark:bg-muted",
		ERROR: "border-destructive bg-destructive/10",
	};

	// Status icons
	const statusIcons: Record<NodeStatus, string> = {
		LOCKED: "🔒",
		VIEWING_EXPLANATION: "📖",
		IN_QUIZ: "❓",
		SHOWING_FEEDBACK: "📊",
		COMPLETED: "✅",
		ERROR: "!",
	};

	// Show refresh for in-progress and ERROR (M12 per-card regen).
	const showRefreshButton =
		node.status === "VIEWING_EXPLANATION" ||
		node.status === "IN_QUIZ" ||
		node.status === "SHOWING_FEEDBACK" ||
		node.status === "ERROR";

	const isLoadingPhase =
		isRegenerating || (isRegeneratingLocal && streamingMarkdown === "");

	const handleProceedToQuiz = () => {
		// Prevent transition if not in VIEWING_EXPLANATION state
		if (node.status === "VIEWING_EXPLANATION") {
			onProceedToQuiz?.(node.id);
		}
	};

	const showCuriosity =
		!!onAskQuestion &&
		(node.status === "VIEWING_EXPLANATION" ||
			node.status === "COMPLETED" ||
			(isRegeneratingLocal && isGeneratingQuizzes));
	const contentToParse = isRegeneratingLocal ? streamingMarkdown : node.content_markdown;
	const { mainContent, questions } = showCuriosity
		? parseCuriosityQuestions(contentToParse)
		: { mainContent: contentToParse, questions: [] };

	const handleSubmitQuiz = (quizIndex: number) => {
		if (selectedOptions.size > 0) {
			onQuizSubmit?.(node.id, Array.from(selectedOptions), quizIndex);
			setSelectedOptions(new Set());
		}
	};

	const handleRetry = () => {
		setSelectedOptions(new Set());
		onRetryQuiz?.(node.id);
	};

	const renderPreviousButton = () => (
		<button
			onClick={onPrevious}
			disabled={!canPrevious}
			className={cn(
				"flex items-center gap-1.5 px-3 py-2 rounded-md text-muted-foreground hover:bg-primary/20 hover:text-primary transition-colors text-sm font-medium",
				!canPrevious && "opacity-0 pointer-events-none",
			)}
		>
			<ChevronLeft className="w-4 h-4" />
			<span>Previous</span>
		</button>
	);

	return (
		<UnlockPulse isUnlocking={isUnlocking}>
			<AnimatedCard
				status={node.status}
				previousStatus={previousStatus}
				onAnimationComplete={() => setPreviousStatus(undefined)}
			>
				<article
					className={cn(
						"border rounded-lg overflow-hidden topic-card-content relative", // Added relative class
						statusStyles[node.status],
						isLoadingPhase && "dark:bg-black",
						isActive && "ring-2 ring-primary ring-offset-2",
					)}
				>
					{/* Card Header */}
					<div
						className={cn(
							"flex items-center gap-3 p-4 border-b",
							(node.status === "VIEWING_EXPLANATION" || node.status === "COMPLETED") ? "bg-white dark:bg-muted" : "bg-card/50",
							isLoadingPhase && "dark:bg-black",
						)}
					>
						<span className="text-xl">{statusIcons[node.status]}</span>
						<div className="flex-1">
							<div className="flex items-center gap-2">
								<h3 className="font-semibold">{node.title}</h3>
								{node.complexity && (
									<span
										className={cn(
											"text-xs font-medium px-2 py-0.5 rounded-full",
											complexityStyles[node.complexity],
										)}
									>
										{node.complexity}
									</span>
								)}
							</div>
							<span className="text-xs text-muted-foreground uppercase tracking-wide">
								{node.status.replace(/_/g, " ")}
							</span>
						</div>
						<div className="flex items-center gap-2">
							{onOpenTOC && (
								<button
									type="button"
									onClick={onOpenTOC}
									className={cn(
										"px-4 py-2 rounded-lg text-base font-semibold select-none transition-all duration-200 cursor-pointer flex items-center gap-2",
										"border border-border/80 text-muted-foreground bg-card hover:bg-accent/40 focus:outline-none focus:ring-1 focus:ring-primary"
									)}
									title="Open Table of Contents"
								>
									<List className="w-5 h-5" />
									<span>See all Topics</span>
								</button>
							)}
							<span className="text-sm text-muted-foreground">
								#{node.sequence_index + 1}
							</span>
							{showRefreshButton && (
								<button
									type="button"
									onClick={() => setShowRegenConfirm(true)}
									disabled={
										isRegenerating || isRegeneratingLocal || !agentsReady
									}
									title="Regenerate the content"
									aria-label="Regenerate the content"
									className={cn(
										"p-2 rounded-md text-muted-foreground hover:bg-primary/20 hover:text-primary transition-colors disabled:opacity-50 disabled:cursor-not-allowed",
										(isRegenerating || isRegeneratingLocal) && "animate-spin",
									)}
								>
									<RefreshCw className="w-5 h-5" />
								</button>
							)}
						</div>
					</div>

					{/* Card Body - State-based content */}
					<ContentTransition contentKey={`${node.id}-${node.status}-${isRegeneratingLocal}-${showRegenConfirm}-${!!localError}`}>
						<div className="p-4 relative">
							{/* Confirmation dialog overlay */}
							{showRegenConfirm && (
								<div className="absolute inset-0 bg-background/95 backdrop-blur-sm z-50 flex flex-col items-center justify-center p-6 text-center">
									<h4 className="font-semibold text-lg mb-2 text-foreground">Regenerate Topic Content?</h4>
									<p className="text-sm text-muted-foreground mb-6 max-w-sm">
										This will overwrite the current explanation and quizzes. You will need to complete the quiz again to master this topic.
									</p>
									<div className="flex gap-4">
										<button
											onClick={() => {
												setShowRegenConfirm(false);
												startStreamingRegen();
											}}
											className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 font-medium text-sm transition-colors"
										>
											Regenerate
										</button>
										<button
											onClick={() => setShowRegenConfirm(false)}
											className="px-4 py-2 border rounded-md hover:bg-muted font-medium text-sm transition-colors"
										>
											Cancel
										</button>
									</div>
								</div>
							)}

							{/* Show SkeletonLoader if confirmation is visible */}
							{showRegenConfirm ? (
								<SkeletonLoader />
							) : localError ? (
								<div className="space-y-4 py-4">
									<div className="flex items-start gap-3 text-destructive">
										<span className="text-2xl font-bold">!</span>
										<div>
											<span className="font-semibold text-lg text-destructive">
												Regeneration failed
											</span>
											<p className="text-sm text-muted-foreground mt-1">
												We encountered an error while regenerating this topic:
											</p>
											<p className="text-xs text-muted-foreground mt-2 font-mono bg-destructive/10 p-2 rounded border border-destructive/20 max-w-full overflow-auto">
												{localError}
											</p>
										</div>
									</div>
									<div className="flex gap-3 pt-4 border-t">
										<button
											onClick={() => {
												setLocalError(null);
												startStreamingRegen();
											}}
											className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 font-medium text-sm transition-colors"
										>
											Retry
										</button>
										<button
											onClick={() => {
												setLocalError(null);
											}}
											className="px-4 py-2 border rounded-md hover:bg-muted font-medium text-sm transition-colors"
										>
											Cancel
										</button>
									</div>
								</div>
							) : isRegeneratingLocal ? (
								// Local streaming/loading state
								<div className="space-y-4">
									{streamingMarkdown === "" ? (
										<SkeletonLoader />
									) : isGeneratingQuizzes ? (
										// Explanation fully streamed, quizzes generating
										<div className="space-y-4">
											<MarkdownRenderer
												content={mainContent}
												selectedHeadingIds={selectedHeadingIds}
												onToggleHeadingChat={onToggleHeadingChat}
												enableHeadingChat
											/>
											{questions.length > 0 && onAskQuestion && (
												<CuriositySpark
													questions={questions}
													onAskQuestion={onAskQuestion}
												/>
											)}
											<div className="flex justify-between items-center pt-4 border-t">
												{renderPreviousButton()}
												<button
													disabled
													className="px-4 py-2 bg-primary text-primary-foreground rounded-md opacity-50 cursor-not-allowed transition-colors flex items-center gap-2"
												>
													<div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary-foreground" />
													<span>Generating quiz...</span>
												</button>
											</div>
										</div>
									) : (
										<div className="space-y-4 animate-fade-in">
											<div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
												<div className="animate-spin rounded-full h-3 w-3 border-b-2 border-primary" />
												<span>Streaming new explanation...</span>
											</div>
											<MarkdownRenderer
												content={streamingMarkdown}
												selectedHeadingIds={selectedHeadingIds}
												onToggleHeadingChat={onToggleHeadingChat}
												enableHeadingChat
											/>
										</div>
									)}
								</div>
							) : (
								<>
							{/* LOCKED state */}
							{node.status === "LOCKED" && (
								<div className="text-center py-8 text-muted-foreground">
									<p>Complete the previous topic to unlock this one.</p>
								</div>
							)}

							{/* VIEWING_EXPLANATION state */}
							{node.status === "VIEWING_EXPLANATION" && (
								<div className="space-y-4">
									<MarkdownRenderer
										content={mainContent}
										selectedHeadingIds={selectedHeadingIds}
										onToggleHeadingChat={onToggleHeadingChat}
										enableHeadingChat
									/>
									{questions.length > 0 && onAskQuestion && (
										<CuriositySpark
											questions={questions}
											onAskQuestion={onAskQuestion}
										/>
									)}
									<SourceCitations citations={node.citations ?? []} />
									{onViewSources && (
										<button
											type="button"
											onClick={onViewSources}
											className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline"
										>
											<BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
											View course sources
										</button>
									)}
									<div className="flex justify-between items-center pt-4 border-t">
										{renderPreviousButton()}
										<button
											onClick={handleProceedToQuiz}
											disabled={isTransitioning}
											className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
										>
											{isTransitioning
												? "Transitioning..."
												: "I understand, proceed to quiz →"}
										</button>
									</div>
								</div>
							)}

							{/* IN_QUIZ state */}
							{node.status === "IN_QUIZ" &&
								(() => {
									const visibleQuiz = getVisibleQuiz(node);
									if (!visibleQuiz) return null;

									// Type guard for QuizSetHidden (has total_quizzes)
									const isQuizSetHidden =
										"quizzes" in visibleQuiz && "total_quizzes" in visibleQuiz;
									const currentQuizIndex = isQuizSetHidden
										? (visibleQuiz as { current_index: number }).current_index
										: 0;
									const currentQuiz =
										"quizzes" in visibleQuiz
											? visibleQuiz.quizzes[currentQuizIndex]
											: (visibleQuiz as QuizCardHidden);

									const isMultipleChoice =
										"question_type" in currentQuiz &&
										(currentQuiz as { question_type?: string }).question_type ===
											"multiple_choice";

									return (
										<div className="space-y-4">
											{isQuizSetHidden && (
												<div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
													<span>
														Quiz {currentQuizIndex + 1} of{" "}
														{
															(visibleQuiz as { total_quizzes: number })
																.total_quizzes
														}
													</span>
													{currentQuiz?.difficulty && (
														<span
															className={cn(
																"text-xs font-medium px-2 py-0.5 rounded-full",
																difficultyStyles[currentQuiz.difficulty],
															)}
														>
															{currentQuiz.difficulty.charAt(0).toUpperCase() +
																currentQuiz.difficulty.slice(1)}
														</span>
													)}
												</div>
											)}
											<div id={`quiz-question-${node.id}`}>
												<MarkdownRenderer
													className="font-medium text-lg [&>div]:!mt-0"
													content={currentQuiz.question_text}
												/>
											</div>
											<fieldset
												className="space-y-2"
												role={isMultipleChoice ? "group" : "radiogroup"}
												aria-describedby={`quiz-question-${node.id}`}
											>
												<legend className="sr-only">Quiz options</legend>
												{currentQuiz.options.map((option) => (
													<label
														key={option.option_id}
														className={cn(
															"flex items-center gap-3 p-3 rounded-md border cursor-pointer transition-colors",
															selectedOptions.has(option.option_id)
																? "border-primary bg-primary/10"
																: "border-muted hover:border-primary/50",
														)}
													>
														<input
															type={isMultipleChoice ? "checkbox" : "radio"}
															name={isMultipleChoice ? undefined : `quiz-${node.id}`}
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
															className="w-4 h-4"
														/>
														<span className="font-mono text-sm text-muted-foreground">
															{option.display_label}.
														</span>
														<InlineMarkdown content={option.text} />
													</label>
												))}
											</fieldset>
											<div className="flex justify-between items-center pt-4 border-t">
												{isQuizSetHidden && currentQuizIndex > 0 ? (
													<button
														onClick={() => onPreviousQuiz?.(node.id)}
														className="flex items-center gap-1.5 px-3 py-2 rounded-md text-muted-foreground hover:bg-primary/20 hover:text-primary transition-colors text-sm font-medium"
													>
														<ChevronLeft className="w-4 h-4" />
														<span>Previous</span>
													</button>
												) : (
													<button
														disabled
														className="flex items-center gap-1.5 px-3 py-2 rounded-md text-muted-foreground/30 cursor-not-allowed transition-colors text-sm font-medium"
													>
														<ChevronLeft className="w-4 h-4" />
														<span>Previous</span>
													</button>
												)}
											<button
												onClick={() => handleSubmitQuiz(currentQuizIndex)}
												disabled={selectedOptions.size === 0}
												className={cn(
													"px-4 py-2 rounded-md transition-colors",
													selectedOptions.size > 0
														? "bg-primary text-primary-foreground hover:bg-primary/90"
														: "bg-muted text-muted-foreground cursor-not-allowed",
												)}
											>
													Submit Answer
												</button>
											</div>
										</div>
									);
								})()}

							{node.status === "SHOWING_FEEDBACK" &&
								(node.quiz || node.quiz_set) && (
									<>
										{feedbackResult && (
											<QuizFeedback
												quiz={node.quiz_set || node.quiz!}
												result={feedbackResult}
												attemptCount={attemptCount}
												currentQuizIndex={
													feedbackResult.quiz_index ??
													node.quiz_set_hidden?.current_index ??
													0
												}
												onRetry={handleRetry}
												onContinue={
													feedbackResult.is_mastered
														? () => onContinueToNext?.(node.id)
														: undefined
												}
												onNextQuiz={onNextQuiz}
											/>
										)}
										{!feedbackResult && isFeedbackLoading && (
											<LoadingState message="Loading quiz feedback..." />
										)}
										{!feedbackResult && !isFeedbackLoading && feedbackError && (
											<ErrorState
												title="Unable to load feedback"
												message="Please try again in a moment."
												showHomeLink={false}
											/>
										)}
										{!feedbackResult &&
											!isFeedbackLoading &&
											!feedbackError && (
												<ErrorState
													title="Feedback unavailable"
													message="We couldn't load the latest quiz result."
													showHomeLink={false}
												/>
											)}
									</>
								)}

							{/* COMPLETED state */}
							{node.status === "COMPLETED" && (
								<div className="space-y-4">
									<div className="flex items-center gap-2 text-green-600 dark:text-green-400">
										<span className="text-xl">✓</span>
										<span className="font-medium">Topic mastered!</span>
									</div>
									<details className="group">
										<summary className="cursor-pointer text-sm text-muted-foreground hover:text-foreground">
											Review explanation
										</summary>
										<div className="mt-4 pt-4 border-t space-y-4">
											<MarkdownRenderer
												content={mainContent}
												selectedHeadingIds={selectedHeadingIds}
												onToggleHeadingChat={onToggleHeadingChat}
												enableHeadingChat
											/>
											{questions.length > 0 && onAskQuestion && (
												<CuriositySpark
													questions={questions}
													onAskQuestion={onAskQuestion}
												/>
											)}
											{/* M12: retain citations after mastery */}
											<SourceCitations citations={node.citations ?? []} />
											{onViewSources && (
												<button
													type="button"
													onClick={onViewSources}
													className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline"
												>
													<BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
													View course sources
												</button>
											)}
										</div>
									</details>
									<div className="flex justify-between items-center pt-4 border-t">
										{renderPreviousButton()}
										{canSkip ? (
											<button
												onClick={() => onSkipNode?.(node.id)}
												className="flex items-center gap-1.5 px-3 py-2 rounded-md text-muted-foreground hover:bg-primary/20 hover:text-primary transition-colors text-sm font-medium"
											>
												<span>Next</span>
												<ChevronLeft className="w-4 h-4 rotate-180" />
											</button>
										) : (
											<div /> /* Spacer */
										)}
									</div>
								</div>
							)}

							{/* ERROR state */}
							{node.status === "ERROR" && (
								<div className="space-y-4">
									<div className="flex items-start gap-3 text-destructive">
										<span className="text-2xl">!</span>
										<div>
											<span className="font-medium">
												Content generation failed
											</span>
											<p className="text-sm text-muted-foreground">
												This topic couldn't be generated. You can retry or skip
												to continue.
											</p>
										</div>
									</div>
									{node.error_message && (
										<p className="text-xs text-muted-foreground">
											{node.error_message}
										</p>
									)}
									{node.content_markdown && (
										<MarkdownRenderer content={node.content_markdown} />
									)}
									<SourceCitations citations={node.citations ?? []} />
									{onViewSources && (
										<button
											type="button"
											onClick={onViewSources}
											className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline"
										>
											<BookOpen className="h-3.5 w-3.5" aria-hidden="true" />
											View course sources
										</button>
									)}
									<div className="flex gap-3">
									<button
										onClick={() => setShowRegenConfirm(true)}
										disabled={
											isRegenerating || isRegeneratingLocal || !agentsReady
										}
										className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors disabled:opacity-50"
									>
										{isRegenerating || isRegeneratingLocal ? "Regenerating..." : "Retry Generation"}
									</button>
										{canSkip && (
											<button
												onClick={() => onSkipNode?.(node.id)}
												className="px-4 py-2 border rounded-md hover:bg-muted transition-colors"
											>
												Skip for Now
											</button>
										)}
									</div>
									{node.content_markdown && (
										<details className="mt-4">
											<summary className="cursor-pointer text-sm text-muted-foreground">
												Show partial content (may be incomplete)
											</summary>
											<div className="mt-2 p-4 bg-muted/50 rounded border border-dashed">
												<MarkdownRenderer
													content={node.content_markdown}
													selectedHeadingIds={selectedHeadingIds}
													onToggleHeadingChat={onToggleHeadingChat}
													enableHeadingChat
												/>
											</div>
										</details>
									)}
								</div>
							)}
							</>
							)}
						</div>
					</ContentTransition>
				</article>
			</AnimatedCard>
		</UnlockPulse>
	);
}
