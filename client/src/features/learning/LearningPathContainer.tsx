/**
 * ============================================================================
 * FILE: LearningPathContainer.tsx
 * LOCATION: client/src/features/learning/LearningPathContainer.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Smart container that orchestrates the entire learning path experience.
 *    Handles session loading, course generation, carousel navigation, quiz
 *    result tracking, and celebration animations.
 *
 * ROLE IN PROJECT:
 *    Central hub of the learning feature. Connects session data, mutations,
 *    carousel state, and all child components (ConceptCard, ProgressBar,
 *    MasteryCelebration). Consumed directly by LearningPage.
 *
 * KEY COMPONENTS:
 *    - LearningPathContainer: Main orchestrator for carousel, sessions, celebrations
 *    - Carousel Navigation: Keyboard (arrow keys) and click-based slide navigation
 *    - Session Management: Loads existing sessions or auto-generates new courses
 *    - Error Recovery: Comprehensive error states with retry capabilities
 *    - Toast System: Transient error messages via useErrorToast
 *
 * DEPENDENCIES:
 *    - External: react, @tanstack/react-query, framer-motion, axios
 *    - Internal: @/types/learning, @/lib/learningApi, ./ConceptCard,
 *                ./LearningErrorBoundary, ./animations/MasteryCelebration,
 *                ./ProgressBar, ./animations, ./ErrorStates,
 *                ./useErrorToast, ./useLearningMutations
 *
 * USAGE:
 *    ```tsx
 *    // Load existing session
 *    <LearningPathContainer sessionId="session-123" />
 *
 *    // Generate new course
 *    <LearningPathContainer query="Machine Learning Basics" userId="user-1" />
 *
 *    // With completion callback
 *    <LearningPathContainer
 *      sessionId={sessionId}
 *      onCourseGenerated={(s) => { document.title = s.course_title; }}
 *    />
 *    ```
 * ============================================================================
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { MessageCircle, GripVertical } from "lucide-react";
import type {
	LearningSessionWithNodes,
	QuizSubmitResponse,
	GenerateCourseRequest,
} from "@/types/learning";
import {
	generateCourse,
	getLearningSession,
	updateLastActiveNode,
} from "@/lib/learningApi";
import { ConceptCard } from "./ConceptCard";
import { ChatPanel } from "./ChatPanel";
import { LearningErrorBoundary } from "./LearningErrorBoundary";
import { MasteryCelebration } from "./animations/MasteryCelebration";
import { ProgressBar } from "./ProgressBar";
import { SkeletonCard } from "./SkeletonCard";
import { TableOfContentsModal } from "./TableOfContentsModal";
import { isTerminalGenerationStage } from "./generationEvents";
import {
	carouselSlideVariants,
	carouselSlideReducedMotionVariants,
	prefersReducedMotion,
} from "./animations";
import {
	EmptyState,
	ErrorState,
	GeneratingState,
	LoadingState,
	NotFoundState,
} from "./ErrorStates";
import { ToastContainer, useErrorToast } from "./useErrorToast";
import { useLearningMutations } from "./useLearningMutations";

interface LearningPathContainerProps {
	/** Existing session ID to load */
	sessionId?: string;
	/** Pre-fetched session data (avoids duplicate fetching) */
	session?: LearningSessionWithNodes;
	/** Query to generate new course (if no sessionId) */
	query?: string;
	/** Optional user ID for new sessions */
	userId?: string;
	/** Initial node ID to scroll to on first load */
	initialNodeId?: string;
	/** Callback when course generation completes */
	onCourseGenerated?: (session: LearningSessionWithNodes) => void;
	/** Open course sources panel */
	onOpenSources?: () => void;
}

type CelebrationState = {
	active: boolean;
	nodeId?: string;
	topicTitle?: string;
	isCourseComplete: boolean;
};

export function LearningPathContainer({
	sessionId,
	session: sessionProp,
	query,
	userId,
	initialNodeId,
	onCourseGenerated,
	onOpenSources,
}: LearningPathContainerProps) {
	const queryClient = useQueryClient();
	const [generatedSessionId, setGeneratedSessionId] = useState<
		string | undefined
	>(undefined);
	const activeSessionId = sessionId ?? generatedSessionId;
	const activeSessionKey = activeSessionId ?? "new";
	const { toasts, showError, dismissToast } = useErrorToast();

	// Chat panel state
	const [isChatOpen, setIsChatOpen] = useState(false);
	const [isTOCOpen, setIsTOCOpen] = useState(false);
	const [selectedHeadingIds, setSelectedHeadingIds] = useState<string[]>([]);
	const [prefillMessage, setPrefillMessage] = useState<string>("");
	// Stable nodeId for chat — only updates when user explicitly opens chat,
	// NOT on carousel swipe. Prevents storage wipe during navigation.
	const [chatNodeId, setChatNodeId] = useState<string>("");
	const chatNodeIdRef = useRef<string>("");

	const handleAskQuestion = useCallback((question: string) => {
		setPrefillMessage(question);
		setChatNodeId(chatNodeIdRef.current);
		setIsChatOpen(true);
	}, []);

	// Resizable chat panel state
	const [chatWidthPercent, setChatWidthPercent] = useState(25); // Default = minimum
	const isResizingRef = useRef(false);
	const containerRef = useRef<HTMLDivElement>(null);

	// Resize constraints (in percentage)
	const CHAT_MIN_PERCENT = 25; // Minimum chat width
	const CHAT_MAX_PERCENT = 38; // Maximum chat width

	// Resize handlers
	const handleResizeStart = useCallback((e: React.MouseEvent) => {
		e.preventDefault();
		isResizingRef.current = true;
		document.body.style.cursor = "col-resize";
		document.body.style.userSelect = "none";
	}, []);

	const handleResizeMove = useCallback(
		(e: MouseEvent) => {
			if (!isResizingRef.current || !containerRef.current) return;

			const containerRect = containerRef.current.getBoundingClientRect();
			const containerWidth = containerRect.width;
			const mouseX = e.clientX - containerRect.left;

			// Calculate new chat width percentage
			const newChatPercent =
				((containerWidth - mouseX) / containerWidth) * 100;

			// Apply constraints
			const clampedPercent = Math.max(
				CHAT_MIN_PERCENT,
				Math.min(CHAT_MAX_PERCENT, newChatPercent),
			);

			setChatWidthPercent(clampedPercent);
		},
		[],
	);

	const handleResizeEnd = useCallback(() => {
		isResizingRef.current = false;
		document.body.style.cursor = "";
		document.body.style.userSelect = "";
	}, []);

	// Always listen for mouse move/up (handler checks ref internally)
	useEffect(() => {
		const onMouseMove = (e: MouseEvent) => {
			if (isResizingRef.current) handleResizeMove(e);
		};
		const onMouseUp = () => {
			if (isResizingRef.current) handleResizeEnd();
		};

		window.addEventListener("mousemove", onMouseMove);
		window.addEventListener("mouseup", onMouseUp);

		return () => {
			window.removeEventListener("mousemove", onMouseMove);
			window.removeEventListener("mouseup", onMouseUp);
		};
	}, [handleResizeMove, handleResizeEnd]);

	const handleToggleHeadingChat = useCallback((headingId: string) => {
		setSelectedHeadingIds((prev) =>
			prev.includes(headingId)
				? prev.filter((id) => id !== headingId)
				: [...prev, headingId],
		);
		setChatNodeId(chatNodeIdRef.current);
		setIsChatOpen(true);
	}, []);

	// Track quiz results for feedback display
	const [quizResultsBySession, setQuizResultsBySession] = useState<
		Record<string, Record<string, QuizSubmitResponse>>
	>({});
	const quizResults = quizResultsBySession[activeSessionKey] ?? {};

	// Track celebration state
	const [celebrationBySession, setCelebrationBySession] = useState<
		Record<string, CelebrationState>
	>({});
	const celebration = celebrationBySession[activeSessionKey] ?? {
		active: false,
		isCourseComplete: false,
	};

	// Carousel state: track current slide index and navigation direction
	const [carouselStateBySession, setCarouselStateBySession] = useState<
		Record<string, { currentIndex: number; direction: number }>
	>({});
	const carouselState = carouselStateBySession[activeSessionKey] ?? {
		currentIndex: 0,
		direction: 0,
	};

	// Track initialized sessions and previous active node to prevent aggressive auto-advancing
	const initializedSessionsRef = useRef<Set<string>>(new Set());
	const previousActiveNodeIndexRef = useRef<number>(-1);

	// Highlight state for initial node glow effect
	const [highlightNodeId, setHighlightNodeId] = useState<string | null>(null);
	const highlightTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
		null,
	);

	// Debounced last-active tracking
	const lastActiveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(
		null,
	);
	const pendingNodeIdRef = useRef<string | null>(null);
	const lastFlushedNodeIdRef = useRef<string | null>(null);

	// Fetch existing session (skip if provided via props)
	const {
		data: fetchedSession,
		isLoading: isLoadingSession,
		isError: isSessionError,
		error: sessionError,
		refetch: refetchSession,
	} = useQuery({
		queryKey: ["learningSession", activeSessionId],
		queryFn: () => getLearningSession(activeSessionId ?? ""),
		enabled: !!activeSessionId && !sessionProp,
		retry: (failureCount, error) => {
			if (axios.isAxiosError(error) && error.response?.status === 404) {
				return false;
			}
			return failureCount < 2;
		},
		retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 10000),
	});

	// Use provided session or fetched session
	const session = sessionProp ?? fetchedSession;

	// Generate new course mutation (legacy query-prop path)
	const generateMutation = useMutation({
		mutationFn: (data: GenerateCourseRequest) =>
			generateCourse(data, { webSearchEnabled: false }),
		onSuccess: (accepted) => {
			const shell = accepted.session;
			const data: LearningSessionWithNodes = {
				id: String(shell.id),
				user_id: null,
				query: String(shell.query ?? ""),
				course_title: String(shell.course_title ?? shell.query ?? ""),
				total_nodes:
					typeof shell.total_nodes === "number" ? shell.total_nodes : 0,
				completed_nodes:
					typeof shell.completed_nodes === "number"
						? shell.completed_nodes
						: 0,
				last_active_node_id: null,
				title_finalized:
					typeof shell.title_finalized === "boolean"
						? shell.title_finalized
						: false,
				created_at:
					typeof shell.created_at === "string"
						? shell.created_at
						: new Date().toISOString(),
				updated_at: null,
				nodes: Array.isArray(shell.nodes)
					? (shell.nodes as LearningSessionWithNodes["nodes"])
					: [],
				generation: accepted.generation,
			};
			setGeneratedSessionId(data.id);
			queryClient.setQueryData(["learningSession", data.id], data);
			onCourseGenerated?.(data);
		},
	});

	const handleQuizResult = (result: QuizSubmitResponse) => {
		setQuizResultsBySession((prev) => ({
			...prev,
			[activeSessionKey]: {
				...(prev[activeSessionKey] ?? {}),
				[result.node_id]: result,
			},
		}));
	};

	const handleRetryNeeded = (nodeId: string, result: QuizSubmitResponse) => {
		setQuizResultsBySession((prev) => ({
			...prev,
			[activeSessionKey]: {
				...(prev[activeSessionKey] ?? {}),
				[nodeId]: result,
			},
		}));
	};

	const handleMutationError = (error: Error, context: string) => {
		console.error(`Mutation error (${context}):`, error);
		// Extract server error message if available
		const axiosError = error as { response?: { data?: { detail?: string } } };
		const serverMessage = axiosError?.response?.data?.detail;
		const displayMessage =
			serverMessage || `Failed to ${context}. Please try again.`;
		showError(displayMessage);
	};

	const {
		proceedToQuiz,
		submitAnswer,
		retry,
		continueToNext,
		regenerate,
		advanceToNextQuiz,
		goToPreviousQuiz,
		isAnyLoading,
		isRegenerating,
		isTransitioning,
	} = useLearningMutations({
		sessionId: activeSessionId ?? "",
		onQuizResult: handleQuizResult,
		onMasteryAchieved: (nodeId) => {
			const node = session?.nodes.find((n) => n.id === nodeId);
			const allOtherCompleted = session?.nodes
				.filter((n) => n.id !== nodeId)
				.every((n) => n.status === "COMPLETED");

			setCelebrationBySession((prev) => ({
				...prev,
				[activeSessionKey]: {
					active: true,
					nodeId,
					topicTitle: node?.title,
					isCourseComplete: allOtherCompleted || false,
				},
			}));
		},
		onRetryNeeded: handleRetryNeeded,
		onError: handleMutationError,
	});

	// Find the index of the active node (first non-completed, non-locked)
	const activeNodeIndex =
		session?.nodes.findIndex(
			(n) => n.status !== "LOCKED" && n.status !== "COMPLETED",
		) ?? -1;
	const activeNodeId =
		activeNodeIndex >= 0 ? session?.nodes[activeNodeIndex]?.id : undefined;

	// Initialize carousel index to active node when session loads/changes
	// Also auto-advance when active node changes (e.g., after completing a topic)
	useEffect(() => {
		if (session && session.nodes.length > 0) {
			const fallbackIndex = activeNodeIndex >= 0 ? activeNodeIndex : 0;

			// Check if we haven't initialized this session yet
			if (!initializedSessionsRef.current.has(activeSessionKey)) {
				initializedSessionsRef.current.add(activeSessionKey);

				// Determine initial index: prefer initialNodeId if found
				let startIndex = fallbackIndex;
				if (initialNodeId) {
					const foundIndex = session.nodes.findIndex(
						(n) => n.id === initialNodeId,
					);
					if (foundIndex >= 0) {
						startIndex = foundIndex;
						// Trigger glow highlight on the initial node
						queueMicrotask(() => setHighlightNodeId(initialNodeId));
						if (highlightTimeoutRef.current) {
							clearTimeout(highlightTimeoutRef.current);
						}
						highlightTimeoutRef.current = setTimeout(() => {
							setHighlightNodeId(null);
							highlightTimeoutRef.current = null;
						}, 1500);
					}
					// If not found, fall back to activeNodeIndex (existing behavior)
				}

				previousActiveNodeIndexRef.current = activeNodeIndex;

				// Schedule state update in a microtask to avoid synchronous setState in effect
				queueMicrotask(() => {
					setCarouselStateBySession((prev) => ({
						...prev,
						[activeSessionKey]: { currentIndex: startIndex, direction: 0 },
					}));
				});
			} else if (
				activeNodeIndex >= 0 &&
				activeNodeIndex !== previousActiveNodeIndexRef.current
			) {
				// M11: only auto-advance when user was following the prior active
				// learner node. Module READY arrival must not yank selected skeleton.
				const prevIdx = previousActiveNodeIndexRef.current;
				const wasFollowing =
					carouselState.currentIndex === prevIdx ||
					(prevIdx < 0 && carouselState.currentIndex === 0);
				previousActiveNodeIndexRef.current = activeNodeIndex;

				if (wasFollowing && activeNodeIndex > Math.max(prevIdx, -1)) {
					queueMicrotask(() => {
						const direction =
							activeNodeIndex > carouselState.currentIndex ? 1 : -1;
						setCarouselStateBySession((prev) => ({
							...prev,
							[activeSessionKey]: {
								currentIndex: activeNodeIndex,
								direction,
							},
						}));
					});
				}
			}
		}
	}, [
		session,
		activeNodeIndex,
		activeSessionKey,
		carouselState.currentIndex,
		initialNodeId,
	]);

	useEffect(() => {
		return () => {
			if (highlightTimeoutRef.current) {
				clearTimeout(highlightTimeoutRef.current);
			}
		};
	}, []);

	// Flush pending last-active update to the server
	const flushLastActive = useCallback(() => {
		const nodeIdToFlush = pendingNodeIdRef.current;
		if (nodeIdToFlush && activeSessionId) {
			updateLastActiveNode(activeSessionId, nodeIdToFlush)
				.then(() => {
					lastFlushedNodeIdRef.current = nodeIdToFlush;
				})
				.catch((err) =>
					console.error("Failed to update last active node:", err),
				);
			pendingNodeIdRef.current = null;
		}
		if (lastActiveTimeoutRef.current) {
			clearTimeout(lastActiveTimeoutRef.current);
			lastActiveTimeoutRef.current = null;
		}
	}, [activeSessionId]);

	// Track carousel changes with debounce
	const currentNodeId = session?.nodes[carouselState.currentIndex]?.id;

	useEffect(() => {
		if (!currentNodeId || !activeSessionId) return;

		// Don't track during initial mount
		if (!initializedSessionsRef.current.has(activeSessionKey)) return;
		// Avoid duplicate scheduling when periodic refetches replace session arrays.
		if (
			pendingNodeIdRef.current === currentNodeId &&
			lastActiveTimeoutRef.current
		) {
			return;
		}
		// Skip writes when this node is already persisted.
		if (lastFlushedNodeIdRef.current === currentNodeId) return;

		pendingNodeIdRef.current = currentNodeId;

		if (lastActiveTimeoutRef.current) {
			clearTimeout(lastActiveTimeoutRef.current);
		}

		lastActiveTimeoutRef.current = setTimeout(() => {
			flushLastActive();
		}, 2000);
	}, [currentNodeId, activeSessionId, activeSessionKey, flushLastActive]);

	// Flush on unmount
	useEffect(() => {
		return () => {
			flushLastActive();
		};
	}, [flushLastActive]);

	// Carousel navigation functions
	const goToSlide = useCallback(
		(index: number) => {
			if (!session) return;
			const clampedIndex = Math.max(
				0,
				Math.min(index, session.nodes.length - 1),
			);
			const currentIndex = carouselState.currentIndex;
			const direction =
				clampedIndex > currentIndex ? 1 : clampedIndex < currentIndex ? -1 : 0;

			setCarouselStateBySession((prev) => ({
				...prev,
				[activeSessionKey]: { currentIndex: clampedIndex, direction },
			}));

			// Close chat panel when navigating to a quiz node or feedback node (anti-cheat)
			const targetStatus = session.nodes[clampedIndex]?.status;
			if (targetStatus === "IN_QUIZ" || targetStatus === "SHOWING_FEEDBACK") {
				setIsChatOpen(false);
			}
		},
		[session, carouselState.currentIndex, activeSessionKey],
	);

	const goToNext = useCallback(() => {
		goToSlide(carouselState.currentIndex + 1);
	}, [goToSlide, carouselState.currentIndex]);

	const goToPrev = useCallback(() => {
		goToSlide(carouselState.currentIndex - 1);
	}, [goToSlide, carouselState.currentIndex]);

	// Keyboard navigation handler
	useEffect(() => {
		const handleKeyDown = (event: KeyboardEvent) => {
			// Ignore if user is typing in an input or textarea
			const target = event.target as HTMLElement;
			const isInput =
				target.tagName === "INPUT" ||
				target.tagName === "TEXTAREA" ||
				target.isContentEditable;

			// Also ignore if modifier keys are pressed (e.g. Alt+Left for browser back)
			if (isInput || event.altKey || event.ctrlKey || event.metaKey) {
				return;
			}

			if (event.key === "ArrowLeft") {
				event.preventDefault();
				goToPrev();
			} else if (event.key === "ArrowRight") {
				event.preventDefault();
				goToNext();
			}
		};

		window.addEventListener("keydown", handleKeyDown);
		return () => window.removeEventListener("keydown", handleKeyDown);
	}, [goToNext, goToPrev]);

	// Get current slide node
	const currentSlideNode = session?.nodes[carouselState.currentIndex];
	const canGoNext = session
		? carouselState.currentIndex < session.nodes.length - 1
		: false;
	const canGoPrev = carouselState.currentIndex > 0;

	// Keep ref in sync so chat-open handlers capture correct node
	useEffect(() => {
		chatNodeIdRef.current = currentSlideNode?.id ?? "";
	}, [currentSlideNode?.id]);

	// Close chat panel automatically when switching to or entering a quiz/feedback node (anti-cheat)
	const isQuizNode = currentSlideNode?.status === "IN_QUIZ" || currentSlideNode?.status === "SHOWING_FEEDBACK";

	// Derive effective chat state — always closed during quiz/feedback
	const effectiveIsChatOpen = isChatOpen && !isQuizNode;

	// Close chat panel when proceeding to quiz (anti-cheat)
	const handleProceedToQuiz = useCallback(
		(nodeId: string) => {
			setIsChatOpen(false);
			proceedToQuiz(nodeId);
		},
		[proceedToQuiz],
	);

	// Handle continue to next (manual button click, not auto-scroll)
	const handleContinueToNext = useCallback(
		(nodeId: string) => {
			const nodeIndex = session?.nodes.findIndex((n) => n.id === nodeId) ?? -1;
			const nextNode = session?.nodes[nodeIndex + 1];

			// Always call continueToNext to complete the current node
			// Pass nextNode.id only if it exists
			continueToNext(nodeId, nextNode?.id);
		},
		[session?.nodes, continueToNext],
	);

	// Handle celebration completion
	const handleCelebrationComplete = () => {
		setCelebrationBySession((prev) => ({
			...prev,
			[activeSessionKey]: { active: false, isCourseComplete: false },
		}));
		// Note: We do NOT auto-advance here. The user must click
		// "Continue to Next Topic" in QuizFeedback to proceed.
	};

	// Auto-generate if query provided but no sessionId
	const shouldGenerate = !activeSessionId && !!query;
	const shouldAutoGenerate =
		shouldGenerate &&
		!generateMutation.isPending &&
		!generateMutation.isError &&
		!generateMutation.isSuccess;

	useEffect(() => {
		if (!shouldAutoGenerate || !query) {
			return;
		}
		generateMutation.mutate({ query, user_id: userId });
	}, [query, shouldAutoGenerate, userId, generateMutation]);

	const isGenerating =
		generateMutation.isPending ||
		(shouldGenerate && !generateMutation.data && !generateMutation.isError);

	if (isGenerating) {
		return (
			<>
				<GeneratingState />
				<ToastContainer toasts={toasts} onDismiss={dismissToast} />
			</>
		);
	}

	if (!sessionProp && isLoadingSession) {
		return (
			<>
				<LoadingState message="Loading your learning session..." />
				<ToastContainer toasts={toasts} onDismiss={dismissToast} />
			</>
		);
	}

	const error = sessionError || generateMutation.error;
	if (error) {
		const isGenerateError = Boolean(generateMutation.error && !activeSessionId);
		const isNotFound =
			isSessionError &&
			axios.isAxiosError(error) &&
			error.response?.status === 404;

		if (isNotFound) {
			return (
				<>
					<NotFoundState type="session" />
					<ToastContainer toasts={toasts} onDismiss={dismissToast} />
				</>
			);
		}

		return (
			<>
				<ErrorState
					title={
						isGenerateError
							? "Failed to generate course"
							: "Failed to load session"
					}
					message={
						isGenerateError
							? "We couldn't generate your learning path. Please try again."
							: "We couldn't load your learning session. Please try again."
					}
					onRetry={() => {
						if (activeSessionId && refetchSession) {
							refetchSession();
							return;
						}
						if (query) {
							generateMutation.mutate({ query, user_id: userId });
						}
					}}
				/>
				<ToastContainer toasts={toasts} onDismiss={dismissToast} />
			</>
		);
	}

	if (!session) {
		return (
			<>
				<NotFoundState type="session" />
				<ToastContainer toasts={toasts} onDismiss={dismissToast} />
			</>
		);
	}

	const generationRunning =
		!!session.generation &&
		!isTerminalGenerationStage(session.generation.stage);

	if (session.nodes.length === 0) {
		if (generationRunning || session.generation) {
			return (
				<>
					<div className="flex flex-col items-center justify-center gap-3 p-8 text-center">
						<p className="text-sm font-medium text-foreground">
							Preparing your course outline...
						</p>
						<p className="text-xs text-muted-foreground max-w-md">
							Research and table of contents will appear as generation
							progresses.
						</p>
					</div>
					<ToastContainer toasts={toasts} onDismiss={dismissToast} />
				</>
			);
		}
		return (
			<>
				<EmptyState
					title="No topics yet"
					message="This learning path doesn't have any topics."
					action={
						query
							? {
									label: "Generate Topics",
									onClick: () =>
										generateMutation.mutate({ query, user_id: userId }),
								}
							: undefined
					}
				/>
				<ToastContainer toasts={toasts} onDismiss={dismissToast} />
			</>
		);
	}

	// M12: keep ERROR cards visible with per-card regen (no global collapse).
	const webSourcesRequested = !!session.generation?.web_search_requested;
	const sourcesCallback = webSourcesRequested ? onOpenSources : undefined;

	// Render learning path
	return (
		<>
			<LearningErrorBoundary
				onError={(boundaryError: Error) => {
					console.error("Learning component crashed:", boundaryError);
				}}
			>
				<div ref={containerRef} className="flex w-full h-full overflow-hidden">
				{/* Main content area - shrinks when chat is open */}
				<motion.div
					className="flex flex-col gap-6 p-4 overflow-y-auto"
					animate={{
						flex: effectiveIsChatOpen
							? `0 0 ${100 - chatWidthPercent}%`
							: "1 1 100%",
					}}
					transition={{ type: "spring", damping: 30, stiffness: 300 }}
				>
					<div className={cn("mx-auto w-full", effectiveIsChatOpen ? "max-w-5xl" : "max-w-6xl")}>
							{/* Header */}
							<header className="text-center">
								<h1 className="text-2xl font-bold">{session.course_title}</h1>
								<p className="text-muted-foreground mt-1">
									{session.completed_nodes} of {session.total_nodes} completed
								</p>
							</header>

							{/* Progress bar using specialized component */}
							<ProgressBar
								nodes={session.nodes}
							/>

							{/* Mastery celebration overlay */}
							<MasteryCelebration
								active={celebration.active}
								topicTitle={celebration.topicTitle}
								isCourseComplete={celebration.isCourseComplete}
								onComplete={handleCelebrationComplete}
							/>

							{/* Carousel container with single ConceptCard */}
							<div
								className="relative"
								role="region"
								aria-roledescription="carousel"
								aria-label="Learning path carousel"
							>
								{/* Slide counter */}
								<div className="flex justify-center items-center gap-3 mb-4 text-sm text-muted-foreground">
									<span>
										Topic {carouselState.currentIndex + 1} of{" "}
										{session.nodes.length}
									</span>
								</div>

								{/* Single ConceptCard with direction-aware slide animation */}
								<div className="relative overflow-hidden">
									<AnimatePresence
										mode="wait"
										custom={carouselState.direction}
										initial={false}
									>
										{currentSlideNode && (
											<motion.div
												key={currentSlideNode.id}
												id={`node-${currentSlideNode.id}`}
												tabIndex={-1}
												role="group"
												aria-roledescription="slide"
												aria-label={`${currentSlideNode.title}, slide ${carouselState.currentIndex + 1} of ${session.nodes.length}`}
												custom={carouselState.direction}
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
												{highlightNodeId === currentSlideNode.id && (
													<motion.div
														className="absolute inset-0 rounded-xl pointer-events-none"
														initial={{
															boxShadow: "0 0 0px rgba(255, 212, 0, 0)",
														}}
														animate={{
															boxShadow: [
																"0 0 20px rgba(255, 212, 0, 0.6)",
																"0 0 0px rgba(255, 212, 0, 0)",
															],
														}}
														transition={{ duration: 1.5, ease: "easeOut" }}
														aria-hidden="true"
													/>
												)}
												{(() => {
												const moduleStatus =
													currentSlideNode.module_status ?? "READY";
												const genStage = session.generation?.stage;
												const skeletonStatic =
													genStage === "CANCELLED" ||
													genStage === "PAUSED" ||
													!generationRunning;
												if (
													moduleStatus === "SKELETON" ||
													moduleStatus === "GENERATING"
												) {
													return (
														<SkeletonCard
															title={currentSlideNode.title}
															sequenceIndex={currentSlideNode.sequence_index}
															animated={
																moduleStatus === "GENERATING" && !skeletonStatic
															}
														/>
													);
												}
												return (
													<ConceptCard
														node={currentSlideNode}
														onOpenTOC={() => setIsTOCOpen(true)}
														onViewSources={sourcesCallback}
														isActive={currentSlideNode.id === activeNodeId}
														quizResult={quizResults[currentSlideNode.id]}
														onProceedToQuiz={handleProceedToQuiz}
														onQuizSubmit={submitAnswer}
														onRetryQuiz={retry}
														onContinueToNext={handleContinueToNext}
														onNextQuiz={() =>
															advanceToNextQuiz(currentSlideNode.id)
														}
														onPreviousQuiz={goToPreviousQuiz}
														onRegenerate={regenerate}
														isRegenerating={isRegenerating}
														isTransitioning={isTransitioning}
														canSkip={canGoNext}
														onSkipNode={() => {
															if (canGoNext) {
																goToNext();
															}
														}}
														onPrevious={goToPrev}
														canPrevious={canGoPrev}
														selectedHeadingIds={selectedHeadingIds}
														onToggleHeadingChat={handleToggleHeadingChat}
														onAskQuestion={handleAskQuestion}
													/>
												);
											})()}
											</motion.div>
										)}
									</AnimatePresence>
								</div>
							</div>

							{/* Loading overlay for mutations */}
							{isAnyLoading && (
								<div
									className="fixed bottom-4 right-4 bg-background border rounded-lg shadow-lg p-3 flex items-center gap-2"
									role="status"
									aria-busy="true"
									aria-label="Loading"
								>
									<div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary" />
									<span className="text-sm text-muted-foreground">
										Updating...
									</span>
								</div>
							)}
						</div>
					</motion.div>

				{/* Resize handle */}
				{effectiveIsChatOpen && (
					<div
						className="w-1 bg-border hover:bg-(--cyber-yellow) cursor-col-resize shrink-0 transition-colors relative group"
						onMouseDown={handleResizeStart}
						role="separator"
						aria-orientation="vertical"
						aria-label="Resize chat panel"
						tabIndex={0}
						onKeyDown={(e) => {
							if (e.key === "ArrowLeft") {
								setChatWidthPercent((prev) =>
									Math.min(CHAT_MAX_PERCENT, prev + 2),
								);
							} else if (e.key === "ArrowRight") {
								setChatWidthPercent((prev) =>
									Math.max(CHAT_MIN_PERCENT, prev - 2),
								);
							}
						}}
					>
						<div className="absolute inset-y-0 -left-1 -right-1" />
						<div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity">
							<GripVertical className="h-4 w-4 text-muted-foreground" />
						</div>
					</div>
				)}

				{/* Chat Panel - slides in from right */}
				<ChatPanel
					isOpen={effectiveIsChatOpen}
					onClose={() => setIsChatOpen(false)}
					sessionId={activeSessionId ?? ""}
					nodeId={chatNodeId}
					selectedHeadingIds={selectedHeadingIds}
					onClearHeadings={() => setSelectedHeadingIds([])}
					isCourseComplete={
						session?.nodes &&
						session.nodes.length > 0 &&
						session.nodes.every((n) => n.status === "COMPLETED")
					}
					widthPercent={chatWidthPercent}
					prefillMessage={prefillMessage}
					onPrefillConsumed={() => setPrefillMessage("")}
				/>
				</div>
			</LearningErrorBoundary>

		{/* Chat FAB - bottom-right fixed (hidden during quizzes/feedback) */}
		{!effectiveIsChatOpen && !isQuizNode && (
		<button
				onClick={() => {
					setChatNodeId(chatNodeIdRef.current);
					setIsChatOpen(true);
				}}
				className="fixed bottom-6 right-6 z-30 h-14 w-14 rounded-full bg-(--cyber-yellow) text-black shadow-lg hover:bg-(--cyber-yellow)/90 transition-colors flex items-center justify-center"
				aria-label="Open concept chat"
			>
				<MessageCircle className="h-6 w-6" />
			</button>
			)}

			<TableOfContentsModal
				isOpen={isTOCOpen}
				onClose={() => setIsTOCOpen(false)}
				nodes={session.nodes}
				currentNodeId={currentSlideNode?.id}
				onSelectTopic={goToSlide}
			/>

			<ToastContainer toasts={toasts} onDismiss={dismissToast} />
		</>
	);
}
