/**
 * ============================================================================
 * FILE: mermaidUtils.ts
 * LOCATION: client/src/features/learning/mermaidUtils.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Utility functions for preprocessing and cleaning up Mermaid diagrams.
 *
 * ROLE IN PROJECT:
 *    Provides chart validation and preprocessing to prevent syntax errors
 *    in the Mermaid rendering component.
 *
 * KEY COMPONENTS:
 *    - preprocessMermaid: Cleans nested quotes in node labels.
 *    - downloadMermaidAsPng: Converts SVG string to PNG image and triggers download.
 *
 * DEPENDENCIES:
 *    - External: None
 *    - Internal: None
 *
 * USAGE:
 *    import { preprocessMermaid, downloadMermaidAsPng } from "./mermaidUtils";
 * ============================================================================
 */

/**
 * Preprocesses a Mermaid chart string to fix common syntax errors.
 * Specifically, it replaces nested, unescaped double quotes inside node labels with single quotes.
 * E.g., `A["multimodal LLM<br/>Can "see" image context"]` becomes `A["multimodal LLM<br/>Can 'see' image context"]`
 */
export function preprocessMermaid(chart: string): string {
	const lines = chart.split("\n");
	const processedLines = lines.map((line) => {
		// Matches node definitions with double-quoted labels:
		// Group 1: Node ID
		// Group 2: Opening shape + quote (e.g. [" or (")
		// Group 3: Label content (lazy match)
		// Group 4: Closing quote + shape (e.g. "] or ")
		// Lookahead: followed by connector, spaces + connector, newline, or end of string
		const nodeRegex = /(\b\w+)\s*(\[\s*"|\(\s*"|\{\s*"|\(\[\s*"|\[\(\s*"|\(\(\s*"|\[\\"\s*|\[\/"\s*|>\s*")([\s\S]*?)("\s*\]|"\s*\)|"\s*\}|"\s*\]\s*\)|"\s*\)\s*\]|"\s*\)\s*\)|"\s*\\\]|"\s*\/\]|"\s*\])(?=\s*(?:-->|---|==>|-\.-|--|\n|\r|$))/g;

		return line.replace(nodeRegex, (_match, id, open, content, close) => {
			// Replace any nested double quotes (escaped or unescaped) with single quotes
			const cleanContent = content.replace(/\\"/g, "'").replace(/"/g, "'");
			return `${id}${open}${cleanContent}${close}`;
		});
	});

	return processedLines.join("\n");
}

/**
 * Converts a Mermaid SVG string to PNG format and triggers a file download in the browser.
 */
export function downloadMermaidAsPng(svgString: string, filename = "mermaid-diagram.png"): void {
	if (typeof window === "undefined" || !svgString) return;

	const container = document.createElement("div");
	container.innerHTML = svgString;
	const svgElement = container.querySelector("svg");
	if (!svgElement) return;

	// Prefer viewBox for exact intrinsic diagram dimensions & aspect ratio
	const viewBoxAttr = svgElement.getAttribute("viewBox");
	let width = 0;
	let height = 0;

	if (viewBoxAttr) {
		const parts = viewBoxAttr.trim().split(/[\s,]+/).map(Number);
		if (parts.length === 4 && parts[2] > 0 && parts[3] > 0) {
			width = parts[2];
			height = parts[3];
		}
	}

	// Fallback to width/height attributes if numeric (ignore percentage values like "100%")
	if (!width || !height) {
		const rawWidth = svgElement.getAttribute("width") || "";
		const rawHeight = svgElement.getAttribute("height") || "";
		if (rawWidth && !rawWidth.includes("%")) {
			width = parseFloat(rawWidth) || 0;
		}
		if (rawHeight && !rawHeight.includes("%")) {
			height = parseFloat(rawHeight) || 0;
		}
	}

	if (!width || !height) {
		width = 800;
		height = 600;
	}

	// Explicitly set pixel dimensions on SVG clone to prevent canvas scaling distortion
	svgElement.setAttribute("width", String(width));
	svgElement.setAttribute("height", String(height));
	svgElement.removeAttribute("style");

	// Convert HTML foreignObject elements to native SVG text nodes to prevent Chrome canvas tainting
	const foreignObjects = Array.from(svgElement.querySelectorAll("foreignObject"));
	foreignObjects.forEach((fo) => {
		const textContent = fo.textContent?.trim() || "";
		if (!textContent) return;

		const x = parseFloat(fo.getAttribute("x") || "0");
		const y = parseFloat(fo.getAttribute("y") || "0");
		const foWidth = parseFloat(fo.getAttribute("width") || "0");
		const foHeight = parseFloat(fo.getAttribute("height") || "0");

		const textNode = document.createElementNS("http://www.w3.org/2000/svg", "text");
		textNode.setAttribute("fill", "#18181b");
		textNode.setAttribute("font-family", "Inter, sans-serif");
		textNode.setAttribute("font-size", "14px");

		const lines = textContent.split("\n").map((l) => l.trim()).filter(Boolean);
		if (lines.length > 1) {
			const lineHeight = 16;
			const startY = y + foHeight / 2 - ((lines.length - 1) * lineHeight) / 2;
			lines.forEach((line, index) => {
				const tspan = document.createElementNS("http://www.w3.org/2000/svg", "tspan");
				tspan.setAttribute("x", String(x + foWidth / 2));
				tspan.setAttribute("y", String(startY + index * lineHeight));
				tspan.setAttribute("text-anchor", "middle");
				tspan.setAttribute("dominant-baseline", "central");
				tspan.textContent = line;
				textNode.appendChild(tspan);
			});
		} else {
			textNode.setAttribute("x", String(x + foWidth / 2));
			textNode.setAttribute("y", String(y + foHeight / 2));
			textNode.setAttribute("text-anchor", "middle");
			textNode.setAttribute("dominant-baseline", "central");
			textNode.textContent = textContent;
		}

		fo.parentNode?.replaceChild(textNode, fo);
	});

	// Inject text fill styling overrides into SVG so canvas export retains dark text colors
	const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
	style.textContent = `
		text, tspan, span, div, a, p {
			fill: #18181b !important;
			color: #18181b !important;
		}
	`;
	svgElement.insertBefore(style, svgElement.firstChild);

	if (!svgElement.getAttribute("xmlns")) {
		svgElement.setAttribute("xmlns", "http://www.w3.org/2000/svg");
	}

	const serializedSvg = new XMLSerializer().serializeToString(svgElement);
	const blob = new Blob([serializedSvg], { type: "image/svg+xml;charset=utf-8" });
	const url = URL.createObjectURL(blob);

	const img = new Image();
	img.onload = () => {
		const scale = 2; // High-resolution 2x scale
		const canvas = document.createElement("canvas");
		canvas.width = width * scale;
		canvas.height = height * scale;

		const ctx = canvas.getContext("2d");
		if (ctx) {
			ctx.fillStyle = "#fafafa";
			ctx.fillRect(0, 0, canvas.width, canvas.height);
			ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

			try {
				const pngUrl = canvas.toDataURL("image/png");
				const a = document.createElement("a");
				a.href = pngUrl;
				a.download = filename;
				document.body.appendChild(a);
				a.click();
				document.body.removeChild(a);
			} catch (err) {
				console.warn("Canvas export tainted, falling back to SVG download:", err);
				const svgBlob = new Blob([serializedSvg], { type: "image/svg+xml;charset=utf-8" });
				const svgUrl = URL.createObjectURL(svgBlob);
				const a = document.createElement("a");
				a.href = svgUrl;
				a.download = filename.replace(/\.png$/, ".svg");
				document.body.appendChild(a);
				a.click();
				document.body.removeChild(a);
				URL.revokeObjectURL(svgUrl);
			}
		}
		URL.revokeObjectURL(url);
	};
	img.src = url;
}

