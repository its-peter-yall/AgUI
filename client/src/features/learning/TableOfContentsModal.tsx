/**
 * ============================================================================
 * FILE: TableOfContentsModal.tsx
 * LOCATION: client/src/features/learning/TableOfContentsModal.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    A modal dialog showing the Table of Contents of the learning course.
 *
 * ROLE IN PROJECT:
 *    Provides users with a structured roadmap view of all topics in a course,
 *    allowing navigation to unlocked/completed topics and displaying status
 *    legends that were moved from the progress bar.
 *
 * KEY COMPONENTS:
 *    - TableOfContentsModal: Main modal component containing list and legends.
 *
 * DEPENDENCIES:
 *    - External: react, framer-motion, lucide-react
 *    - Internal: @/lib/utils (cn), @/types/learning (ConceptNode)
 *
 * USAGE:
 *    ```tsx
 *    <TableOfContentsModal
 *      isOpen={isTOCOpen}
 *      onClose={() => setIsTOCOpen(false)}
 *      nodes={nodes}
 *      currentNodeId={currentNodeId}
 *      onSelectTopic={handleSelectTopic}
 *    />
 *    ```
 * ============================================================================
 */

import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Lock, CheckCircle2, PlayCircle, HelpCircle } from "lucide-react";
import type { ConceptNode } from "@/types/learning";
import { cn } from "@/lib/utils";

interface TableOfContentsModalProps {
	isOpen: boolean;
	onClose: () => void;
	nodes: ConceptNode[];
	currentNodeId?: string;
	onSelectTopic: (index: number) => void;
}

function getNumQuizzes(node: ConceptNode): string | number {
	if (node.total_quizzes !== undefined && node.total_quizzes !== null) return node.total_quizzes;
	if (node.quiz_set) return node.quiz_set.quizzes.length;
	if (node.quiz_set_hidden) return node.quiz_set_hidden.total_quizzes || node.quiz_set_hidden.quizzes.length;
	if (node.quiz || node.quiz_hidden) return 1;
	
	return "-";
}

export function TableOfContentsModal({
	isOpen,
	onClose,
	nodes,
	currentNodeId,
	onSelectTopic,
}: TableOfContentsModalProps) {
	const modalRef = useRef<HTMLDivElement>(null);
	const activeRowRef = useRef<HTMLTableRowElement | null>(null);

	// Focus trap & Escape key
	useEffect(() => {
		if (!isOpen) return;
		const previousActiveElement = document.activeElement as HTMLElement | null;
		
		const handleKeyDown = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				onClose();
				return;
			}
			if (event.key !== "Tab") return;

			const focusableSelector = 'button, [href], [tabindex]:not([tabindex="-1"])';
			const focusableElements = modalRef.current?.querySelectorAll<HTMLElement>(focusableSelector);
			if (!focusableElements || focusableElements.length === 0) return;

			const firstElement = focusableElements[0];
			const lastElement = focusableElements[focusableElements.length - 1];

			if (event.shiftKey) {
				if (document.activeElement === firstElement) {
					event.preventDefault();
					lastElement.focus();
				}
			} else {
				if (document.activeElement === lastElement) {
					event.preventDefault();
					firstElement.focus();
				}
			}
		};

		modalRef.current?.focus();
		window.addEventListener("keydown", handleKeyDown);
		return () => {
			window.removeEventListener("keydown", handleKeyDown);
			previousActiveElement?.focus();
		};
	}, [isOpen, onClose]);

	// Auto-scroll active row into view
	useEffect(() => {
		if (isOpen && activeRowRef.current) {
			activeRowRef.current.scrollIntoView({
				behavior: "smooth",
				block: "nearest",
			});
		}
	}, [isOpen]);

	if (!isOpen) return null;

	return (
		<AnimatePresence>
			<motion.div
				className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
				initial={{ opacity: 0 }}
				animate={{ opacity: 1 }}
				exit={{ opacity: 0 }}
				onClick={(e) => e.target === e.currentTarget && onClose()}
			>
				<motion.div
					ref={modalRef}
					role="dialog"
					aria-modal="true"
					aria-label="Table of Contents"
					tabIndex={-1}
					className="relative w-full max-w-4xl bg-card/95 backdrop-blur-md border border-border shadow-2xl rounded-xl p-6 flex flex-col focus:outline-none"
					initial={{ scale: 0.95, opacity: 0 }}
					animate={{ scale: 1, opacity: 1 }}
					exit={{ scale: 0.95, opacity: 0 }}
					transition={{ type: "spring", stiffness: 300, damping: 25 }}
				>
					{/* Close Button */}
					<button
						onClick={onClose}
						className="absolute top-4 right-4 p-2 rounded-md hover:bg-muted text-muted-foreground transition-colors cursor-pointer"
						aria-label="Close modal"
					>
						<X className="w-5 h-5" />
					</button>

					{/* Title */}
					<h2 className="text-xl font-bold text-foreground mb-4">Table of Contents</h2>

					{/* Table Container - Fits exactly 10 items (approx. 48px per row + headers) */}
					<div className="overflow-x-auto border border-border/60 rounded-lg bg-muted/20">
						<table className="w-full border-collapse text-left text-sm flex flex-col">
							<thead className="w-full flex">
								<tr className="border-b border-border/60 bg-muted/50 text-xs font-semibold text-muted-foreground uppercase tracking-wider h-10 flex w-full items-center">
									<th className="px-4 w-[10%] text-center">#</th>
									<th className="px-4 w-[50%]">Topic Name</th>
									<th className="px-4 w-[15%] text-center">Quizzes</th>
									<th className="px-4 w-[15%] text-center">Difficulty</th>
									<th className="px-4 w-[10%] text-center">Status</th>
								</tr>
							</thead>
							<tbody className="divide-y divide-border/40 overflow-y-auto block max-h-[480px] w-full scrollbar-thin">
								{nodes.map((node, index) => {
									const isCurrent = node.id === currentNodeId;
									const moduleStatus = node.module_status ?? "READY";
									const isGeneratingModule =
										moduleStatus === "SKELETON" || moduleStatus === "GENERATING";
									const isLocked =
										node.status === "LOCKED" && !isGeneratingModule;
									const isCompleted = node.status === "COMPLETED";
									const numQuizzes = getNumQuizzes(node);

									let statusLabel = "In Progress";
									let statusBadgeClass = "bg-amber-500/10 text-amber-400 border border-amber-500/20";
									let statusIcon = <PlayCircle className="w-4 h-4" />;
									if (isGeneratingModule) {
										statusLabel = "Generating";
										statusBadgeClass = "bg-[#ffb74d]/10 text-[#ffb74d] border border-[#ffb74d]/30";
										statusIcon = <HelpCircle className="w-4 h-4" />;
									} else if (isLocked) {
										statusLabel = "Locked";
										statusBadgeClass = "bg-zinc-800/50 text-zinc-500 border border-zinc-700/30";
										statusIcon = <Lock className="w-4 h-4" />;
									} else if (isCompleted) {
										statusLabel = "Mastered";
										statusBadgeClass = "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20";
										statusIcon = <CheckCircle2 className="w-4 h-4" />;
									} else if (node.status === "ERROR" || moduleStatus === "ERROR") {
										statusLabel = "In Progress";
										statusIcon = <HelpCircle className="w-4 h-4" />;
									}

									const complexityBadgeClass = 
										node.complexity === "Advanced" ? "bg-rose-500/10 text-rose-400 border border-rose-500/20" :
										node.complexity === "Intermediate" ? "bg-amber-500/10 text-amber-400 border border-amber-500/20" :
										"bg-emerald-500/10 text-emerald-400 border border-emerald-500/20";

									return (
										<tr
											key={node.id}
											ref={isCurrent ? activeRowRef : undefined}
											className={cn(
												"h-12 flex w-full items-center hover:bg-muted/10 transition-colors",
												isCurrent && "bg-primary/5 border-l-2 border-primary"
											)}
										>
											<td className="px-4 text-center font-mono text-muted-foreground w-[10%]">
												#{node.sequence_index + 1}
											</td>
											<td className="px-4 w-[50%] overflow-hidden text-ellipsis whitespace-nowrap">
												{!isLocked ? (
													<button
														onClick={() => {
															onSelectTopic(index);
															onClose();
														}}
														className="text-left font-medium text-primary hover:underline cursor-pointer focus:outline-none focus:ring-1 focus:ring-primary rounded"
													>
														{node.title}
													</button>
												) : (
													<span className="text-muted-foreground font-medium flex items-center gap-1.5 cursor-not-allowed">
														{node.title}
													</span>
												)}
											</td>
											<td className="px-4 text-center text-muted-foreground w-[15%]">
												{numQuizzes}
											</td>
											<td className="px-4 text-center w-[15%]">
												{node.complexity && (
													<span className={cn("text-xs font-semibold px-2 py-0.5 rounded-full", complexityBadgeClass)}>
														{node.complexity}
													</span>
												)}
											</td>
											<td className="px-4 w-[10%] flex justify-center">
												<span className={cn("text-xs font-semibold px-2 py-0.5 rounded-full flex items-center gap-1", statusBadgeClass)} title={statusLabel}>
													{statusIcon}
													<span>{statusLabel}</span>
												</span>
											</td>
										</tr>
									);
								})}
							</tbody>
						</table>
					</div>

					{/* Bottom Legends & Key (Moved from Progress Bar) */}
					<div className="flex items-center gap-6 mt-6 pt-4 border-t border-border/60 text-xs text-muted-foreground select-none">
						<span className="font-semibold text-foreground">Status Legend:</span>
						<div className="flex items-center gap-1.5">
							<span className="w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-[0_0_6px_rgba(16,185,129,0.5)]" />
							<span>Mastered</span>
						</div>
						<div className="flex items-center gap-1.5">
							<span className="w-2.5 h-2.5 rounded-full bg-amber-500 shadow-[0_0_6px_rgba(245,158,11,0.5)] animate-pulse" />
							<span>In progress</span>
						</div>
						<div className="flex items-center gap-1.5">
							<span className="w-2.5 h-2.5 rounded-full bg-zinc-600" />
							<span>Locked</span>
						</div>
					</div>
				</motion.div>
			</motion.div>
		</AnimatePresence>
	);
}
