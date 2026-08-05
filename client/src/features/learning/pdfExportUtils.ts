/**
 * ============================================================================
 * FILE: pdfExportUtils.ts
 * LOCATION: client/src/features/learning/pdfExportUtils.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Generates and triggers download of a styled PDF for course concept modules.
 *
 * ROLE IN PROJECT:
 *    Utility within learning feature to render Markdown text, KaTeX formulas,
 *    and Mermaid diagrams into downloadable PDFs named after topic titles.
 *
 * KEY COMPONENTS:
 *    - sanitizeFilename: Cleans concept titles into safe PDF filenames
 *    - stripCuriositySpark: Removes curiosity Q&A section from export DOM
 *    - moveDiagramsToDedicatedSection: Relocates diagrams to dedicated bottom section
 *    - exportConceptAsPdf: Prepares off-screen light container and saves PDF
 *
 * DEPENDENCIES:
 *    - External: html2canvas-pro, jspdf
 *    - Internal: None
 *
 * USAGE:
 *    import { exportConceptAsPdf } from "./pdfExportUtils";
 *    await exportConceptAsPdf(title, element, sequenceIndex, complexity);
 * ============================================================================
 */
import html2canvas from "html2canvas-pro";
import { jsPDF } from "jspdf";

/**
 * Sanitizes a concept title for use as a valid PDF filename.
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
 * Completely strips the CuriositySpark ('Curious to explore more?') section from export DOM.
 * Targets specifically the CuriositySpark card container without touching main text content.
 */
export function stripCuriositySpark(container: HTMLElement): void {
	container.querySelectorAll(".curiosity-spark").forEach((el) => el.remove());

	const headings = Array.from(container.querySelectorAll("h4, h3"));
	headings.forEach((h4) => {
		if (
			container.contains(h4) &&
			h4.textContent &&
			h4.textContent.trim().includes("Curious to explore more?")
		) {
			const cardBox = h4.closest(".border, .rounded-lg");
			if (cardBox && cardBox !== container && container.contains(cardBox)) {
				cardBox.remove();
			}
		}
	});
}

/**
 * Extracts Mermaid/SVG diagrams from inline text, places them in a dedicated 'Diagrams'
 * section at the bottom of the content container, and applies page-break avoidance styling.
 */
export function moveDiagramsToDedicatedSection(container: HTMLElement): void {
	// Target ONLY Mermaid diagram containers (do NOT touch Lucide icons or text wrappers)
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
		diag.style.pageBreakInside = "avoid";
		diag.style.breakInside = "avoid";
		diag.style.maxWidth = "100%";
		diag.style.margin = "0 auto 16px auto";
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
 * Strips non-content interactive UI buttons (e.g. chat toggles, copy buttons)
 * from cloned export container without removing main content text.
 */
function stripInteractiveElements(container: HTMLElement): void {
	// Remove ALL button elements (proceed to quiz, previous, chat icons, copy buttons, etc.)
	container.querySelectorAll("button").forEach((btn) => btn.remove());

	// Remove source citations action area if present
	container.querySelectorAll(".source-citations").forEach((el) => el.remove());

	// Remove bottom navigation/footer action rows containing action buttons or quiz triggers
	const actionRows = Array.from(container.querySelectorAll(".border-t"));
	actionRows.forEach((row) => {
		const text = row.textContent || "";
		if (
			text.includes("quiz") ||
			text.includes("Previous") ||
			text.includes("Transitioning") ||
			row.children.length === 0
		) {
			row.remove();
		}
	});
}

/**
 * Exports a course concept module content as a downloadable PDF.
 * Uses html2canvas-pro to support modern Tailwind 4 CSS colors (e.g. oklch).
 */
export async function exportConceptAsPdf(
	title: string,
	contentElement: HTMLElement,
	sequenceIndex?: number,
	complexity?: string,
): Promise<void> {
	const filename = sanitizeFilename(title);

	// Create visible light mode container for high-res PDF snapshot
	const exportWrapper = document.createElement("div");
	exportWrapper.className = "pdf-export-wrapper";
	exportWrapper.style.position = "absolute";
	exportWrapper.style.left = "0";
	exportWrapper.style.top = "0";
	exportWrapper.style.zIndex = "99999";
	exportWrapper.style.width = "800px";
	exportWrapper.style.backgroundColor = "#ffffff";
	exportWrapper.style.color = "#18181b";
	exportWrapper.style.padding = "32px";
	exportWrapper.style.boxSizing = "border-box";
	exportWrapper.style.fontFamily = "'Inter', -apple-system, BlinkMacSystemFont, sans-serif";

	// Inject contrast typography rules to prevent invisible dark-mode text in export
	const styleTag = document.createElement("style");
	styleTag.textContent = `
		.pdf-export-wrapper, .pdf-export-wrapper * {
			color: #18181b !important;
			opacity: 1 !important;
		}
		.pdf-export-wrapper h1, .pdf-export-wrapper h2, .pdf-export-wrapper h3, .pdf-export-wrapper h4 {
			color: #09090b !important;
			font-weight: 700 !important;
		}
		.pdf-export-wrapper p, .pdf-export-wrapper li, .pdf-export-wrapper span {
			color: #27272a !important;
			line-height: 1.6 !important;
		}
		.pdf-export-wrapper pre, .pdf-export-wrapper code {
			background-color: #f4f4f5 !important;
			color: #18181b !important;
			border-radius: 4px;
		}
		.pdf-export-wrapper strong {
			color: #09090b !important;
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

	// Clone explanation content
	const contentClone = contentElement.cloneNode(true) as HTMLElement;
	stripInteractiveElements(contentClone);
	stripCuriositySpark(contentClone);
	moveDiagramsToDedicatedSection(contentClone);
	prepareSvgsForPdf(contentClone);

	// Enforce visible light colors on clone container
	contentClone.style.color = "#18181b";
	contentClone.style.backgroundColor = "#ffffff";

	exportWrapper.appendChild(contentClone);
	document.body.appendChild(exportWrapper);

	try {
		// Render element to high-res canvas using html2canvas-pro (handles oklch colors)
		const canvas = await html2canvas(exportWrapper, {
			scale: 2,
			useCORS: true,
			logging: false,
			backgroundColor: "#ffffff",
		});

		const imgData = canvas.toDataURL("image/jpeg", 0.98);
		const pdf = new jsPDF({
			orientation: "portrait",
			unit: "mm",
			format: "a4",
		});

		const pdfWidth = pdf.internal.pageSize.getWidth();
		const pdfHeight = pdf.internal.pageSize.getHeight();
		const margin = 10; // 10mm margins
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

		pdf.save(filename);
	} finally {
		if (document.body.contains(exportWrapper)) {
			document.body.removeChild(exportWrapper);
		}
	}
}
