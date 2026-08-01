/**
 * ============================================================================
 * FILE: LearningPage.tsx
 * LOCATION: client/src/features/learning/LearningPage.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Main learning page component that displays an interactive learning path
 *    for a specific session. Handles session routing, real-time progress
 *    tracking, and celebrates course completion with an accessible modal.
 *
 * ROLE IN PROJECT:
 *    Page-level shell for the /learn/:sessionId route. Owns the sticky header,
 *    progress bar, completion modal, and resume banner. Delegates the actual
 *    learning interaction to LearningPathContainer.
 *
 * KEY COMPONENTS:
 *    - LearningPage: Main page wrapper with header navigation and completion modal
 *    - Completion Modal: Accessible overlay celebrating course mastery
 *    - Progress Integration: Syncs with LearningPathContainer via refetch
 *
 * DEPENDENCIES:
 *    - External: react, react-router-dom, @tanstack/react-query, axios
 *    - Internal: @/lib/learningApi, @/lib/utils, @/components/ThemeToggle,
 *                ./LearningPathContainer
 *
 * USAGE:
 *    ```tsx
 *    // Route: /learn/:sessionId
 *    <LearningPage />
 *    ```
 * ============================================================================
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import axios from "axios";
import { BookOpen } from "lucide-react";
import { LearningPathContainer } from "./LearningPathContainer";
import { GenerationStatusPanel } from "./GenerationStatusPanel";
import { CourseSourcesPanel } from "./CourseSourcesPanel";
import { SettingsButton } from "@/components/SettingsButton";
import {
	cancelGeneration,
	deleteSession,
	getCourseResearch,
	getLearningSession,
	resumeGeneration,
} from "@/lib/learningApi";
import { hasWebSearchCapability } from "@/lib/providerSettings";
import { cn } from "@/lib/utils";
import type { LearningSessionWithNodes } from "@/types/learning";
import type { ResearchReport } from "@/types/generation";
import {
	isTerminalGenerationStage,
	useSessionEvents,
} from "./useSessionEvents";

export function LearningPage() {
	const { sessionId } = useParams<{ sessionId: string }>();
	const navigate = useNavigate();
	const queryClient = useQueryClient();
	const [dismissedSessionId, setDismissedSessionId] = useState<string | null>(
		null,
	);
	const [showResumeBanner, setShowResumeBanner] = useState(false);
	const [sourcesOpen, setSourcesOpen] = useState(false);
	const [controlError, setControlError] = useState<string | null>(null);
	const modalRef = useRef<HTMLDivElement>(null);
	const previousFocusRef = useRef<HTMLElement | null>(null);

	// Check for reduced motion preference
	const prefersReducedMotion =
		typeof window !== "undefined" &&
		window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

	// Fetch session for progress bar — 2s repair poll while generation nonterminal
	const {
		data: session,
		refetch,
		isError,
		error: sessionError,
	} = useQuery({
		queryKey: ["learningSession", sessionId],
		queryFn: () => getLearningSession(sessionId!),
		enabled: !!sessionId,
		staleTime: 0,
		refetchInterval: (query) => {
			const stage = query.state.data?.generation?.stage;
			if (!stage || isTerminalGenerationStage(stage)) {
				return false;
			}
			return 2000;
		},
	});

	const generationActive =
		!!session?.generation &&
		!isTerminalGenerationStage(session.generation.stage);
	useSessionEvents(sessionId, generationActive);

	const webRequested = !!session?.generation?.web_search_requested;
	const researchQuery = useQuery({
		queryKey: ["courseResearch", sessionId],
		queryFn: () => getCourseResearch(sessionId!),
		enabled: !!sessionId && webRequested && (sourcesOpen || webRequested),
		staleTime: 0,
		refetchInterval: (query) => {
			const status = query.state.data?.status;
			if (status === "PENDING" || status === "RESEARCHING") {
				return 2000;
			}
			return false;
		},
	});

	const mergeGeneration = useCallback(
		(generation: NonNullable<LearningSessionWithNodes["generation"]>) => {
			if (!sessionId) return;
			queryClient.setQueryData<LearningSessionWithNodes>(
				["learningSession", sessionId],
				(prev) => (prev ? { ...prev, generation } : prev),
			);
		},
		[queryClient, sessionId],
	);

	const cancelMutation = useMutation({
		mutationFn: () => cancelGeneration(sessionId!),
		onSuccess: (data) => {
			mergeGeneration(data.generation);
			setControlError(null);
		},
		onError: (err) => {
			if (axios.isAxiosError(err)) {
				const detail = err.response?.data?.detail;
				if (
					typeof detail === "string" &&
					(err.response?.status === 400 || err.response?.status === 409)
				) {
					setControlError(detail);
					return;
				}
			}
			setControlError("Could not stop generation. Please try again.");
		},
	});

	const resumeMutation = useMutation({
		mutationFn: async () => {
			const needsSearch =
				!!session?.generation?.web_search_requested &&
				session.generation.grounding_status !== "GROUNDED" &&
				session.generation.grounding_status !== "DISABLED";
			if (needsSearch && !hasWebSearchCapability()) {
				throw new Error(
					"Web search capability required. Configure a provider in Settings, then resume.",
				);
			}
			return resumeGeneration(sessionId!, {
				webSearchEnabled: needsSearch,
			});
		},
		onSuccess: (data) => {
			mergeGeneration(data.generation);
			setControlError(null);
			void queryClient.invalidateQueries({
				queryKey: ["learningSession", sessionId],
			});
		},
		onError: (err) => {
			if (err instanceof Error && err.message.includes("Web search")) {
				setControlError(err.message);
				return;
			}
			if (axios.isAxiosError(err)) {
				const detail = err.response?.data?.detail;
				if (
					typeof detail === "string" &&
					(err.response?.status === 400 || err.response?.status === 409)
				) {
					setControlError(detail);
					return;
				}
			}
			setControlError("Could not resume generation. Please try again.");
		},
	});

	const deleteMutation = useMutation({
		mutationFn: () => deleteSession(sessionId!),
		onSuccess: async () => {
			await queryClient.cancelQueries({
				queryKey: ["learningSession", sessionId],
			});
			await queryClient.cancelQueries({
				queryKey: ["courseResearch", sessionId],
			});
			queryClient.removeQueries({
				queryKey: ["learningSession", sessionId],
			});
			queryClient.removeQueries({
				queryKey: ["courseResearch", sessionId],
			});
			void queryClient.invalidateQueries({ queryKey: ["courses"] });
			navigate("/learn");
		},
		onError: () => {
			setControlError("Could not delete course. Please try again.");
		},
	});

	const handleDelete = useCallback(() => {
		const ok = window.confirm(
			"Permanently delete this course and all artifacts? This cannot be undone.",
		);
		if (ok) {
			deleteMutation.mutate();
		}
	}, [deleteMutation]);

	// Invalidate course list on unmount so dashboard is fresh
	useEffect(() => {
		return () => {
			queryClient.invalidateQueries({ queryKey: ["courses"] });
		};
	}, [queryClient]);

	// Flush last-active node with keepalive request on page unload
	useEffect(() => {
		const handleBeforeUnload = () => {
			if (sessionId && session?.last_active_node_id) {
				const baseUrl = import.meta.env.VITE_API_URL || "http://localhost:8000";
				const url = `${baseUrl}/learning/sessions/${sessionId}/last-active`;
				void fetch(url, {
					method: "PATCH",
					headers: {
						"Content-Type": "application/json",
					},
					body: JSON.stringify({ node_id: session.last_active_node_id }),
					keepalive: true,
				}).catch(() => undefined);
			}
		};
		window.addEventListener("beforeunload", handleBeforeUnload);
		return () => window.removeEventListener("beforeunload", handleBeforeUnload);
	}, [sessionId, session?.last_active_node_id]);

	// Show resume banner when session has a last active node
	useEffect(() => {
		if (session?.last_active_node_id) {
			queueMicrotask(() => setShowResumeBanner(true));
			const timer = setTimeout(() => setShowResumeBanner(false), 3000);
			return () => clearTimeout(timer);
		}
	}, [session?.last_active_node_id]);

	// Check for course completion
	const isComplete =
		session?.nodes &&
		session.nodes.length > 0 &&
		session.nodes.every((n) => n.status === "COMPLETED");

	const showCompletion = Boolean(
		sessionId && isComplete && dismissedSessionId !== sessionId,
	);

	// Focus management for modal with focus trap
	useEffect(() => {
		if (showCompletion && modalRef.current) {
			if (!previousFocusRef.current) {
				previousFocusRef.current = document.activeElement as HTMLElement;
			}
			// Focus the first focusable element, or the modal itself
			const focusableSelector =
				'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
			const focusableElements =
				modalRef.current.querySelectorAll<HTMLElement>(focusableSelector);
			if (focusableElements.length > 0) {
				focusableElements[0].focus();
			} else {
				modalRef.current.focus();
			}
		} else if (!showCompletion && previousFocusRef.current) {
			previousFocusRef.current.focus();
			previousFocusRef.current = null;
		}
	}, [showCompletion]);

	// Focus trap and escape key handler for modal
	useEffect(() => {
		if (!showCompletion) return;

		const handleKeyDown = (e: KeyboardEvent) => {
			if (e.key === "Escape") {
				setDismissedSessionId(sessionId ?? null);
				return;
			}

			if (e.key !== "Tab" || !modalRef.current) return;

			const focusableSelector =
				'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
			const focusableElements =
				modalRef.current.querySelectorAll<HTMLElement>(focusableSelector);
			if (focusableElements.length === 0) return;

			const firstElement = focusableElements[0];
			const lastElement = focusableElements[focusableElements.length - 1];

			if (e.shiftKey) {
				// Shift+Tab: if at first element, wrap to last
				if (document.activeElement === firstElement) {
					e.preventDefault();
					lastElement.focus();
				}
			} else {
				// Tab: if at last element, wrap to first
				if (document.activeElement === lastElement) {
					e.preventDefault();
					firstElement.focus();
				}
			}
		};

		document.addEventListener("keydown", handleKeyDown);
		return () => document.removeEventListener("keydown", handleKeyDown);
	}, [sessionId, showCompletion]);

	const closeCompletionModal = useCallback(() => {
		setDismissedSessionId(sessionId ?? null);
	}, [sessionId]);

	if (!sessionId) {
		return (
			<div className="flex flex-col items-center justify-center min-h-screen gap-4">
				<p className="text-muted-foreground">No session ID provided</p>
				<Link
					to="/learn"
					className={cn(
						"px-4 py-2 bg-primary text-primary-foreground rounded-md",
						"hover:bg-primary/90 transition-colors",
						"focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2",
					)}
				>
					Start Learning
				</Link>
			</div>
		);
	}

	// Handle session not found (404)
	const isNotFound =
		isError &&
		axios.isAxiosError(sessionError) &&
		sessionError.response?.status === 404;

	if (isNotFound) {
		return (
			<div className="flex flex-col items-center justify-center min-h-screen gap-4">
				<p className="text-xl font-semibold">Course not found</p>
				<p className="text-muted-foreground">
					This course doesn&apos;t exist or has been removed.
				</p>
				<Link
					to="/learn"
					className={cn(
						"flex items-center gap-2 text-primary hover:text-primary/80 transition-colors",
						"focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 rounded-md px-2 py-1",
					)}
				>
					← Dashboard
				</Link>
			</div>
		);
	}

	return (
		<div className="flex flex-col h-dvh overflow-hidden bg-background">
			{/* Skip to main content link for keyboard users */}
			<a
				href="#main-content"
				className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:px-4 focus:py-2 focus:bg-primary focus:text-primary-foreground focus:rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2"
			>
				Skip to main content
			</a>
			<header className="sticky top-0 z-10 bg-background/95 backdrop-blur border-b shrink-0">
				<div className="max-w-6xl mx-auto px-4 py-3">
					<div className="flex items-center justify-between mb-3">
						<button
							onClick={() => navigate("/learn")}
							className={cn(
								"flex items-center gap-2 text-muted-foreground hover:text-foreground transition-colors",
								"focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 rounded-md px-2 py-1",
							)}
							aria-label="Go to dashboard"
						>
							<span aria-hidden="true">←</span>
							<span>Dashboard</span>
						</button>
						{session?.course_title && (
							<h1 className="text-sm font-medium text-foreground truncate max-w-xs">
								{session.course_title}
							</h1>
						)}
						<nav
							className="flex items-center gap-2 sm:gap-4"
							aria-label="Main navigation"
						>
							{(webRequested || researchQuery.data) && (
								<button
									type="button"
									onClick={() => setSourcesOpen(true)}
									className={cn(
										"inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors",
										"focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 rounded-md px-2 py-1",
									)}
									aria-label="View course sources"
								>
									<BookOpen className="h-4 w-4" aria-hidden="true" />
									<span className="hidden sm:inline">Sources</span>
								</button>
							)}
							{session?.generation?.grounding_status === "GROUNDED" && (
								<span className="text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30">
									Web grounded
								</span>
							)}
							<Link
								to="/learn?new=true"
								className={cn(
									"text-sm text-muted-foreground hover:text-foreground transition-colors",
									"focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 rounded-md px-2 py-1",
								)}
							>
								New Topic
							</Link>
							<SettingsButton />
						</nav>
					</div>
					{session?.generation && (
						<div className="pb-3">
							<GenerationStatusPanel
								generation={session.generation}
								onCancel={() => cancelMutation.mutate()}
								onResume={() => resumeMutation.mutate()}
								onDelete={handleDelete}
								isCancelling={cancelMutation.isPending}
								isResuming={resumeMutation.isPending}
								isDeleting={deleteMutation.isPending}
							/>
							{controlError && (
								<p className="mt-2 text-xs text-destructive" role="alert">
									{controlError}
								</p>
							)}
						</div>
					)}
				</div>
			</header>

			{/* Resume banner */}
			{showResumeBanner && (
				<div
					className="bg-primary/10 text-primary text-sm text-center py-1.5 px-4 animate-in fade-in duration-300 shrink-0"
					role="status"
				>
					Resuming where you left off...
				</div>
			)}

			{/* Main content */}
			<main id="main-content" className="flex-1 min-h-0 overflow-hidden">
				<LearningPathContainer
					sessionId={sessionId}
					session={session ?? undefined}
					initialNodeId={session?.last_active_node_id ?? undefined}
					onOpenSources={() => setSourcesOpen(true)}
					onCourseGenerated={(nextSession) => {
						document.title = `Learn: ${nextSession.course_title}`;
						refetch();
					}}
				/>
			</main>

			<CourseSourcesPanel
				isOpen={sourcesOpen}
				onClose={() => setSourcesOpen(false)}
				report={researchQuery.data as ResearchReport | undefined}
			/>

			{/* Course completion overlay - accessible modal */}
			{showCompletion && (
				<div
					className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
					role="dialog"
					aria-modal="true"
					aria-labelledby="completion-title"
					aria-describedby="completion-description"
					onClick={closeCompletionModal}
				>
					<div
						ref={modalRef}
						tabIndex={-1}
						className={cn(
							"bg-card p-8 rounded-xl text-center max-w-md mx-4",
							!prefersReducedMotion && "animate-in zoom-in-95 duration-300",
							"focus:outline-none",
						)}
						onClick={(e) => e.stopPropagation()}
					>
						{/* Celebration emoji - hidden from screen readers */}
						<div className="text-6xl mb-4" aria-hidden="true">
							🎉
						</div>
						<h2 id="completion-title" className="text-2xl font-bold mb-2">
							Course Complete!
						</h2>
						<p
							id="completion-description"
							className="text-muted-foreground mb-6"
						>
							Congratulations! You've mastered all {session?.nodes.length}{" "}
							topics.
						</p>
						<div className="flex gap-3 justify-center">
							<button
								onClick={closeCompletionModal}
								className={cn(
									"px-4 py-2 border rounded-md hover:bg-muted transition-colors",
									"focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2",
								)}
							>
								Review Topics
							</button>
							<Link
								to="/learn"
								className={cn(
									"px-4 py-2 bg-primary text-primary-foreground rounded-md hover:bg-primary/90 transition-colors",
									"focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2",
								)}
							>
								Learn More
							</Link>
						</div>
					</div>
				</div>
			)}

		</div>
	);
}
