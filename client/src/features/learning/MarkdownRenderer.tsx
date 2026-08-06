/**
 * ============================================================================
 * FILE: MarkdownRenderer.tsx
 * LOCATION: client/src/features/learning/MarkdownRenderer.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Renders markdown content as styled HTML for concept explanations in the
 *    learning path. Wraps react-markdown with custom styling, GitHub Flavored
 *    Markdown (GFM) support, and HTML sanitization for security.
 *
 * ROLE IN PROJECT:
 *    Shared rendering utility within the learning feature. Consumed by
 *    ConceptCard to display AI-generated explanations with consistent
 *    typography and Cyber Yellow accent colors aligned with the design system.
 *
 * KEY COMPONENTS:
 *    - MarkdownRenderer: Main wrapper with styled prose container
 *    - Custom Components: Code block and heading rendering with overrides
 *    - Plugin Configuration: GFM, raw HTML, and sanitization plugins
 *
 * DEPENDENCIES:
 *    - External: react-markdown, rehype-raw, rehype-sanitize, remark-gfm,
 *                react, tailwindcss/typography, lucide-react
 *    - Internal: @/lib/utils (cn utility)
 *
 * USAGE:
 *    ```tsx
 *    <MarkdownRenderer content={node.content_markdown} />
 *
 *    <MarkdownRenderer
 *      content={node.content_markdown}
 *      selectedHeadingIds={selectedIds}
 *      onToggleHeadingChat={handleToggle}
 *      enableHeadingChat
 *    />
 *    ```
 * ============================================================================
 */
import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import remarkEmoji from "remark-emoji";
import rehypeExternalLinks from "rehype-external-links";
import React, { useState, useEffect, useRef, useId, useMemo } from "react";
import { createPortal } from "react-dom";
import "katex/dist/katex.min.css";
import { MessageCircle, Copy, Check, X, Download } from "lucide-react";
import { cn } from "@/lib/utils";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import mermaid from "mermaid";
import { preprocessMermaid, downloadMermaidAsPng } from "./mermaidUtils";

// Initialize mermaid for light mode
if (typeof window !== "undefined") {
	mermaid.initialize({
		startOnLoad: false,
		theme: "default",
		securityLevel: "loose",
		themeVariables: {
			background: "#fafafa",
			primaryColor: "#ffb74d",
			primaryTextColor: "#18181b",
			lineColor: "#ffb74d",
			textColor: "#18181b",
		}
	});
}

// Helper functions moved to external utility files to satisfy react-refresh component-only export requirements.

interface MermaidProps {
	chart: string;
	/** Skip debounce — used by PDF/ZIP export so diagrams settle immediately. */
	eager?: boolean;
}

export function Mermaid({ chart, eager = false }: MermaidProps) {
	const uniqueId = useId().replace(/:/g, "-");
	const elementId = useRef(`mermaid-${uniqueId}`);
	const containerRef = useRef<HTMLDivElement>(null);
	const [svg, setSvg] = useState<string>("");
	const [error, setError] = useState<string | null>(null);
	const [isZoomed, setIsZoomed] = useState(false);

	useEffect(() => {
		let isMounted = true;
		const renderChart = async () => {
			if (!containerRef.current) return;
			try {
				const preprocessedChart = preprocessMermaid(chart);

				// Configure Mermaid to always render in light mode
				mermaid.initialize({
					startOnLoad: false,
					theme: "default",
					securityLevel: "loose",
					themeVariables: {
						background: "#fafafa",
						primaryColor: "#ffb74d",
						primaryTextColor: "#18181b",
						lineColor: "#ffb74d",
						textColor: "#18181b",
					}
				});

				const { svg: renderedSvg } = await mermaid.render(
					elementId.current,
					preprocessedChart,
					containerRef.current
				);
				if (isMounted) {
					setSvg(renderedSvg);
					setError(null);
				}
			} catch (err) {
				console.error("Mermaid parsing error: ", err);
				if (containerRef.current) {
					containerRef.current.innerHTML = "";
				}
				if (isMounted) {
					setError("Failed to parse Mermaid diagram (invalid syntax while typing)");
				}
			}
		};

		// Debounce only for live typing; export path renders immediately
		if (eager) {
			void renderChart();
			return () => {
				isMounted = false;
			};
		}

		const timer = setTimeout(() => {
			void renderChart();
		}, 300);

		return () => {
			isMounted = false;
			clearTimeout(timer);
		};
	}, [chart, eager]);

	// Close on escape key
	useEffect(() => {
		if (!isZoomed) return;
		const handleKeyDown = (e: KeyboardEvent) => {
			if (e.key === "Escape") {
				e.stopPropagation();
				e.preventDefault();
				setIsZoomed(false);
			}
		};
		window.addEventListener("keydown", handleKeyDown, true);
		return () => window.removeEventListener("keydown", handleKeyDown, true);
	}, [isZoomed]);

	return (
		<div className="mermaid-wrapper my-6">
			<style>{`
				.mermaid-zoomed-container {
					width: 100%;
				}
				.mermaid-zoomed-container svg {
					width: 100% !important;
					max-width: 100% !important;
					height: auto !important;
					max-height: 75vh !important;
				}
				.mermaid-container text,
				.mermaid-container span,
				.mermaid-container div,
				.mermaid-container a,
				.mermaid-container p,
				.mermaid-zoomed-container text,
				.mermaid-zoomed-container span,
				.mermaid-zoomed-container div,
				.mermaid-zoomed-container a,
				.mermaid-zoomed-container p {
					fill: #18181b !important;
					color: #18181b !important;
				}
			`}</style>
			{/* Off-screen rendering target to allow proper text/layout measurement */}
			<div ref={containerRef} style={{ position: "absolute", top: "-9999px", left: "-9999px", visibility: "hidden" }} />
			
			{error && (
				<div className="text-red-500 text-xs p-3 border border-red-500/20 rounded bg-red-500/5 font-mono whitespace-pre-wrap mb-2">
					{error}
				</div>
			)}
			
			{!svg && !error && (
				<div className="animate-pulse bg-zinc-800/20 h-40 rounded-xl flex items-center justify-center text-xs text-muted-foreground">
					Rendering diagram...
				</div>
			)}
			
			{svg && (
				<div 
					className={cn(
						"mermaid-container flex justify-center overflow-x-auto p-4 rounded-xl border transition-all duration-200 cursor-zoom-in",
						"border-zinc-200 bg-zinc-50 hover:border-zinc-300 text-zinc-900",
						error ? 'opacity-40' : 'opacity-100'
					)}
					dangerouslySetInnerHTML={{ __html: svg }} 
					onClick={() => setIsZoomed(true)}
				/>
			)}

			{isZoomed && svg && createPortal(
				<div 
					className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4 md:p-8 cursor-zoom-out select-none animate-in fade-in duration-200"
					onClick={(e) => {
						e.stopPropagation();
						setIsZoomed(false);
					}}
				>
					<div 
						className="relative w-full max-w-4xl md:max-w-5xl max-h-[90vh] bg-zinc-50 border border-zinc-200 rounded-2xl p-6 md:p-8 shadow-2xl flex items-center justify-center overflow-auto cursor-zoom-out animate-in zoom-in-95 duration-200 text-zinc-900"
						onClick={() => setIsZoomed(false)}
					>
						<div className="absolute top-4 right-4 flex items-center gap-2 z-10">
							<button
								type="button"
								className="p-2 rounded-full bg-red-500/10 hover:bg-red-500/20 text-red-600 border border-red-500/30 transition-colors cursor-pointer focus:outline-none"
								onClick={(e) => {
									e.stopPropagation();
									downloadMermaidAsPng(svg);
								}}
								aria-label="Download diagram as PNG"
								title="Download PNG"
							>
								<Download className="h-5 w-5" />
							</button>
							<button
								type="button"
								className="p-2 rounded-full bg-zinc-200/80 hover:bg-zinc-300 text-zinc-600 hover:text-zinc-800 transition-colors cursor-pointer focus:outline-none"
								onClick={(e) => {
									e.stopPropagation();
									setIsZoomed(false);
								}}
								aria-label="Close diagram"
								title="Close"
							>
								<X className="h-5 w-5" />
							</button>
						</div>
						<div 
							className="mermaid-zoomed-container flex justify-center w-full cursor-pointer" 
							dangerouslySetInnerHTML={{ __html: svg }} 
							onClick={(e) => {
								e.stopPropagation();
								downloadMermaidAsPng(svg);
							}}
							title="Click diagram to download PNG"
						/>
					</div>
				</div>,
				document.body
			)}
		</div>
	);
}

interface Vector {
	name: string;
	x: number;
	y: number;
	color?: string;
}

interface VectorPlotProps {
	data: string;
}

export function VectorPlot({ data }: VectorPlotProps) {
	const [plotData, setPlotData] = useState<{
		vectors: Vector[];
		grid?: boolean;
		xAxisLabel?: string;
		yAxisLabel?: string;
	} | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [isZoomed, setIsZoomed] = useState(false);

	useEffect(() => {
		try {
			const parsed = JSON.parse(data);
			if (!parsed.vectors || !Array.isArray(parsed.vectors)) {
				throw new Error("Missing 'vectors' array");
			}
			setPlotData(parsed);
			setError(null);
		} catch (err) {
			const errMsg = err instanceof Error ? err.message : String(err);
			setError(`Invalid plot data: ${errMsg}`);
		}
	}, [data]);

	// Close on escape key
	useEffect(() => {
		if (!isZoomed) return;
		const handleKeyDown = (e: KeyboardEvent) => {
			if (e.key === "Escape") {
				e.stopPropagation();
				e.preventDefault();
				setIsZoomed(false);
			}
		};
		window.addEventListener("keydown", handleKeyDown, true);
		return () => window.removeEventListener("keydown", handleKeyDown, true);
	}, [isZoomed]);

	if (error) {
		return (
			<div className="text-red-500 text-sm p-4 border border-red-500/20 rounded bg-red-500/5 my-4 font-mono">
				{error}
			</div>
		);
	}

	if (!plotData) return null;

	const width = 380;
	const height = 300;
	const paddingX = 70;
	const paddingY = 30;
	
	const allX = plotData.vectors.flatMap(v => [0, v.x]);
	const allY = plotData.vectors.flatMap(v => [0, v.y]);
	const minX = Math.min(...allX, -2);
	const maxX = Math.max(...allX, 5);
	const minY = Math.min(...allY, -2);
	const maxY = Math.max(...allY, 5);
	
	const domainX = [minX - 1, maxX + 1];
	const domainY = [minY - 1, maxY + 1];
	
	const mapX = (val: number) => {
		return paddingX + ((val - domainX[0]) / (domainX[1] - domainX[0])) * (width - 2 * paddingX);
	};
	const mapY = (val: number) => {
		return height - (paddingY + ((val - domainY[0]) / (domainY[1] - domainY[0])) * (height - 2 * paddingY));
	};

	const originX = mapX(0);
	const originY = mapY(0);

	const gridStroke = "#e4e4e7";
	const axisStroke = "#a1a1aa";
	const axisTextFill = "#71717a";
	const originTextFill = "#a1a1aa";

	const gridLines: React.ReactNode[] = [];
	if (plotData.grid !== false) {
		for (let x = Math.ceil(domainX[0]); x <= Math.floor(domainX[1]); x++) {
			if (x !== 0) {
				gridLines.push(
					<line
						key={`v-${x}`}
						x1={mapX(x)}
						y1={paddingY}
						x2={mapX(x)}
						y2={height - paddingY}
						stroke={gridStroke}
						strokeWidth="0.5"
					/>
				);
			}
		}
		for (let y = Math.ceil(domainY[0]); y <= Math.floor(domainY[1]); y++) {
			if (y !== 0) {
				gridLines.push(
					<line
						key={`h-${y}`}
						x1={paddingX}
						y1={mapY(y)}
						x2={width - paddingX}
						y2={mapY(y)}
						stroke={gridStroke}
						strokeWidth="0.5"
					/>
				);
			}
		}
	}

	const renderSvg = (zoomed: boolean) => {
		const idSuffix = zoomed ? "-zoomed" : "";
		return (
			<svg 
				viewBox={`0 0 ${width} ${height}`} 
				className={cn(
					"w-full h-auto overflow-visible transition-all duration-200",
					zoomed ? "max-w-[500px]" : "max-w-[380px]"
				)}
			>
				<defs>
					{plotData.vectors.map((v, i) => (
						<marker
							key={`arrow-${i}${idSuffix}`}
							id={`arrow-${i}${idSuffix}`}
							viewBox="0 0 10 10"
							refX="6"
							refY="5"
							markerWidth="6"
							markerHeight="6"
							orient="auto-start-reverse"
						>
							<path d="M 0 1.5 L 10 5 L 0 8.5 z" fill={v.color || "#ffb74d"} />
						</marker>
					))}
				</defs>

				{gridLines}

				<line
					x1={paddingX}
					y1={originY}
					x2={width - paddingX}
					y2={originY}
					stroke={axisStroke}
					strokeWidth="1.5"
				/>
				<line
					x1={originX}
					y1={paddingY}
					x2={originX}
					y2={height - paddingY}
					stroke={axisStroke}
					strokeWidth="1.5"
				/>

				<text
					x={width - paddingX + 5}
					y={originY + 4}
					fill={axisTextFill}
					fontSize="10"
					textAnchor="start"
				>
					{plotData.xAxisLabel || "x"}
				</text>
				<text
					x={originX}
					y={paddingY - 8}
					fill={axisTextFill}
					fontSize="10"
					textAnchor="middle"
				>
					{plotData.yAxisLabel || "y"}
				</text>

				<text
					x={originX - 8}
					y={originY + 12}
					fill={originTextFill}
					fontSize="8"
					textAnchor="end"
				>
					0
				</text>

				{plotData.vectors.map((v, i) => {
					const vx = mapX(v.x);
					const vy = mapY(v.y);
					const color = v.color || "#ffb74d";
					
					// Split name by <br> or <br/> tags to support multi-line vector labels
					const nameLines = v.name.split(/<br\s*\/?>/i);
					const lines = [...nameLines];
					// Append coordinates to the last line
					lines[lines.length - 1] = `${lines[lines.length - 1]} (${v.x}, ${v.y})`;
					
					const textAnchor = v.x >= 0 ? "start" : "end";
					const textX = vx + (v.x >= 0 ? 8 : -8);
					const lineHeight = 14;
					const totalHeight = (lines.length - 1) * lineHeight;
					const startY = vy + (v.y >= 0 ? -4 : 8) - (v.y >= 0 ? totalHeight : 0);

					return (
						<g key={`vec-${i}`}>
							<line
								x1={originX}
								y1={originY}
								x2={vx}
								y2={vy}
								stroke={color}
								strokeWidth="2.5"
								markerEnd={`url(#arrow-${i}${idSuffix})`}
							/>
							<text
								x={textX}
								y={startY}
								fill={color}
								fontSize="11"
								fontWeight="bold"
								textAnchor={textAnchor}
							>
								{lines.map((line, idx) => (
									<tspan
										key={idx}
										x={textX}
										dy={idx === 0 ? 0 : lineHeight}
									>
										{line}
									</tspan>
								))}
							</text>
						</g>
					);
				})}
			</svg>
		);
	};

	return (
		<div 
			className="flex flex-col items-center justify-center my-6 p-4 rounded-xl border border-zinc-200 bg-zinc-50 select-none cursor-zoom-in hover:border-zinc-300 transition-all duration-200 text-zinc-900"
			onClick={() => setIsZoomed(true)}
		>
			{renderSvg(false)}

			{isZoomed && createPortal(
				<div 
					className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4 md:p-8 cursor-zoom-out select-none animate-in fade-in duration-200"
					onClick={(e) => {
						e.stopPropagation();
						setIsZoomed(false);
					}}
				>
					<div 
						className="relative w-full max-w-xl md:max-w-2xl bg-zinc-50 border border-zinc-200 rounded-2xl p-6 md:p-8 shadow-2xl flex flex-col items-center justify-center overflow-auto cursor-zoom-out animate-in zoom-in-95 duration-200 text-zinc-900"
						onClick={() => setIsZoomed(false)}
					>
						<button
							type="button"
							className="absolute top-4 right-4 p-2 rounded-full bg-zinc-200/80 hover:bg-zinc-300 text-zinc-600 hover:text-zinc-800 transition-colors cursor-pointer focus:outline-none z-10"
							onClick={() => setIsZoomed(false)}
							aria-label="Close graph"
						>
							<X className="h-5 w-5" />
						</button>
						<div className="w-full flex items-center justify-center">
							{renderSvg(true)}
						</div>
					</div>
				</div>,
				document.body
			)}
		</div>
	);
}

export interface CodeBlockProps {
	className?: string;
	children: React.ReactNode;
}

export function CodeBlock({ className, children }: CodeBlockProps) {
	const [copied, setCopied] = useState(false);
	const codeText = String(children).replace(/\n$/, "");
	const match = /language-(\w+)/.exec(className || "");
	const lang = match ? match[1] : "";

	const displayLang = "Code";

	const handleCopy = async () => {
		try {
			await navigator.clipboard.writeText(codeText);
			setCopied(true);
			setTimeout(() => setCopied(false), 2000);
		} catch (err) {
			console.error("Failed to copy text: ", err);
		}
	};

	return (
		<div className="not-prose my-4 rounded-xl border border-zinc-800 bg-[#18181b] overflow-hidden">
			<div className="flex items-center justify-between px-4 py-2 border-b border-zinc-800 bg-[#0f0f12] text-xs font-semibold text-muted-foreground select-none">
				<span>{displayLang}</span>
				<button
					type="button"
					onClick={handleCopy}
					className="p-1 rounded hover:bg-white/10 hover:text-foreground transition-all duration-200 cursor-pointer focus:outline-none"
					aria-label={copied ? "Copied" : "Copy code"}
				>
					{copied ? (
						<Check className="h-4 w-4 text-green-500 animate-in fade-in zoom-in duration-200" />
					) : (
						<Copy className="h-4 w-4 transition-transform active:scale-95" />
					)}
				</button>
			</div>
			<div className="text-[13.5px] leading-relaxed font-mono">
				<SyntaxHighlighter
					language={lang || "text"}
					style={vscDarkPlus}
					customStyle={{
						margin: 0,
						padding: "1rem",
						background: "transparent",
						fontSize: "inherit",
						lineHeight: "inherit",
						fontFamily: "inherit",
					}}
					codeTagProps={{
						className: "font-mono !text-[#f4f4f5]",
					}}
				>
					{codeText}
				</SyntaxHighlighter>
			</div>
		</div>
	);
}

interface MarkdownRendererProps {
	content: string;
	className?: string;
	selectedHeadingIds?: string[];
	onToggleHeadingChat?: (headingId: string) => void;
	enableHeadingChat?: boolean;
	/** Render Mermaid diagrams immediately (no debounce). For PDF/ZIP export. */
	eagerDiagrams?: boolean;
}

/**
 * Generate a stable heading ID from text content and level.
 * Uses lowercase kebab-case with level prefix: "h-2-my-heading"
 */
function generateHeadingId(level: number, text: string): string {
	const slug = text
		.toLowerCase()
		.replace(/[^\w\s-]/g, "")
		.replace(/\s+/g, "-")
		.replace(/-+/g, "-")
		.trim();
	return `h-${level}-${slug}`;
}

/**
 * Extract plain text from React children nodes.
 */
function extractText(children: React.ReactNode): string {
	if (typeof children === "string") return children;
	if (typeof children === "number") return String(children);
	if (Array.isArray(children)) return children.map(extractText).join("");
	if (React.isValidElement(children)) {
		const elementProps = children.props as { children?: React.ReactNode };
		if (elementProps.children) {
			return extractText(elementProps.children);
		}
	}
	return "";
}

/**
 * Creates a heading component override for the given level.
 */
function createHeadingComponent(
	level: number,
	selectedHeadingIds: string[],
	onToggleHeadingChat?: (headingId: string) => void,
	enableHeadingChat?: boolean,
) {
	const Tag = `h${level}` as keyof React.JSX.IntrinsicElements;
	return function HeadingOverride({
		children,
		...props
	}: React.HTMLAttributes<HTMLHeadingElement>) {
		const text = extractText(children);
		const headingId = generateHeadingId(level, text);
		const isSelected = selectedHeadingIds.includes(headingId);

		if (!enableHeadingChat) {
			return React.createElement(Tag, props, children);
		}

		return (
			<div className="relative" data-heading-id={headingId}>
				{React.createElement(
					Tag,
					{
						...props,
						className: cn(
							props.className,
							"group inline-block w-fit relative pr-7",
							isSelected &&
								"border-l-3 border-[#ffb74d] pl-3 bg-[#ffb74d]/5 rounded-r",
						),
					},
					<>
						{children}
						<button
							type="button"
							onClick={(e) => {
								e.stopPropagation();
								onToggleHeadingChat?.(headingId);
							}}
							className={cn(
								"absolute right-0 top-1/2 -translate-y-1/2 p-1 rounded-md inline-flex items-center justify-center cursor-pointer",
								"opacity-0 group-hover:opacity-100 transition-opacity duration-200",
								"hover:bg-[#ffb74d]/20",
								isSelected && "opacity-100",
							)}
							aria-label={`Chat about "${text}"`}
						>
							<MessageCircle
								className={cn(
									"h-4 w-4",
									isSelected ? "text-[#ffb74d]" : "text-muted-foreground",
								)}
							/>
						</button>
					</>,
				)}
			</div>
		);
	};
}

interface InlineMarkdownProps {
	content: string;
	className?: string;
}

export function InlineMarkdown({ content, className }: InlineMarkdownProps) {
	const inlineComponents = useMemo(() => ({
		p({ children }: React.HTMLAttributes<HTMLParagraphElement>) {
			return <>{children}</>;
		},
		code({
			className: codeClassName,
			children,
			...props
		}: React.HTMLAttributes<HTMLElement>) {
			const isInline = !codeClassName;
			if (isInline) {
				return (
					<code
						className={cn(
							"bg-primary/10 text-primary px-1 py-0.5 rounded font-mono text-[13px]",
							codeClassName,
						)}
						{...props}
					>
						{children}
					</code>
				);
			}
			return (
				<code className={codeClassName} {...props}>
					{children}
				</code>
			);
		},
	}), []);

	return (
		<span className={cn("prose-inline", className)}>
			<ReactMarkdown
				remarkPlugins={[remarkGfm, remarkMath, remarkEmoji]}
				rehypePlugins={[
					rehypeRaw,
					rehypeSanitize,
					rehypeKatex,
					[rehypeExternalLinks, { target: "_blank", rel: ["noopener", "noreferrer"] }]
				]}
				allowedElements={[
					"p",
					"em",
					"strong",
					"code",
					"a",
					"br",
					"del",
					"span",
				]}
				unwrapDisallowed
				components={inlineComponents}
			>
				{content}
			</ReactMarkdown>
		</span>
	);
}

const EMPTY_ARRAY: string[] = [];

export function MarkdownRenderer({
	content,
	className,
	selectedHeadingIds = EMPTY_ARRAY,
	onToggleHeadingChat,
	enableHeadingChat = false,
	eagerDiagrams = false,
}: MarkdownRendererProps) {
	const h2 = useMemo(() => createHeadingComponent(
		2,
		selectedHeadingIds,
		onToggleHeadingChat,
		enableHeadingChat,
	), [selectedHeadingIds, onToggleHeadingChat, enableHeadingChat]);

	const h3 = useMemo(() => createHeadingComponent(
		3,
		selectedHeadingIds,
		onToggleHeadingChat,
		enableHeadingChat,
	), [selectedHeadingIds, onToggleHeadingChat, enableHeadingChat]);

	const h4 = useMemo(() => createHeadingComponent(
		4,
		selectedHeadingIds,
		onToggleHeadingChat,
		enableHeadingChat,
	), [selectedHeadingIds, onToggleHeadingChat, enableHeadingChat]);

	const h5 = useMemo(() => createHeadingComponent(
		5,
		selectedHeadingIds,
		onToggleHeadingChat,
		enableHeadingChat,
	), [selectedHeadingIds, onToggleHeadingChat, enableHeadingChat]);

	const h6 = useMemo(() => createHeadingComponent(
		6,
		selectedHeadingIds,
		onToggleHeadingChat,
		enableHeadingChat,
	), [selectedHeadingIds, onToggleHeadingChat, enableHeadingChat]);

	const markdownComponents = useMemo(() => ({
		h2,
		h3,
		h4,
		h5,
		h6,
		table({ children, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
			return (
				<div 
					className="w-full overflow-x-auto border border-foreground/15 rounded-xl max-w-full shadow-sm"
					style={{ marginTop: "1.5rem", marginBottom: "1.5rem" }}
				>
					<table className="min-w-full divide-y divide-foreground/15 text-[14px] table-auto border-collapse m-0!" {...props}>
						{children}
					</table>
				</div>
			);
		},
		thead({ children, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
			return (
				<thead className="bg-muted/40" {...props}>
					{children}
				</thead>
			);
		},
		tbody({ children, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
			return (
				<tbody className="divide-y divide-foreground/10" {...props}>
					{children}
				</tbody>
			);
		},
		tr({ children, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
			return (
				<tr className="hover:bg-muted/10 transition-colors" {...props}>
					{children}
				</tr>
			);
		},
		th({ children, ...props }: React.ThHTMLAttributes<HTMLTableHeaderCellElement>) {
			return (
				<th className="px-4 py-3 text-left font-bold text-primary border-b border-r border-foreground/20 last:border-r-0 uppercase tracking-wider text-[12px] whitespace-nowrap" {...props}>
					{children}
				</th>
			);
		},
		td({ children, ...props }: React.TdHTMLAttributes<HTMLTableDataCellElement>) {
			return (
				<td className="px-4 py-3 text-foreground/90 border-b border-r border-foreground/10 last:border-r-0 align-middle leading-relaxed" {...props}>
					{children}
				</td>
			);
		},
		pre({ children }: React.HTMLAttributes<HTMLPreElement>) {
			return <>{children}</>;
		},
		code({
			className: codeClassName,
			children,
			...props
		}: React.HTMLAttributes<HTMLElement>) {
			const isInline = !codeClassName;
			if (isInline) {
				return (
					<code
						className={cn(
							"bg-primary/10 text-primary px-1.5 py-0.5 rounded font-mono text-[14px]",
							codeClassName,
						)}
						{...props}
					>
						{children}
					</code>
				);
			}
			const match = /language-([\w-]+)/.exec(codeClassName || "");
			const lang = match ? match[1] : "";
			if (lang === "mermaid") {
				return (
					<Mermaid
						chart={String(children).replace(/\n$/, "")}
						eager={eagerDiagrams}
					/>
				);
			}
			if (lang === "vector-plot") {
				return <VectorPlot data={String(children).replace(/\n$/, "")} />;
			}
			return <CodeBlock className={codeClassName}>{children}</CodeBlock>;
		},
	}), [h2, h3, h4, h5, h6, eagerDiagrams]);

	return (
		<div
			className={cn(
				"prose max-w-none text-base leading-relaxed",
				"dark:prose-invert",
				// Body Text
				"prose-p:text-foreground",
				// Headings: Cyber Yellow / Primary brand color
				"prose-headings:text-primary font-bold",
				// Strong / Bold: Cyber Yellow / Primary brand color
				"prose-strong:text-primary font-bold",
				// Links: Cyber Yellow (Primary)
				"prose-a:text-primary hover:prose-a:text-primary/80",
				// Code
				"prose-code:text-primary prose-code:bg-primary/10 prose-code:px-1 prose-code:rounded prose-code:before:content-none prose-code:after:content-none [&_pre_code]:bg-transparent [&_pre_code]:p-0",
				// Lists
				"prose-ul:text-muted-foreground prose-ol:text-muted-foreground",
				// Blockquotes: left border matches primary brand, text is slightly muted
				"prose-blockquote:border-l-primary prose-blockquote:text-muted-foreground/90 prose-blockquote:italic",
				// Pre / Block Code
				"prose-pre:bg-transparent prose-pre:p-0 prose-pre:border-none",
				className,
			)}
		>
			<ReactMarkdown
				remarkPlugins={[remarkGfm, remarkMath, remarkEmoji]}
				rehypePlugins={[
					rehypeRaw,
					rehypeSanitize,
					rehypeKatex,
					[rehypeExternalLinks, { target: "_blank", rel: ["noopener", "noreferrer"] }]
				]}
				components={markdownComponents}
			>
				{content}
			</ReactMarkdown>
		</div>
	);
}
