/**
 * ============================================================================
 * FILE: pdfExportUtils.ts
 * LOCATION: client/src/features/learning/pdfExportUtils.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Generates and triggers download of styled PDFs and ZIP course archives
 *    for course concept modules.
 *
 * ROLE IN PROJECT:
 *    Utility within learning feature to render Markdown text, KaTeX formulas,
 *    and Mermaid diagrams into downloadable PDFs and full-course ZIP packages.
 *
 * KEY COMPONENTS:
 *    - sanitizeFilename: Cleans titles into safe PDF/ZIP filenames
 *    - exportConceptAsPdf: Exports a single concept card as PDF
 *    - exportCourseAsZip: Exports all concept modules of a completed course as a ZIP
 *
 * DEPENDENCIES:
 *    - External: html2canvas-pro, jspdf, jszip, react-dom/client, react
 *    - Internal: @/lib/learningApi, ./MarkdownRenderer
 *
 * USAGE:
 *    import { exportConceptAsPdf, exportCourseAsZip } from "./pdfExportUtils";
 *    await exportConceptAsPdf(title, element, sequenceIndex, complexity);
 *    await exportCourseAsZip(sessionId, courseTitle);
 * ============================================================================
 */
import html2canvas from "html2canvas-pro";
import { jsPDF } from "jspdf";
import JSZip from "jszip";
import React from "react";
import { createRoot } from "react-dom/client";
import { getLearningSession } from "@/lib/learningApi";
import { MarkdownRenderer } from "./MarkdownRenderer";

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
 * Pre-processes SVG diagrams inside an element before canvas/PDF capture
 * to preserve crisp text colors, correct font styles, and explicit sizing.
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

		// Ensure SVG displays in standard block flow without absolute positioning overlap
		svg.style.position = "static";
		svg.style.display = "block";
		svg.style.margin = "0 auto";
		svg.style.maxWidth = "100%";

		// Inject light theme styling override for Mermaid text in export
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

/**
 * Completely strips the CuriositySpark ('Curious to explore more?') section from export DOM
 * without deleting parent content containers.
 *
 * Never uses broad selectors like `.border` / `.rounded-lg` — those match the concept
 * card wrapper and wipe the entire body (header-only blank PDFs).
 */
export function stripCuriositySpark(container: HTMLElement): void {
	container.querySelectorAll(".curiosity-spark").forEach((el) => el.remove());

	// Prefer className string checks — Tailwind `/` classes are unreliable in querySelector
	const isCuriosityBox = (node: HTMLElement): boolean => {
		if (node === container) return false;
		if (node.classList.contains("curiosity-spark")) return true;
		const cls = typeof node.className === "string" ? node.className : "";
		return cls.includes("border-primary/20") || cls.includes("bg-primary/5");
	};

	// Headings/labels only — never match bulk `div` wrappers whose textContent
	// inherits the curiosity phrase (that path deleted whole card bodies).
	const markers = Array.from(
		container.querySelectorAll("h1, h2, h3, h4, h5, h6, p, span, strong"),
	);

	markers.forEach((el) => {
		if (!container.contains(el) || !el.textContent) return;
		const text = el.textContent.trim().toLowerCase();
		if (
			!text.includes("curious to explore more") &&
			!text.includes("curiosity spark")
		) {
			return;
		}

		let node: HTMLElement | null = el as HTMLElement;
		while (node && node !== container) {
			if (isCuriosityBox(node)) {
				node.remove();
				return;
			}
			node = node.parentElement;
		}

		// Markdown-embedded curiosity block: drop heading + following siblings
		// until next heading. Do not climb to / remove parent containers.
		if (!/^H[1-6]$/i.test(el.tagName)) return;

		let next: Element | null = el.nextElementSibling;
		while (next && !/^H[1-6]$/i.test(next.tagName) && container.contains(next)) {
			const siblingToRemove = next;
			next = next.nextElementSibling;
			siblingToRemove.remove();
		}
		el.remove();
	});
}


/**
 * Extracts Mermaid/SVG diagrams from inline text, places them in a dedicated 'Diagrams'
 * section at the bottom of the content container, and applies page-break avoidance styling.
 */
export function moveDiagramsToDedicatedSection(container: HTMLElement): void {
	// Target ONLY Mermaid diagram containers and vector plots
	const diagramWrappers = Array.from(
		container.querySelectorAll<HTMLElement>(".mermaid-wrapper, .mermaid, div[id^='mermaid-']"),
	);

	const mermaidSvgs = Array.from(container.querySelectorAll("svg")).filter((svg) => {
		const id = svg.getAttribute("id") || "";
		const parentId = svg.parentElement?.getAttribute("id") || "";
		return id.startsWith("mermaid") || parentId.startsWith("mermaid");
	});

	const diagramContainers: HTMLElement[] = [];
	const visited = new Set<Element>();

	diagramWrappers.forEach((wrapper) => {
		if (!visited.has(wrapper) && container.contains(wrapper)) {
			visited.add(wrapper);
			diagramContainers.push(wrapper);
		}
	});

	mermaidSvgs.forEach((svg) => {
		const wrapper = (svg.closest(".mermaid-wrapper, .mermaid") as HTMLElement) || svg;
		if (!visited.has(wrapper) && container.contains(wrapper)) {
			visited.add(wrapper);
			diagramContainers.push(wrapper);
		}
	});

	if (diagramContainers.length === 0) return;

	diagramContainers.forEach((diag) => {
		diag.remove();

		// Clean positioning and display on diagram container to prevent overlap
		diag.style.position = "relative";
		diag.style.top = "0";
		diag.style.left = "0";
		diag.style.display = "block";
		diag.style.clear = "both";
		diag.style.pageBreakInside = "avoid";
		diag.style.breakInside = "avoid";
		diag.style.maxWidth = "100%";
		diag.style.margin = "16px auto";
		diag.style.overflow = "visible";

		// Remove off-screen measurement divs inside wrapper
		diag.querySelectorAll("div").forEach((childDiv) => {
			if (childDiv.style.position === "absolute" || childDiv.style.top === "-9999px") {
				childDiv.remove();
			}
		});

		// Ensure inner SVG is centered block element
		const innerSvg = diag.querySelector("svg");
		if (innerSvg) {
			innerSvg.style.position = "static";
			innerSvg.style.display = "block";
			innerSvg.style.margin = "0 auto";
			innerSvg.style.maxWidth = "100%";
			innerSvg.style.height = "auto";
		}
	});

	const diagramsSection = document.createElement("div");
	diagramsSection.className = "pdf-diagrams-section";
	diagramsSection.style.marginTop = "32px";
	diagramsSection.style.borderTop = "1px solid #e4e4e7";
	diagramsSection.style.paddingTop = "24px";
	diagramsSection.style.pageBreakBefore = "auto";

	const sectionTitle = document.createElement("h2");
	sectionTitle.style.fontSize = "18px";
	sectionTitle.style.fontWeight = "700";
	sectionTitle.style.color = "#18181b";
	sectionTitle.style.marginBottom = "16px";
	sectionTitle.textContent = "Diagrams";
	diagramsSection.appendChild(sectionTitle);

	diagramContainers.forEach((diag) => {
		diagramsSection.appendChild(diag);
	});

	container.appendChild(diagramsSection);
}

/**
 * Strips non-content interactive UI buttons, mastery banners, and unwraps <details> tags.
 */
function stripInteractiveElements(container: HTMLElement): void {
	// Remove all button elements (proceed to quiz, previous, chat icons, copy buttons, etc.)
	container.querySelectorAll("button").forEach((btn) => btn.remove());

	// Remove source citations action area if present
	container.querySelectorAll(".source-citations").forEach((el) => el.remove());

	// Remove "Topic mastered!" status banner
	const masteryBanners = Array.from(container.querySelectorAll(".text-green-600, .text-green-400"));
	masteryBanners.forEach((el) => {
		if (el.textContent?.includes("Topic mastered")) {
			const cardBox = el.closest(".flex.items-center");
			if (cardBox && cardBox !== container && container.contains(cardBox)) {
				cardBox.remove();
			}
		}
	});

	// Unwrap <details> tags (remove <summary> "Review explanation", keep inner markdown content)
	const detailsElements = Array.from(container.querySelectorAll("details"));
	detailsElements.forEach((detailsEl) => {
		const summary = detailsEl.querySelector("summary");
		if (summary) summary.remove();

		// Move inner children out of details tag into parent container
		while (detailsEl.firstChild) {
			detailsEl.parentNode?.insertBefore(detailsEl.firstChild, detailsEl);
		}
		detailsEl.remove();
	});

	// Remove bottom navigation/footer action rows
	const actionRows = Array.from(container.querySelectorAll(".border-t"));
	actionRows.forEach((row) => {
		const text = row.textContent || "";
		if (
			text.includes("quiz") ||
			text.includes("Previous") ||
			text.includes("Transitioning") ||
			text.includes("Next") ||
			row.children.length === 0
		) {
			row.remove();
		}
	});
}

/**
 * Polls off-screen container until markdown text, KaTeX formulas, and Mermaid SVG diagrams
 * finish rendering.
 */
async function waitForContentSettled(container: HTMLElement, maxWaitMs = 4000): Promise<void> {
	const startTime = Date.now();
	// Mermaid debounces 300ms — only enforce floor while wrappers still lack SVG.
	await new Promise<void>((resolve) => {
		const check = () => {
			const hasText = !!container.querySelector(
				"p, h1, h2, h3, h4, h5, h6, li, table, code, pre, span",
			);
			const mermaidWrappers = Array.from(
				container.querySelectorAll(".mermaid-wrapper"),
			);
			const pendingMermaid = mermaidWrappers.some(
				(w) => !w.querySelector("svg") && !w.querySelector(".text-red-500"),
			);
			const mermaidsReady = !pendingMermaid;
			const elapsed = Date.now() - startTime;
			const minWait = pendingMermaid ? 350 : 0;

			if ((hasText && mermaidsReady && elapsed >= minWait) || elapsed > maxWaitMs) {
				setTimeout(resolve, pendingMermaid ? 200 : 50);
			} else {
				setTimeout(check, 50);
			}
		};
		check();
	});
}

/**
 * Helper to construct a jsPDF instance for a given concept element.
 * Positions exportWrapper at position: fixed; left: 0; top: 0; zIndex: -99999
 * so html2canvas reads (0,0) coordinates without clipping, without body reflow flicker.
 */
async function buildPdfForElement(
	title: string,
	contentElement: HTMLElement,
	sequenceIndex?: number,
	complexity?: string,
): Promise<jsPDF> {
	// fixed + off-flow: no body reflow/scrollbar flicker; left/top 0 so html2canvas
	// reads real (0,0) coords (left:-9999px clips overflow and blanks body pages)
	const exportWrapper = document.createElement("div");
	exportWrapper.className = "pdf-export-wrapper";
	exportWrapper.style.position = "fixed";
	exportWrapper.style.left = "0";
	exportWrapper.style.top = "0";
	exportWrapper.style.zIndex = "-99999";
	exportWrapper.style.width = "800px";
	exportWrapper.style.backgroundColor = "#ffffff";
	exportWrapper.style.color = "#18181b";
	exportWrapper.style.padding = "32px";
	exportWrapper.style.boxSizing = "border-box";
	exportWrapper.style.fontFamily = "'Inter', -apple-system, BlinkMacSystemFont, sans-serif";
	exportWrapper.style.overflow = "visible";
	exportWrapper.style.pointerEvents = "none";
	exportWrapper.setAttribute("aria-hidden", "true");

	// Scoped light mode typography and code highlighting rules
	const styleTag = document.createElement("style");
	styleTag.textContent = `
		.pdf-export-wrapper {
			background-color: #ffffff !important;
			color: #18181b !important;
		}
		.pdf-export-wrapper * {
			box-sizing: border-box !important;
		}
		.pdf-export-wrapper p, .pdf-export-wrapper li, .pdf-export-wrapper span, .pdf-export-wrapper td, .pdf-export-wrapper th {
			color: #18181b !important;
			line-height: 1.6 !important;
		}
		.pdf-export-wrapper h1, .pdf-export-wrapper h2, .pdf-export-wrapper h3, .pdf-export-wrapper h4, .pdf-export-wrapper h5, .pdf-export-wrapper h6 {
			color: #09090b !important;
			font-weight: 700 !important;
		}
		.pdf-export-wrapper pre,
		.pdf-export-wrapper .not-prose,
		.pdf-export-wrapper [class*="language-"],
		.pdf-export-wrapper .token {
			background-color: #f4f4f5 !important;
			background-image: none !important;
			border: 1px solid #e4e4e7 !important;
			border-radius: 8px !important;
			color: #18181b !important;
		}
		.pdf-export-wrapper pre {
			padding: 12px !important;
			margin: 12px 0 !important;
		}
		.pdf-export-wrapper pre code,
		.pdf-export-wrapper code,
		.pdf-export-wrapper pre span,
		.pdf-export-wrapper .token {
			background-color: transparent !important;
			background-image: none !important;
			color: #09090b !important;
			font-family: "JetBrains Mono", "Fira Code", ui-monospace, monospace !important;
			text-shadow: none !important;
		}
		.pdf-export-wrapper .katex {
			color: #09090b !important;
			font-size: 1.05em !important;
		}
		.pdf-export-wrapper .katex-html {
			color: #09090b !important;
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
	`;
	exportWrapper.appendChild(styleTag);

	// PDF Header
	const headerDiv = document.createElement("div");
	headerDiv.style.borderBottom = "2px solid #e4e4e7";
	headerDiv.style.paddingBottom = "16px";
	headerDiv.style.marginBottom = "24px";
	headerDiv.style.display = "flex";
	headerDiv.style.justifyContent = "space-between";
	headerDiv.style.alignItems = "center";

	const leftHeader = document.createElement("div");
	const titleEl = document.createElement("h1");
	titleEl.style.fontSize = "22px";
	titleEl.style.fontWeight = "700";
	titleEl.style.color = "#18181b";
	titleEl.style.margin = "0 0 6px 0";
	titleEl.textContent = title;
	leftHeader.appendChild(titleEl);

	if (complexity) {
		const badge = document.createElement("span");
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
		const indexEl = document.createElement("span");
		indexEl.style.fontSize = "14px";
		indexEl.style.fontWeight = "600";
		indexEl.style.color = "#71717a";
		indexEl.textContent = `#${sequenceIndex + 1}`;
		headerDiv.appendChild(indexEl);
	}

	exportWrapper.appendChild(headerDiv);

	// Clone explanation content and reset cloned root styles
	const contentClone = contentElement.cloneNode(true) as HTMLElement;
	contentClone.style.position = "relative";
	contentClone.style.left = "0";
	contentClone.style.top = "0";
	contentClone.style.width = "100%";
	contentClone.style.height = "auto";
	contentClone.style.display = "block";
	contentClone.style.opacity = "1";
	contentClone.style.visibility = "visible";
	contentClone.style.color = "#18181b";
	contentClone.style.backgroundColor = "#ffffff";
	contentClone.style.zIndex = "auto";

	// Ensure visible descendant elements stay visible
	contentClone.querySelectorAll("*").forEach((el) => {
		if (el instanceof HTMLElement || el instanceof SVGElement) {
			if (el.classList.contains("katex-mathml")) {
				el.style.display = "none";
				return;
			}
			if (el.style.opacity === "0" || el.style.opacity === "0.01") {
				el.style.opacity = "1";
			}
			if (el.style.visibility === "hidden") {
				if (el.style.position !== "absolute" || el.style.top !== "-9999px") {
					el.style.visibility = "visible";
				}
			}
		}
	});

	stripInteractiveElements(contentClone);
	stripCuriositySpark(contentClone);

	const firstH1 = contentClone.querySelector("h1");
	if (firstH1 && firstH1.textContent?.trim().toLowerCase() === title.trim().toLowerCase()) {
		firstH1.remove();
	}

	moveDiagramsToDedicatedSection(contentClone);
	prepareSvgsForPdf(contentClone);

	exportWrapper.appendChild(contentClone);
	document.body.appendChild(exportWrapper);

	try {
		await waitForContentSettled(exportWrapper, 4000);

		const wrapperHeight = Math.max(
			exportWrapper.scrollHeight,
			exportWrapper.offsetHeight,
			contentClone.scrollHeight + 120,
			600,
		);
		exportWrapper.style.height = `${wrapperHeight}px`;

		const canvas = await html2canvas(exportWrapper, {
			scale: 2,
			useCORS: true,
			allowTaint: false,
			logging: false,
			backgroundColor: "#ffffff",
			x: 0,
			y: 0,
			scrollX: 0,
			scrollY: 0,
			width: 800,
			height: wrapperHeight,
			windowWidth: 800,
			windowHeight: wrapperHeight,
			onclone: (_doc, cloned) => {
				// Flatten Prism/theme inline colors that beat stylesheet cascade
				cloned.querySelectorAll("pre, code, .token").forEach((node) => {
					if (node instanceof HTMLElement) {
						node.style.setProperty("color", "#09090b", "important");
						node.style.setProperty("background-color", node.tagName === "PRE" ? "#f4f4f5" : "transparent", "important");
						node.style.setProperty("text-shadow", "none", "important");
					}
				});
			},
		});

		const imgData = canvas.toDataURL("image/jpeg", 0.98);
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
		if (document.body.contains(exportWrapper)) {
			document.body.removeChild(exportWrapper);
		}
	}
}

/**
 * Exports a single course concept module content as a downloadable PDF.
 */
export async function exportConceptAsPdf(
	title: string,
	contentElement: HTMLElement,
	sequenceIndex?: number,
	complexity?: string,
): Promise<void> {
	const filename = sanitizeFilename(title);
	const pdf = await buildPdfForElement(title, contentElement, sequenceIndex, complexity);
	pdf.save(filename);
}

/**
 * Generates a PDF Blob for a concept module.
 */
export async function exportConceptAsPdfBlob(
	title: string,
	contentElement: HTMLElement,
	sequenceIndex?: number,
	complexity?: string,
): Promise<Blob> {
	const pdf = await buildPdfForElement(title, contentElement, sequenceIndex, complexity);
	return pdf.output("blob");
}

/**
 * Exports all concept modules of a completed course as a ZIP file named after the course.
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

	// fixed off-flow mount — no host UI reflow while modules render
	const mountDiv = document.createElement("div");
	mountDiv.className = "pdf-temp-mount";
	mountDiv.style.position = "fixed";
	mountDiv.style.left = "0";
	mountDiv.style.top = "0";
	mountDiv.style.zIndex = "-99999";
	mountDiv.style.width = "800px";
	mountDiv.style.backgroundColor = "#ffffff";
	mountDiv.style.color = "#18181b";
	mountDiv.style.opacity = "1";
	mountDiv.style.visibility = "visible";
	mountDiv.style.overflow = "visible";
	mountDiv.style.pointerEvents = "none";
	mountDiv.setAttribute("aria-hidden", "true");
	document.body.appendChild(mountDiv);

	const root = createRoot(mountDiv);

	try {
		for (let i = 0; i < sortedNodes.length; i++) {
			const node = sortedNodes[i];
			const markdown = node.content_markdown;
			if (!markdown) continue;

			// key forces full remount so prior module Mermaid/SVG never leaks
			root.render(
				React.createElement(MarkdownRenderer, {
					key: node.id ?? `export-node-${i}`,
					content: markdown,
				}),
			);

			// Flush React commit before polling Mermaid (300ms debounce + render)
			await new Promise<void>((r) => requestAnimationFrame(() => r()));
			await waitForContentSettled(mountDiv, 5000);

			const pdfBlob = await exportConceptAsPdfBlob(
				node.title,
				mountDiv,
				node.sequence_index ?? i,
				node.complexity,
			);

			const seqPrefix = String((node.sequence_index ?? i) + 1).padStart(2, "0");
			const cleanTitle = sanitizeFilename(node.title).replace(/\.pdf$/i, "");
			const pdfFilename = `${seqPrefix}_${cleanTitle}.pdf`;
			zip.file(pdfFilename, pdfBlob);
		}
	} finally {
		root.unmount();
		if (document.body.contains(mountDiv)) {
			document.body.removeChild(mountDiv);
		}
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
