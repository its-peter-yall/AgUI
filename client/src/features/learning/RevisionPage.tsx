/**
 * ============================================================================
 * FILE: RevisionPage.tsx
 * LOCATION: client/src/features/learning/RevisionPage.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Main page for revision sessions, rendering concept cards in a carousel.
 *
 * ROLE IN PROJECT:
 *    Mounted at /learn/:sessionId/revise/:revisionId. Fetches both the
 *    original learning session (for node content/quizzes) and the revision
 *    session (for per-node progress). Tracks revision-specific progress
 *    independently of the original session and shows a summary modal on
 *    completion.
 *
 * KEY COMPONENTS:
 *    - RevisionPage: Page root with header, progress bar, carousel, and footer
 *    - Carousel: AnimatePresence-driven slide navigation with keyboard support
 *    - getRevisionStepColor: Maps node status to step indicator color
 *
 * DEPENDENCIES:
 *    - External: react, react-router-dom, @tanstack/react-query, axios, framer-motion
 *    - Internal: @/lib/learningApi, ./useRevisionSession, ./useRevisionMutations,
 *                ./RevisionConceptCard, ./RevisionSummaryModal, @/components/ThemeToggle,
 *                ./animations, ./ErrorStates, @/types/learning
 *
 * USAGE:
 *    // Rendered automatically via react-router-dom route:
 *    // <Route path="/learn/:sessionId/revise/:revisionId" element={<RevisionPage />} />
 * ============================================================================
 */
// RevisionPage.tsx
// Main page for revision mode, displaying concept cards in either
// full_review or quiz_only mode with revision-specific progress tracking.

// @see: LearningPage.tsx (original learning page)
// @see: RevisionConceptCard.tsx (revision card component)
// @see: RevisionSummaryModal.tsx (completion summary modal)
// @see: useRevisionSession.ts, useRevisionMutations.ts (hooks)

import { useState, useCallback, useEffect, useRef } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { motion, AnimatePresence } from "framer-motion";
import { List, MessageCircle } from "lucide-react";
import {
	getLearningSession,
	getRevisionSummary,
	createRevisionSession,
} from "@/lib/learningApi";
import { useRevisionSession } from "./useRevisionSession";
import { useRevisionMutations } from "./useRevisionMutations";
import { RevisionConceptCard } from "./RevisionConceptCard";
import { RevisionSummaryModal } from "./RevisionSummaryModal";
import { TableOfContentsModal } from "./TableOfContentsModal";
import { ChatPanel } from "./ChatPanel";
import { SettingsButton } from "@/components/SettingsButton";
import { cn } from "@/lib/utils";
import {
	carouselSlideVariants,
	carouselSlideReducedMotionVariants,
	prefersReducedMotion,
} from "./animations";
import { LoadingState, ErrorState } from "./ErrorStates";
import type {
	RevisionNodeProgressWithDetails,
	RevisionQuizResponse,
} from "@/types/learning";

export function RevisionPage() {
	const { sessionId, revisionId } = useParams<{
		sessionId: string;
		revisionId: string;
	}>();
	const navigate = useNavigate();

	// Focus management
	const carouselRef = useRef<HTMLDivElement>(null);

	// Carousel state
	const [currentIndex, setCurrentIndex] = useState(0);
	const [direction, setDirection] = useState(0);

	// TOC and Chat modal states
	const [isTOCOpen, setIsTOCOpen] = useState(false);
	const [isChatOpen, setIsChatOpen] = useState(false);

	// Store quiz results per node for feedback display
	const [quizResults, setQuizResults] = useState<
		Record<string, RevisionQuizResponse>
	>({});

	// Fetch original session for node content/quizzes
	const {
		data: originalSession,
		isLoading: isLoadingOriginal,
		isError: isOriginalError,
		error: originalError,
	} = useQuery({
		queryKey: ["learningSession", sessionId],
		queryFn: () => getLearningSession(sessionId!),
		enabled: !!sessionId,
		staleTime: 60_000,
	});

	// Fetch revision session for progress
	const {
		data: revisionSession,
		isLoading: isLoadingRevision,
		isError: isRevisionError,
		error: revisionError,
	} = useRevisionSession(revisionId ?? "");

	useEffect(() => {
		// Focus the carousel container for keyboard navigation
		if (!isLoadingOriginal && !isLoadingRevision && carouselRef.current) {
			carouselRef.current.focus();
		}
	}, [isLoadingOriginal, isLoadingRevision]);

	// Revision mutations
	const {
		markReviewed,
		submitAnswer,
		isMarkingReviewed,
		isSubmitting,
		isAnyLoading,
	} = useRevisionMutations({
		revisionId: revisionId ?? "",
		onError: (error, context) => {
			console.error(`Revision mutation error (${context}):`, error);
		},
		onQuizResult: (nodeId, _isCorrect, result) => {
			// Store quiz result for feedback display
			setQuizResults((prev) => ({ ...prev, [nodeId]: result }));
		},
	});

	// Completion summary modal state
	const queryClient = useQueryClient();
	const [summaryDismissed, setSummaryDismissed] = useState(false);

	// Fetch revision summary when revision is completed (via React Query)
	const isCompleted = revisionSession?.status === "completed";
	const { data: summaryData } = useQuery({
		queryKey: ["revision-summary", revisionId],
		queryFn: () => getRevisionSummary(revisionId!),
		enabled: !!revisionId && isCompleted && !summaryDismissed,
		staleTime: Infinity,
	});

	// Derive whether to show modal from query result + dismissal flag
	const showSummary = !!summaryData && !summaryDismissed;

	// Invalidate course list when summary data first becomes available
	useEffect(() => {
		if (summaryData) {
			queryClient.invalidateQueries({ queryKey: ["courses"] });
		}
	}, [summaryData, queryClient]);

	// Summary modal actions
	const handleBackToDashboard = useCallback(() => {
		setSummaryDismissed(true);
		navigate("/learn");
	}, [navigate]);

	const handleReviseAgain = useCallback(async () => {
		if (!sessionId || !revisionSession) return;
		try {
			const newRevision = await createRevisionSession(sessionId, {
				mode: revisionSession.mode,
			});
			setSummaryDismissed(true);
			navigate(`/learn/${sessionId}/revise/${newRevision.id}`);
		} catch (err) {
			console.error("Failed to create new revision:", err);
		}
	}, [sessionId, revisionSession, navigate]);

	const handleCloseSummary = useCallback(() => {
		setSummaryDismissed(true);
	}, []);

	// Carousel navigation
	const goToSlide = useCallback(
		(index: number) => {
			if (!originalSession) return;
			const clamped = Math.max(
				0,
				Math.min(index, originalSession.nodes.length - 1),
			);
			const dir = clamped > currentIndex ? 1 : clamped < currentIndex ? -1 : 0;
			setDirection(dir);
			setCurrentIndex(clamped);
		},
		[originalSession, currentIndex],
	);

	const canGoNext = originalSession
		? currentIndex < originalSession.nodes.length - 1
		: false;
	const canGoPrev = currentIndex > 0;

	// Loading state
	if (!sessionId || !revisionId) {
		return (
			<div className="flex flex-col items-center justify-center min-h-screen gap-4">
				<p className="text-muted-foreground">Missing session or revision ID</p>
				<Link
					to="/learn"
					className="px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors"
				>
					Back to Dashboard
				</Link>
			</div>
		);
	}

	if (isLoadingOriginal || isLoadingRevision) {
		return <LoadingState message="Loading revision session..." />;
	}

	// Error states
	const error = originalError || revisionError;
	const isNotFound =
		(isOriginalError || isRevisionError) &&
		axios.isAxiosError(error) &&
		error.response?.status === 404;

	if (isNotFound) {
		return (
			<div className="flex flex-col items-center justify-center min-h-screen gap-4">
				<p className="text-xl font-semibold">Revision not found</p>
				<p className="text-muted-foreground">
					This revision session doesn&apos;t exist or has been removed.
				</p>
				<Link
					to="/learn"
					className="text-primary hover:text-primary/80 transition-colors"
				>
					&larr; Dashboard
				</Link>
			</div>
		);
	}

	if (isOriginalError || isRevisionError) {
		return (
			<ErrorState
				title="Failed to load revision"
				message="We couldn't load the revision data. Please try again."
				showHomeLink
			/>
		);
	}

	if (!originalSession || !revisionSession) {
		return (
			<ErrorState
				title="No data available"
				message="Session or revision data is missing."
				showHomeLink
			/>
		);
	}

	// Build a map of node_id -> revision progress
	const revisionProgressMap = new Map<
		string,
		RevisionNodeProgressWithDetails
	>();
	for (const nodeProgress of revisionSession.nodes) {
		revisionProgressMap.set(nodeProgress.node_id, nodeProgress);
	}

	// Determine header text based on mode
	const modeLabel =
		revisionSession.mode === "full_review" ? "Full Review" : "Quiz Only";
	const modeBadgeColor =
		revisionSession.mode === "full_review"
			? "bg-blue-500/20 text-blue-600 dark:text-blue-400"
			: "bg-green-500/20 text-green-600 dark:text-green-400";

	// Calculate revision-specific progress
	const totalNodes = revisionSession.nodes.length;
	const completedNodes = revisionSession.nodes.filter(
		(n) =>
			n.status === "reviewed" ||
			n.status === "quiz_passed" ||
			n.status === "quiz_failed",
	).length;
	const progressPercent =
		totalNodes > 0 ? Math.floor((completedNodes / totalNodes) * 100) : 0;

	const currentNode = originalSession.nodes[currentIndex];
	const currentRevisionProgress = currentNode
		? (revisionProgressMap.get(currentNode.id) ?? {
				id: `fallback-${currentNode.id}`,
				node_id: currentNode.id,
				node_title: currentNode.title,
				sequence_index: currentNode.sequence_index,
				status: "pending" as const,
				reviewed_at: null,
			})
		: undefined;

	return (
		<div className="min-h-screen bg-background">
			{/* Skip to main content link for keyboard users */}
			<a
				href="#main-content"
				className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:px-4 focus:py-2 focus:bg-primary focus:text-primary-foreground focus:rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2"
			>
				Skip to main content
			</a>
			{/* Header */}
			<header className="sticky top-0 z-10 bg-background/95 backdrop-blur border-b">
				<div className="max-w-4xl mx-auto px-4 py-3">
					<div className="flex items-center justify-between mb-3">
						<button
							onClick={() => navigate("/learn")}
							className={cn(
								"flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors",
								"focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 rounded-md px-2 py-1",
							)}
							aria-label="Go to dashboard"
							data-testid="back-to-dashboard"
						>
							<span aria-hidden="true">&larr;</span>
							<span>Dashboard</span>
						</button>
						<div
							className="flex items-center gap-2 overflow-hidden"
							data-testid="revision-header"
						>
							<span className="text-sm font-medium text-foreground truncate max-w-[200px]">
								Revision #{revisionSession.revision_number}
							</span>
							<span
								className={cn(
									"inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium shrink-0",
									modeBadgeColor,
								)}
								data-testid="revision-mode-badge"
							>
								{modeLabel}
							</span>
						</div>
						<div className="w-24 flex justify-end">
							<SettingsButton />
						</div>{" "}
						{/* Spacer for alignment */}
					</div>

					{/* Table of Contents button (replaces progress bar) */}
					<div className="flex items-center justify-between pt-1">
						<button
							onClick={() => setIsTOCOpen(true)}
							className="inline-flex items-center gap-2 text-sm font-medium border border-input bg-background hover:bg-muted text-foreground rounded-lg px-3.5 py-1.5 transition-colors cursor-pointer shadow-xs focus:outline-none focus:ring-2 focus:ring-primary"
							aria-label="Open Table of Contents"
							data-testid="toc-button"
						>
							<List className="h-4 w-4 text-primary" />
							<span>Table of Contents</span>
						</button>
						<div className="text-xs font-medium text-muted-foreground" aria-live="polite">
							{completedNodes} / {totalNodes} completed
						</div>
					</div>
				</div>
			</header>

			{/* Main content */}
			<main id="main-content" className="py-8">
				<div className="flex flex-col gap-6 p-4 max-w-4xl mx-auto">
					{/* Course title */}
					<header className="text-center">
						<h1 className="text-2xl font-bold">
							{originalSession.course_title}
						</h1>
					</header>

					{/* Slide counter */}
					<div className="flex justify-center text-sm text-muted-foreground">
						<span>
							Topic {currentIndex + 1} of {originalSession.nodes.length}
						</span>
					</div>

					{/* Carousel */}
					<div
						className="relative overflow-hidden outline-none"
						role="region"
						aria-roledescription="carousel"
						aria-label="Revision carousel"
						ref={carouselRef}
						tabIndex={-1}
					>
						<AnimatePresence mode="wait" custom={direction} initial={false}>
							{currentNode && currentRevisionProgress && (
								<motion.div
									key={currentNode.id}
									custom={direction}
									variants={
										prefersReducedMotion()
											? carouselSlideReducedMotionVariants
											: carouselSlideVariants
									}
									initial="enter"
									animate="center"
									exit="exit"
									className="w-full relative"
								>
									<RevisionConceptCard
										key={currentNode.id}
										node={currentNode}
										revisionMode={revisionSession.mode}
										revisionProgress={currentRevisionProgress}
										onMarkReviewed={markReviewed}
										onQuizSubmit={submitAnswer}
										isMarkingReviewed={isMarkingReviewed}
										isSubmitting={isSubmitting}
										quizResult={quizResults[currentNode.id]}
									/>
								</motion.div>
							)}
						</AnimatePresence>
					</div>

					{/* Navigation buttons */}
					<div className="flex justify-between items-center">
						<button
							onClick={() => goToSlide(currentIndex - 1)}
							disabled={!canGoPrev}
							className={cn(
								"px-4 py-2 rounded-md text-sm font-medium transition-colors",
								canGoPrev
									? "text-muted-foreground hover:bg-muted cursor-pointer"
									: "opacity-0 pointer-events-none",
							)}
						>
							&larr; Previous
						</button>
						<button
							onClick={() => goToSlide(currentIndex + 1)}
							disabled={!canGoNext}
							className={cn(
								"px-4 py-2 rounded-md text-sm font-medium transition-colors",
								canGoNext
									? "text-muted-foreground hover:bg-muted cursor-pointer"
									: "opacity-0 pointer-events-none",
							)}
						>
							Next &rarr;
						</button>
					</div>
				</div>
			</main>

			{/* Loading overlay for mutations */}
			{isAnyLoading && (
				<div
					className="fixed bottom-4 right-4 bg-background border rounded-lg shadow-lg p-3 flex items-center gap-2"
					role="status"
					aria-busy="true"
					aria-label="Loading"
				>
					<div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary" />
					<span className="text-sm text-muted-foreground">Updating...</span>
				</div>
			)}

			{/* Chat FAB - bottom-right fixed */}
			{!isChatOpen && (
				<button
					onClick={() => setIsChatOpen(true)}
					className="fixed bottom-6 right-6 z-30 h-14 w-14 rounded-full bg-(--cyber-yellow) text-black shadow-lg hover:bg-(--cyber-yellow)/90 transition-colors flex items-center justify-center cursor-pointer"
					aria-label="Open concept chat"
					data-testid="revision-chat-fab"
				>
					<MessageCircle className="h-6 w-6" />
				</button>
			)}

			{/* Chat Panel - slides in from right */}
			<ChatPanel
				isOpen={isChatOpen}
				onClose={() => setIsChatOpen(false)}
				sessionId={sessionId}
				nodeId={currentNode?.id ?? ""}
				isCourseComplete={revisionSession.status === "completed"}
			/>

			{/* Table of Contents Modal */}
			<TableOfContentsModal
				isOpen={isTOCOpen}
				onClose={() => setIsTOCOpen(false)}
				nodes={originalSession.nodes.map((node) => {
					const progress = revisionProgressMap.get(node.id);
					const isDone =
						progress?.status === "reviewed" || progress?.status === "quiz_passed";
					return {
						...node,
						status: isDone ? ("COMPLETED" as const) : ("AVAILABLE" as const),
					};
				})}
				currentNodeId={currentNode?.id}
				onSelectTopic={(index) => {
					goToSlide(index);
					setIsTOCOpen(false);
				}}
			/>

			{/* Footer */}
			<footer className="border-t py-4 text-center text-sm text-muted-foreground">
				<p>Revision mode &mdash; your original progress is preserved</p>
			</footer>

			{/* Revision summary modal */}
			{showSummary && summaryData && (
				<RevisionSummaryModal
					revisionSummary={summaryData}
					onClose={handleCloseSummary}
					onReviseAgain={handleReviseAgain}
					onBackToDashboard={handleBackToDashboard}
				/>
			)}
		</div>
	);
}

/**
 * Get step indicator color for revision node status.
 */
function getRevisionStepColor(status?: string): string {
	switch (status) {
		case "reviewed":
		case "quiz_passed":
			return "bg-green-500";
		case "quiz_failed":
			return "bg-red-500";
		case "pending":
		default:
			return "bg-muted-foreground/30";
	}
}
