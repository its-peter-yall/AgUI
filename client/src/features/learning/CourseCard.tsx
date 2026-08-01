/**
 * ============================================================================
 * FILE: CourseCard.tsx
 * LOCATION: client/src/features/learning/CourseCard.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Card component displaying a single learning course with progress and actions.
 *
 * ROLE IN PROJECT:
 *    Renders course summaries in the dashboard grid with two states: in-progress
 *    (progress bar, Resume button, last active topic) and completed (green badge,
 *    Revise/Practice Quizzes buttons). Includes delete confirmation and expandable
 *    revision history.
 *
 * KEY COMPONENTS:
 *    - CourseCard: Animated article card with progress bar and action buttons
 *    - Delete confirmation overlay: Inline confirm/cancel dialog
 *
 * DEPENDENCIES:
 *    - External: react, framer-motion, lucide-react
 *    - Internal: @/types/learning, @/lib/utils, ./RevisionHistoryList
 *
 * USAGE:
 *    <CourseCard session={session} onResume={handleResume} onRevise={handleRevise} />
 * ============================================================================
 */
// CourseCard.tsx
// Card component displaying a single learning course with progress and actions

// Renders a course summary card for the dashboard with two visual states:
// - In-progress: Shows progress bar, "Resume Course" button, last active topic
// - Completed: Shows green checkmark, "Revise Course" and "Practice Quizzes" buttons
// Key features include Cyber Yellow progress bar (adapts to theme), glassmorphism styling,
// Framer Motion hover animation, and expandable revision history list.

// @see: client/src/types/learning.ts (LearningSessionSummary)
// @see: RevisionHistoryList.tsx (expandable revision history)
// @see: conductor/product-guidelines.md (visual identity)
// @note: onRevise accepts a mode param ('full_review' | 'quiz_only')

import { useState, useRef, useEffect } from "react";
import { motion } from "framer-motion";
import { CheckCircle, Trash2, AlertCircle } from "lucide-react";

import type { LearningSessionSummary } from "@/types/learning";
import { cn } from "@/lib/utils";
import { RevisionHistoryList } from "./RevisionHistoryList";

export interface CourseCardProps {
	session: LearningSessionSummary;
	onResume: (sessionId: string) => void;
	onRevise: (sessionId: string, mode: "full_review" | "quiz_only") => void;
	onViewRevision?: (revisionId: string) => void;
	onDelete?: (sessionId: string) => void | Promise<void>;
}

function formatDate(isoString: string): string {
	return new Intl.DateTimeFormat("en-US", {
		month: "short",
		day: "numeric",
	}).format(new Date(isoString));
}

function generationBadge(
	generation: CourseCardProps["session"]["generation"],
): { label: string; className: string } | null {
	if (!generation) return null;
	switch (generation.stage) {
		case "COMPLETE":
			return null;
		case "COMPLETE_DEGRADED":
			return {
				label: "Complete with research warning",
				className:
					"bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/30",
			};
		case "CANCELLED":
			return {
				label: "Cancelled",
				className:
					"bg-zinc-500/10 text-zinc-500 border border-zinc-500/30",
			};
		case "PAUSED":
			return {
				label: "Paused",
				className:
					"bg-blue-500/10 text-blue-500 border border-blue-500/30",
			};
		case "FAILED":
			return {
				label: "Failed",
				className:
					"bg-red-500/10 text-red-500 border border-red-500/30",
			};
		default:
			return {
				label: "Generating",
				className:
					"bg-[#ffb74d]/15 text-[#ffb74d] border border-[#ffb74d]/40",
			};
	}
}

export function CourseCard({
	session,
	onResume,
	onRevise,
	onViewRevision,
	onDelete,
}: CourseCardProps) {
	const isCompleted = session.status === "completed";
	const progressPercent = Math.floor(session.progress_percent);
	// M10: prefer nested generation; fall back to flat list fields.
	const generation =
		session.generation ??
		(session.generation_stage
			? ({
					stage: session.generation_stage,
					grounding_status: session.grounding_status ?? "PENDING",
				} as CourseCardProps["session"]["generation"])
			: null);
	const genBadge = generationBadge(generation);
	const [showConfirm, setShowConfirm] = useState(false);
	const [isDeleting, setIsDeleting] = useState(false);
	const cancelBtnRef = useRef<HTMLButtonElement>(null);
	const deleteTriggerRef = useRef<HTMLButtonElement>(null);

	// Focus the Cancel button when the delete confirmation dialog opens
	useEffect(() => {
		if (showConfirm) {
			cancelBtnRef.current?.focus();
		}
	}, [showConfirm]);

	const handleKeyDown = (e: React.KeyboardEvent) => {
		if (e.key === "Enter" || e.key === " ") {
			e.preventDefault();
			if (isCompleted) {
				onRevise(session.id, "full_review");
			} else {
				onResume(session.id);
			}
		}
	};

	const handleDeleteClick = (e: React.MouseEvent) => {
		e.stopPropagation();
		deleteTriggerRef.current = e.currentTarget as HTMLButtonElement;
		setShowConfirm(true);
	};

	const handleConfirmDelete = async (e: React.MouseEvent) => {
		e.stopPropagation();
		if (isDeleting) return;

		setIsDeleting(true);
		try {
			await onDelete?.(session.id);
		} finally {
			setIsDeleting(false);
			setShowConfirm(false);
		}
	};

	const handleCancelDelete = (e: React.MouseEvent) => {
		e.stopPropagation();
		setShowConfirm(false);
		// Return focus to the delete trigger button
		deleteTriggerRef.current?.focus();
	};

	const handleConfirmKeyDown = (e: React.KeyboardEvent) => {
		if (e.key === "Escape") {
			e.stopPropagation();
			setShowConfirm(false);
			deleteTriggerRef.current?.focus();
		}
	};

	return (
		<motion.article
			className={cn(
				"group relative rounded-xl border border-border/60 p-5",
				"bg-card/85 backdrop-blur-sm shadow-sm hover:shadow-md hover:border-border transition-all duration-300",
				"flex flex-col gap-3",
				"w-full",
				"cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2",
			)}
			whileHover={{ scale: 1.015 }}
			transition={{ type: "spring", stiffness: 300, damping: 20 }}
			data-testid="course-card"
			role="article"
			tabIndex={0}
			onKeyDown={handleKeyDown}
			onClick={(e) => {
				if ((e.target as HTMLElement).closest("button")) return;
				if (isCompleted) {
					onRevise(session.id, "full_review");
				} else {
					onResume(session.id);
				}
			}}
		>
			{/* Delete button - shown on hover */}
			{onDelete && !showConfirm && (
				<button
					onClick={handleDeleteClick}
					className={cn(
						"absolute top-3 right-3 p-2 rounded-lg",
						"bg-background/80 backdrop-blur-sm",
						"text-muted-foreground hover:text-red-500",
						"opacity-0 group-hover:opacity-100",
						"transition-all duration-200",
						"focus:outline-none focus:ring-2 focus:ring-(--cyber-yellow) focus:ring-offset-2 focus:ring-offset-background",
					)}
					aria-label="Delete course"
					data-testid="delete-course-button"
				>
					<Trash2 className="h-4 w-4" aria-hidden="true" />
				</button>
			)}

			{/* Confirmation dialog */}
			{showConfirm && (
				<div
					role="alertdialog"
					aria-labelledby="delete-dialog-title"
					aria-describedby="delete-dialog-description"
					className={cn(
						"absolute inset-0 z-10 rounded-xl",
						"bg-background/95 backdrop-blur-sm",
						"flex flex-col items-center justify-center gap-4 p-5",
						"border border-(--cyber-yellow)/30",
					)}
					onClick={(e) => e.stopPropagation()}
					onKeyDown={handleConfirmKeyDown}
				>
					<div className="flex items-center gap-2 text-(--cyber-yellow)">
						<AlertCircle className="h-5 w-5" aria-hidden="true" />
						<span className="font-semibold" id="delete-dialog-title">
							Delete Course?
						</span>
					</div>
					<p
						className="text-sm text-muted-foreground text-center"
						id="delete-dialog-description"
					>
						This will permanently delete &quot;{session.course_title}&quot; and
						all associated progress.
					</p>
					<div className="flex items-center gap-3">
						<button
							ref={cancelBtnRef}
							onClick={handleCancelDelete}
							disabled={isDeleting}
							className={cn(
								"px-4 py-2 rounded-lg text-sm font-medium",
								"border border-border text-foreground",
								"hover:bg-muted transition-colors",
								"disabled:opacity-50 disabled:cursor-not-allowed",
								"focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-background",
							)}
						>
							Cancel
						</button>
						<button
							onClick={handleConfirmDelete}
							disabled={isDeleting}
							className={cn(
								"px-4 py-2 rounded-lg text-sm font-medium",
								"bg-red-600 text-white",
								"hover:bg-red-700 transition-colors",
								"disabled:opacity-50 disabled:cursor-not-allowed",
								"focus:outline-none focus:ring-2 focus:ring-red-600 focus:ring-offset-2 focus:ring-offset-background",
							)}
						>
							{isDeleting ? "Deleting..." : "Delete"}
						</button>
					</div>
				</div>
			)}

			{/* Header: title + status */}
			<div className="flex items-start justify-between gap-3 pr-8">
				<h3 className="text-base font-semibold text-foreground line-clamp-2 flex-1">
					{session.course_title}
				</h3>
				<div className="flex flex-col items-end gap-1 shrink-0">
					{genBadge && (
						<span
							className={cn(
								"text-[10px] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full",
								genBadge.className,
							)}
							data-testid="generation-badge"
						>
							{genBadge.label}
						</span>
					)}
					{isCompleted && !genBadge && (
						<span
							className="flex items-center gap-1 text-green-400"
							data-testid="completed-badge"
							aria-label="Course Completed"
						>
							<CheckCircle className="h-4 w-4" aria-hidden="true" />
							<span className="text-xs font-medium">Completed</span>
						</span>
					)}
					{isCompleted && genBadge?.label.startsWith("Complete") && (
						<span
							className="flex items-center gap-1 text-green-400"
							data-testid="completed-badge"
							aria-label="Course Completed"
						>
							<CheckCircle className="h-4 w-4" aria-hidden="true" />
							<span className="text-xs font-medium">Completed</span>
						</span>
					)}
				</div>
			</div>

			{/* Query text */}
			<p className="text-sm text-muted-foreground line-clamp-2">
				{session.query}
			</p>

			{/* Progress bar */}
			<div className="space-y-1.5">
				<div
					className="h-2 w-full rounded-full bg-muted overflow-hidden"
					role="progressbar"
					aria-valuenow={progressPercent}
					aria-valuemin={0}
					aria-valuemax={100}
					aria-label={`Course progress: ${progressPercent}%`}
				>
					<div
						className={cn(
							"h-full rounded-full transition-all duration-500 ease-out",
							isCompleted ? "bg-green-400" : "bg-(--cyber-yellow)",
						)}
						style={{ width: `${progressPercent}%` }}
						data-testid="progress-bar-fill"
					/>
				</div>
				<div className="flex items-center justify-between text-xs text-muted-foreground">
					<span>
						{session.completed_nodes}/{session.total_nodes} topics completed
					</span>
					<span>{progressPercent}%</span>
				</div>
			</div>

			{/* Last active node (in-progress only) */}
			{!isCompleted && session.last_active_node_title && (
				<p className="text-xs text-muted-foreground">
					Last active:{" "}
					<span className="text-foreground">
						{session.last_active_node_title}
					</span>
				</p>
			)}

			{/* Actions */}
			<div className="flex items-center justify-between gap-2 mt-1">
				{isCompleted ? (
					<div className="flex items-center gap-2 flex-wrap">
						<button
							onClick={() => onRevise(session.id, "full_review")}
							className={cn(
								"rounded-lg px-3 py-1.5 text-sm font-medium",
								"bg-primary text-primary-foreground",
								"hover:bg-primary/90 transition-colors",
								"focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-background",
							)}
						>
							Revise Course
						</button>
						<button
							onClick={() => onRevise(session.id, "quiz_only")}
							className={cn(
								"rounded-lg px-3 py-1.5 text-sm font-medium",
								"border border-primary/50 text-primary",
								"hover:bg-primary/10 transition-colors",
								"focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-background",
							)}
						>
							Practice Quizzes
						</button>
					</div>
				) : (
					<button
						onClick={() => onResume(session.id)}
						className={cn(
							"rounded-lg px-4 py-1.5 text-sm font-medium",
							"bg-primary text-primary-foreground",
							"hover:bg-primary/90 transition-colors",
							"focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-background",
						)}
					>
						Resume Course
					</button>
				)}
				<span className="text-xs text-muted-foreground shrink-0">
					{isCompleted
						? `Completed: ${formatDate(session.completed_at ?? session.updated_at)}`
						: `Started: ${formatDate(session.created_at)}`}
				</span>
			</div>

			{/* Revision history section */}
			{session.revision_count > 0 && onViewRevision && (
				<RevisionHistoryList
					sessionId={session.id}
					onViewRevision={onViewRevision}
				/>
			)}
		</motion.article>
	);
}
