/**
 * ============================================================================
 * FILE: pdfExportUtils.ts
 * LOCATION: client/src/features/learning/pdfExportUtils.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Markdown-first PDF/ZIP export for course concept modules. Strips curiosity
 *    sections, inlines Mermaid SVGs, renders a light-theme print DOM, then
 *    captures via html2canvas-pro + jsPDF multipage (or packages ZIP).
 *
 * ROLE IN PROJECT:
 *    Utility within learning feature. ConceptCard downloads single PDFs from
 *    content_markdown; CourseCard downloads full-course ZIP archives.
 *
 * KEY COMPONENTS:
 *    - sanitizeFilename: Safe PDF/ZIP filenames from titles
 *    - stripCuriosityFromMarkdown: Drop curiosity section via parser
 *    - renderMermaidFencesInMarkdown: ```mermaid → inline figure+svg
 *    - exportConceptAsPdf / exportConceptAsPdfBlob: Single-module PDF
 *    - exportCourseAsZip: All modules as numbered PDFs in a ZIP
 *
 * DEPENDENCIES:
 *    - External: html2canvas-pro, jspdf, jszip, mermaid, react, react-dom/client,
 *                react-markdown, remark-gfm, remark-math, rehype-katex, rehype-raw
 *    - Internal: @/lib/learningApi, ./curiosityParser, ./mermaidUtils
 *
 * USAGE:
 *    import { exportConceptAsPdf, exportCourseAsZip } from "./pdfExportUtils";
 *    await exportConceptAsPdf(title, markdown, sequenceIndex, complexity);
 *    await exportCourseAsZip(sessionId, courseTitle);
 * ============================================================================
 */
import html2canvas from "html2canvas-pro";
import { jsPDF } from "jspdf";
import JSZip from "jszip";
import mermaid from "mermaid";
import React from "react";
import { createRoot } from "react-dom/client";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import "katex/dist/katex.min.css";
import { getLearningSession } from "@/lib/learningApi";
import { parseCuriosityQuestions } from "./curiosityParser";
import { preprocessMermaid } from "./mermaidUtils";
import { renderVectorPlotSvg } from "./vectorPlotUtils";

function ensureMermaidLightTheme(): void {
	if (typeof window === "undefined") return;
	// Re-init each export batch — iframe / multi-call safety
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
		},
	});
}

/**
 * Parent-document measure root with real layout metrics.
 * Mermaid getBBox fails inside height:0 / visibility:hidden iframes.
 */
function createMermaidMeasureHost(): { host: HTMLElement; cleanup: () => void } {
	const host = document.createElement("div");
	host.setAttribute("data-pdf-mermaid-measure", "true");
	host.style.cssText = [
		"position:fixed",
		"left:0",
		"top:0",
		"width:800px",
		"height:600px",
		"opacity:0",
		"pointer-events:none",
		"z-index:-1",
		"overflow:hidden",
	].join(";");
	document.body.appendChild(host);
	return {
		host,
		cleanup: () => {
			if (host.parentNode) host.parentNode.removeChild(host);
			// Mermaid leaves temp nodes (#d{id}) on body
			document
				.querySelectorAll("[id^='dpdfmmd'], [id^='pdfmmd']")
				.forEach((el) => el.remove());
		},
	};
}

/**
 * Sanitizes a concept title for use as a valid PDF or ZIP filename.
 */
export function sanitizeFilename(title: string): string {
	if (!title || typeof title !== "string") {
		return "concept-explanation.pdf";
	}

	const cleaned = title
		.trim()
		.replace(/[/\\?%*:|"<>]/g, "-")
		.replace(/\s+/g, " ");

	if (!cleaned) {
		return "concept-explanation.pdf";
	}

	return cleaned.endsWith(".pdf") ? cleaned : `${cleaned}.pdf`;
}

/**
 * Removes curiosity / spark sections from markdown source before export.
 */
export function stripCuriosityFromMarkdown(markdown: string): string {
	if (!markdown) return "";
	return parseCuriosityQuestions(markdown).mainContent;
}

/**
 * Replaces ```mermaid and ```vector-plot fences with inline figures/SVGs.
 * Mermaid measures on a parent-document host (real layout). Never loading placeholders.
 */
export async function renderMermaidFencesInMarkdown(
	markdown: string,
	options?: { measureHost?: HTMLElement },
): Promise<string> {
	if (!markdown) return "";

	// mermaid | vector-plot | vector_plot
	const fenceRegex = /```\s*(mermaid|vector-plot|vector_plot)[^\n]*\r?\n([\s\S]*?)```/gi;
	const matches = Array.from(markdown.matchAll(fenceRegex));
	if (matches.length === 0) return markdown;

	ensureMermaidLightTheme();

	// Prefer caller host; else create parent measure root with real box metrics
	const owned = options?.measureHost
		? null
		: createMermaidMeasureHost();
	const measureHost = options?.measureHost ?? owned!.host;

	let result = "";
	let lastIndex = 0;
	let diagramIndex = 0;

	try {
		for (const match of matches) {
			const matchIndex = match.index ?? 0;
			result += markdown.slice(lastIndex, matchIndex);
			const lang = (match[1] || "").toLowerCase().replace("_", "-");
			const body = (match[2] ?? "").trim();

			if (lang === "vector-plot") {
				const svg = renderVectorPlotSvg(body);
				if (svg) {
					result += `<figure class="pdf-diagram pdf-vector-diagram">${svg}</figure>`;
				} else {
					result +=
						'<pre class="pdf-diagram-error">Vector plot failed to render.</pre>';
				}
			} else {
				// mermaid — id must be valid CSS/DOM id (no dots from random alone is fine)
				const uniqueId = `pdfmmd${Date.now()}${diagramIndex++}${Math.random().toString(36).slice(2, 8)}`;
				try {
					const preprocessed = preprocessMermaid(body);
					// Always pass measure host so layout uses a real 800×600 box
					const { svg } = await mermaid.render(
						uniqueId,
						preprocessed,
						measureHost,
					);
					// Clear measure host between diagrams (mermaid injects temp DOM)
					measureHost.innerHTML = "";
					result += `<figure class="pdf-diagram">${svg}</figure>`;
				} catch (err) {
					console.warn("[pdfExport] Mermaid render failed:", err);
					measureHost.innerHTML = "";
					result +=
						'<pre class="pdf-diagram-error">Diagram failed to render.</pre>';
				}
			}

			lastIndex = matchIndex + match[0].length;
		}

		result += markdown.slice(lastIndex);
		return result;
	} finally {
		owned?.cleanup();
	}
}

/**
 * Pre-processes SVG diagrams inside an element before canvas/PDF capture.
 */
function prepareSvgsForPdf(container: HTMLElement): void {
	const svgs = Array.from(container.querySelectorAll("svg"));

	svgs.forEach((svg) => {
		if (!svg.getAttribute("xmlns")) {
			svg.setAttribute("xmlns", "http://www.w3.org/2000/svg");
		}

		const viewBox = svg.getAttribute("viewBox");
		let width = parseFloat(svg.getAttribute("width") || "0");
		let height = parseFloat(svg.getAttribute("height") || "0");

		if ((!width || !height) && viewBox) {
			const parts = viewBox.trim().split(/[\s,]+/).map(Number);
			if (parts.length === 4 && parts[2] > 0 && parts[3] > 0) {
				width = parts[2];
				height = parts[3];
			}
		}

		if (!width || !height) {
			const rect = svg.getBoundingClientRect();
			width = rect.width || 800;
			height = rect.height || 600;
		}

		svg.setAttribute("width", String(width));
		svg.setAttribute("height", String(height));

		svg.style.position = "static";
		svg.style.display = "block";
		svg.style.margin = "0"; // left-aligned
		svg.style.maxWidth = "100%";
		svg.style.height = "auto";

		const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
		style.textContent = `
			text, tspan, span, div, p {
				fill: #18181b !important;
				color: #18181b !important;
				font-family: Inter, sans-serif !important;
			}
		`;
		svg.insertBefore(style, svg.firstChild);
	});
}

const EXPORT_HOST_STYLES = `
	.pdf-export-wrapper {
		background-color: #ffffff !important;
		color: #18181b !important;
	}
	.pdf-export-wrapper * {
		box-sizing: border-box !important;
	}
	.pdf-export-wrapper p, .pdf-export-wrapper li, .pdf-export-wrapper span,
	.pdf-export-wrapper td, .pdf-export-wrapper th {
		color: #18181b !important;
		line-height: 1.6 !important;
	}
	.pdf-export-wrapper h1, .pdf-export-wrapper h2, .pdf-export-wrapper h3,
	.pdf-export-wrapper h4, .pdf-export-wrapper h5, .pdf-export-wrapper h6 {
		color: #09090b !important;
		font-weight: 700 !important;
	}
	.pdf-export-wrapper pre,
	.pdf-export-wrapper code {
		background-color: #f4f4f5 !important;
		background-image: none !important;
		border: 1px solid #e4e4e7 !important;
		border-radius: 8px !important;
		color: #09090b !important;
		font-family: "JetBrains Mono", "Fira Code", ui-monospace, monospace !important;
		text-shadow: none !important;
	}
	.pdf-export-wrapper pre {
		padding: 12px !important;
		margin: 12px 0 !important;
		overflow-x: auto !important;
	}
	.pdf-export-wrapper pre code {
		background-color: transparent !important;
		border: none !important;
		padding: 0 !important;
	}
	.pdf-export-wrapper :not(pre) > code {
		padding: 2px 6px !important;
	}
	.pdf-export-wrapper .katex,
	.pdf-export-wrapper .katex-html {
		color: #09090b !important;
		font-size: 1.05em !important;
	}
	.pdf-export-wrapper .katex-mathml {
		display: none !important;
	}
	.pdf-export-wrapper table {
		border-collapse: collapse !important;
		width: 100% !important;
		margin: 16px 0 !important;
	}
	.pdf-export-wrapper th, .pdf-export-wrapper td {
		border: 1px solid #e4e4e7 !important;
		padding: 8px 12px !important;
		color: #18181b !important;
	}
	.pdf-export-wrapper th {
		background-color: #f4f4f5 !important;
		font-weight: 700 !important;
	}
	.pdf-export-wrapper strong {
		color: #09090b !important;
		font-weight: 700 !important;
	}
	.pdf-export-wrapper .pdf-diagram {
		display: block !important;
		margin: 16px 0 !important;
		text-align: left !important;
		page-break-inside: avoid !important;
		break-inside: avoid !important;
	}
	.pdf-export-wrapper .pdf-diagram svg,
	.pdf-export-wrapper .pdf-vector-plot {
		display: block !important;
		margin: 0 !important;
		max-width: 100% !important;
		height: auto !important;
	}
	.pdf-export-wrapper .pdf-diagram-error {
		color: #b91c1c !important;
		background-color: #fef2f2 !important;
		border-color: #fecaca !important;
	}
	.pdf-export-wrapper .pdf-print-body {
		color: #18181b !important;
	}
`;

type ExportSandbox = {
	iframe: HTMLIFrameElement;
	doc: Document;
	host: HTMLElement;
	cleanup: () => void;
};

/**
 * Isolated iframe sandbox — html2canvas never touches main document layout.
 * Fixes host-page text bold/unbold flicker from windowWidth reflow + body host.
 */
async function createExportSandbox(): Promise<ExportSandbox> {
	const iframe = document.createElement("iframe");
	iframe.setAttribute("aria-hidden", "true");
	iframe.setAttribute("tabindex", "-1");
	iframe.setAttribute("title", "pdf-export-sandbox");
	// Invisible but real size — height:0/visibility:hidden breaks layout metrics.
	// opacity:0 keeps main page free of flicker without collapsing iframe layout.
	iframe.style.cssText = [
		"position:fixed",
		"left:0",
		"top:0",
		"width:800px",
		"height:10000px",
		"border:0",
		"margin:0",
		"padding:0",
		"opacity:0",
		"pointer-events:none",
		"z-index:-1",
		"overflow:hidden",
	].join(";");
	document.body.appendChild(iframe);

	await new Promise<void>((resolve) => {
		const done = () => resolve();
		if (iframe.contentDocument?.readyState === "complete") {
			done();
			return;
		}
		iframe.addEventListener("load", done, { once: true });
		// jsdom / already-loaded
		setTimeout(done, 0);
	});

	const doc = iframe.contentDocument;
	if (!doc) {
		iframe.remove();
		throw new Error("PDF export sandbox failed to initialize.");
	}

	const baseHref =
		typeof location !== "undefined" && location.href ? location.href : "";
	doc.open();
	doc.write(
		`<!DOCTYPE html><html><head><base href="${baseHref.replace(/"/g, "")}"/></head><body style="margin:0;background:#ffffff;"></body></html>`,
	);
	doc.close();

	// Print styles only inside iframe — never inject into parent document
	const styleTag = doc.createElement("style");
	styleTag.textContent = EXPORT_HOST_STYLES;
	doc.head.appendChild(styleTag);

	// KaTeX CSS lives on parent (vite import). Copy matching stylesheets into iframe.
	document
		.querySelectorAll('link[rel="stylesheet"], style')
		.forEach((node) => {
			if (node instanceof HTMLLinkElement) {
				const href = node.href || "";
				if (!/katex/i.test(href) && !/katex/i.test(node.getAttribute("href") || "")) {
					return;
				}
				const link = doc.createElement("link");
				link.rel = "stylesheet";
				link.href = href;
				doc.head.appendChild(link);
			} else if (node instanceof HTMLStyleElement) {
				const text = node.textContent || "";
				if (!/katex|\.katex/i.test(text)) return;
				const clone = doc.createElement("style");
				clone.textContent = text;
				doc.head.appendChild(clone);
			}
		});

	const host = doc.createElement("div");
	host.className = "pdf-export-wrapper";
	host.style.cssText = [
		"width:800px",
		"padding:32px",
		"box-sizing:border-box",
		"background-color:#ffffff",
		"color:#18181b",
		"font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif",
		"overflow:visible",
	].join(";");
	doc.body.appendChild(host);

	return {
		iframe,
		doc,
		host,
		cleanup: () => {
			if (iframe.parentNode) iframe.parentNode.removeChild(iframe);
		},
	};
}

type PrintCodeProps = {
	className?: string;
	children?: React.ReactNode;
};

/**
 * Light-theme markdown body for PDF — no SyntaxHighlighter / vscDarkPlus.
 */
function PrintMarkdownBody({ content }: { content: string }) {
	return React.createElement(
		"div",
		{ className: "pdf-print-body" },
		React.createElement(
			ReactMarkdown,
			{
				remarkPlugins: [remarkGfm, remarkMath],
				rehypePlugins: [rehypeKatex, rehypeRaw],
				components: {
					code({ className, children, ...props }: PrintCodeProps) {
						const isBlock =
							typeof className === "string" &&
							className.includes("language-");
						if (isBlock) {
							return React.createElement(
								"code",
								{ className, ...props },
								children,
							);
						}
						return React.createElement(
							"code",
							{
								className,
								style: {
									backgroundColor: "#f4f4f5",
									color: "#09090b",
									borderRadius: "4px",
									padding: "2px 6px",
								},
								...props,
							},
							children,
						);
					},
					pre({ children }: { children?: React.ReactNode }) {
						return React.createElement(
							"pre",
							{
								style: {
									backgroundColor: "#f4f4f5",
									color: "#09090b",
									border: "1px solid #e4e4e7",
									borderRadius: "8px",
									padding: "12px",
									overflowX: "auto",
								},
							},
							children,
						);
					},
				},
			},
			content,
		),
	);
}

function buildPdfHeader(
	title: string,
	sequenceIndex?: number,
	complexity?: string,
	ownerDoc: Document = document,
): HTMLElement {
	const headerDiv = ownerDoc.createElement("div");
	headerDiv.style.borderBottom = "2px solid #e4e4e7";
	headerDiv.style.paddingBottom = "16px";
	headerDiv.style.marginBottom = "24px";
	headerDiv.style.display = "flex";
	headerDiv.style.justifyContent = "space-between";
	headerDiv.style.alignItems = "center";

	const leftHeader = ownerDoc.createElement("div");
	const titleEl = ownerDoc.createElement("h1");
	titleEl.style.fontSize = "22px";
	titleEl.style.fontWeight = "700";
	titleEl.style.color = "#18181b";
	titleEl.style.margin = "0 0 6px 0";
	titleEl.textContent = title;
	leftHeader.appendChild(titleEl);

	if (complexity) {
		const badge = ownerDoc.createElement("span");
		badge.style.display = "inline-block";
		badge.style.fontSize = "11px";
		badge.style.fontWeight = "600";
		badge.style.padding = "2px 8px";
		badge.style.borderRadius = "12px";
		badge.style.backgroundColor = "#fef3c7";
		badge.style.color = "#b45309";
		badge.textContent = complexity;
		leftHeader.appendChild(badge);
	}

	headerDiv.appendChild(leftHeader);

	if (typeof sequenceIndex === "number") {
		const indexEl = ownerDoc.createElement("span");
		indexEl.style.fontSize = "14px";
		indexEl.style.fontWeight = "600";
		indexEl.style.color = "#71717a";
		indexEl.textContent = `#${sequenceIndex + 1}`;
		headerDiv.appendChild(indexEl);
	}

	return headerDiv;
}

/** Mermaid sometimes leaves temp nodes on parent body — strip without touching app UI. */
function scrubMermaidTempNodes(root: ParentNode = document.body): void {
	root
		.querySelectorAll(
			'[id^="dpdfmmd"], [id^="pdfmmd"], [id^="dpdf-mermaid"], [id^="pdf-mermaid"]',
		)
		.forEach((el) => {
			el.remove();
		});
}

function flushFrames(count = 2): Promise<void> {
	return new Promise((resolve) => {
		const step = (left: number) => {
			if (left <= 0) {
				resolve();
				return;
			}
			requestAnimationFrame(() => step(left - 1));
		};
		step(count);
	});
}

/**
 * Build multipage jsPDF from markdown (strip → mermaid → print DOM → canvas).
 * All DOM work runs inside a hidden iframe so the visible app never reflows.
 */
async function buildPdfFromMarkdown(
	title: string,
	markdown: string,
	sequenceIndex?: number,
	complexity?: string,
): Promise<jsPDF> {
	const stripped = stripCuriosityFromMarkdown(markdown);
	if (!stripped.trim()) {
		throw new Error("No content to export.");
	}

	const sandbox = await createExportSandbox();
	const { iframe, doc, host, cleanup } = sandbox;

	host.appendChild(buildPdfHeader(title, sequenceIndex, complexity, doc));

	const bodyMount = doc.createElement("div");
	host.appendChild(bodyMount);

	const root = createRoot(bodyMount);

	try {
		// Mermaid measures on parent-document host (real box). Not iframe.
		const withDiagrams = await renderMermaidFencesInMarkdown(stripped);
		scrubMermaidTempNodes(document.body);

		root.render(
			React.createElement(PrintMarkdownBody, { content: withDiagrams }),
		);
		await flushFrames(2);

		prepareSvgsForPdf(host);

		const wrapperHeight = Math.max(
			host.scrollHeight,
			host.offsetHeight,
			doc.body.scrollHeight,
			400,
		);

		// Size iframe to content for correct layout metrics; stay visibility:hidden
		iframe.style.height = `${wrapperHeight + 32}px`;
		await flushFrames(1);

		// Capture inside iframe only — never reflow parent document
		const canvas = await html2canvas(host, {
			scale: 1.5,
			useCORS: true,
			allowTaint: false,
			logging: false,
			backgroundColor: "#ffffff",
			width: 800,
			height: wrapperHeight,
			windowWidth: 800,
			windowHeight: wrapperHeight,
			scrollX: 0,
			scrollY: 0,
			onclone: (_clonedDoc, cloned) => {
				cloned.style.opacity = "1";
				cloned.style.visibility = "visible";
				cloned.querySelectorAll("pre, code").forEach((node) => {
					if (node instanceof HTMLElement) {
						node.style.setProperty("color", "#09090b", "important");
						node.style.setProperty(
							"background-color",
							node.tagName === "PRE" ? "#f4f4f5" : "transparent",
							"important",
						);
						node.style.setProperty("text-shadow", "none", "important");
					}
				});
			},
		});

		const imgData = canvas.toDataURL("image/jpeg", 0.92);
		const pdf = new jsPDF({
			orientation: "portrait",
			unit: "mm",
			format: "a4",
		});

		const pdfWidth = pdf.internal.pageSize.getWidth();
		const pdfHeight = pdf.internal.pageSize.getHeight();
		const margin = 10;
		const printWidth = pdfWidth - margin * 2;
		const printHeight = (canvas.height * printWidth) / canvas.width;
		const usablePageHeight = pdfHeight - margin * 2;

		let heightLeft = printHeight;
		let position = margin;

		pdf.addImage(imgData, "JPEG", margin, position, printWidth, printHeight);
		heightLeft -= usablePageHeight;

		while (heightLeft > 0) {
			position = margin - (printHeight - heightLeft);
			pdf.addPage();
			pdf.addImage(imgData, "JPEG", margin, position, printWidth, printHeight);
			heightLeft -= usablePageHeight;
		}

		return pdf;
	} finally {
		try {
			root.unmount();
		} catch {
			// ignore unmount races in tests
		}
		scrubMermaidTempNodes(document.body);
		cleanup();
	}
}

/**
 * Exports a single course concept module as a downloadable PDF from markdown.
 */
export async function exportConceptAsPdf(
	title: string,
	markdown: string,
	sequenceIndex?: number,
	complexity?: string,
): Promise<void> {
	const filename = sanitizeFilename(title);
	const pdf = await buildPdfFromMarkdown(
		title,
		markdown,
		sequenceIndex,
		complexity,
	);
	pdf.save(filename);
}

/**
 * Generates a PDF Blob for a concept module from markdown.
 */
export async function exportConceptAsPdfBlob(
	title: string,
	markdown: string,
	sequenceIndex?: number,
	complexity?: string,
): Promise<Blob> {
	const pdf = await buildPdfFromMarkdown(
		title,
		markdown,
		sequenceIndex,
		complexity,
	);
	return pdf.output("blob");
}

/**
 * Yield main thread so UI stays responsive during multi-module ZIP export.
 */
function yieldToMain(): Promise<void> {
	return new Promise((resolve) => {
		if (typeof requestIdleCallback === "function") {
			requestIdleCallback(() => resolve(), { timeout: 50 });
		} else {
			setTimeout(resolve, 0);
		}
	});
}

/**
 * Exports all concept modules of a completed course as a ZIP named after course.
 */
export async function exportCourseAsZip(
	sessionId: string,
	courseTitle: string,
): Promise<void> {
	const sessionData = await getLearningSession(sessionId);
	const nodes = sessionData.nodes ?? [];

	if (nodes.length === 0) {
		throw new Error("No course concept modules found to export.");
	}

	const sortedNodes = [...nodes].sort(
		(a, b) => (a.sequence_index ?? 0) - (b.sequence_index ?? 0),
	);

	const zip = new JSZip();

	for (let i = 0; i < sortedNodes.length; i++) {
		const node = sortedNodes[i];
		const markdown = node.content_markdown;
		if (!markdown?.trim()) continue;

		await yieldToMain();

		const pdfBlob = await exportConceptAsPdfBlob(
			node.title,
			markdown,
			node.sequence_index ?? i,
			node.complexity,
		);

		const seqPrefix = String((node.sequence_index ?? i) + 1).padStart(2, "0");
		const cleanTitle = sanitizeFilename(node.title).replace(/\.pdf$/i, "");
		const pdfFilename = `${seqPrefix}_${cleanTitle}.pdf`;
		zip.file(pdfFilename, pdfBlob);
	}

	const zipBlob = await zip.generateAsync({ type: "blob" });
	const zipFilename = `${sanitizeFilename(courseTitle).replace(/\.pdf$/i, "")}.zip`;

	if (typeof URL !== "undefined" && typeof URL.createObjectURL === "function") {
		const url = URL.createObjectURL(zipBlob);
		const a = document.createElement("a");
		a.href = url;
		a.download = zipFilename;
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
		if (typeof URL.revokeObjectURL === "function") {
			setTimeout(() => URL.revokeObjectURL(url), 1000);
		}
	}
}
