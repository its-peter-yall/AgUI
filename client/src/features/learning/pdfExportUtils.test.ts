/**
 * ============================================================================
 * FILE: pdfExportUtils.test.ts
 * LOCATION: client/src/features/learning/pdfExportUtils.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Unit tests for pdfExportUtils helper functions.
 *
 * ROLE IN PROJECT:
 *    Ensures filename sanitization and export triggering work reliably.
 *
 * KEY COMPONENTS:
 *    - sanitizeFilename tests: Verifies illegal character removal and extension handling
 *    - exportConceptAsPdf tests: Verifies html2canvas-pro and jsPDF caller behavior
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: ./pdfExportUtils
 * ============================================================================
 */
import { describe, it, expect, vi } from "vitest";
import {
	sanitizeFilename,
	exportConceptAsPdf,
	stripCuriositySpark,
	moveDiagramsToDedicatedSection,
} from "./pdfExportUtils";

const mockSave = vi.fn();
const mockAddImage = vi.fn();
const mockAddPage = vi.fn();

vi.mock("html2canvas-pro", () => {
	const mockCanvas = {
		width: 1600,
		height: 1200,
		toDataURL: vi.fn().mockReturnValue("data:image/jpeg;base64,mock"),
	};
	return {
		default: vi.fn().mockImplementation(() => {
			return Promise.resolve(mockCanvas);
		}),
	};
});

vi.mock("jspdf", () => {
	return {
		jsPDF: vi.fn().mockImplementation(() => ({
			internal: {
				pageSize: {
					getWidth: () => 210,
					getHeight: () => 297,
				},
			},
			addImage: mockAddImage,
			addPage: mockAddPage,
			save: mockSave,
		})),
	};
});

describe("pdfExportUtils", () => {
	describe("sanitizeFilename", () => {
		it("returns concept-explanation.pdf for empty input", () => {
			expect(sanitizeFilename("")).toBe("concept-explanation.pdf");
			expect(sanitizeFilename("   ")).toBe("concept-explanation.pdf");
		});

		it("cleans illegal characters and adds pdf extension", () => {
			expect(sanitizeFilename("Understanding RAG: Limits & Graph?")).toBe(
				"Understanding RAG- Limits & Graph-.pdf",
			);
			expect(sanitizeFilename("Topic/Subtopic\\1*2")).toBe(
				"Topic-Subtopic-1-2.pdf",
			);
		});

		it("preserves topic title as file name when valid", () => {
			expect(sanitizeFilename("Understanding Classic RAG and Its Limits")).toBe(
				"Understanding Classic RAG and Its Limits.pdf",
			);
		});

		it("does not duplicate .pdf extension if already present", () => {
			expect(sanitizeFilename("My_Topic.pdf")).toBe("My_Topic.pdf");
		});
	});

	describe("stripCuriositySpark", () => {
		it("removes CuriositySpark section completely by class and heading text", () => {
			const container = document.createElement("div");
			container.innerHTML = `
				<h2>Main Concept</h2>
				<p>Main content explanation</p>
				<div class="mt-6 p-4 rounded-lg border">
					<div class="flex items-center gap-2 mb-3">
						<h4>Curious to explore more?</h4>
					</div>
					<p>Click any question to ask:</p>
					<ul><li>Question 1</li></ul>
				</div>
			`;

			expect(container.innerHTML).toContain("Curious to explore more?");
			stripCuriositySpark(container);
			expect(container.innerHTML).not.toContain("Curious to explore more?");
			expect(container.innerHTML).not.toContain("Click any question to ask:");
			expect(container.innerHTML).toContain("Main Concept");
		});
	});

	describe("moveDiagramsToDedicatedSection", () => {
		it("extracts inline mermaid diagrams and places them in dedicated Diagrams section with page-break avoidance styling", () => {
			const container = document.createElement("div");
			container.innerHTML = `
				<h2>Main Concept</h2>
				<p>First paragraph before diagram</p>
				<div class="mermaid-wrapper my-6">
					<div class="mermaid-container">
						<svg width="400" height="200"><g><text>Diagram 1</text></g></svg>
					</div>
				</div>
				<p>Second paragraph after diagram</p>
			`;

			moveDiagramsToDedicatedSection(container);

			const diagramsSection = container.querySelector(".pdf-diagrams-section");
			expect(diagramsSection).not.toBeNull();
			expect(diagramsSection?.querySelector("h2")?.textContent).toBe("Diagrams");

			const mermaidWrapper = diagramsSection?.querySelector(".mermaid-wrapper") as HTMLElement;
			expect(mermaidWrapper).not.toBeNull();
			expect(mermaidWrapper.style.pageBreakInside).toBe("avoid");
			expect(mermaidWrapper.style.breakInside).toBe("avoid");
			expect(mermaidWrapper.style.maxWidth).toBe("100%");

			// Verify inline text body no longer has the mermaid diagram inline between paragraphs
			const children = Array.from(container.children);
			const lastChild = children[children.length - 1];
			expect(lastChild).toBe(diagramsSection);
		});

		it("does not create Diagrams section if no diagrams are present", () => {
			const container = document.createElement("div");
			container.innerHTML = "<h2>Main Concept</h2><p>Text only</p>";

			moveDiagramsToDedicatedSection(container);
			expect(container.querySelector(".pdf-diagrams-section")).toBeNull();
		});
	});

	describe("exportConceptAsPdf", () => {
		it("prepares export wrapper, renders canvas, and saves PDF", async () => {
			const container = document.createElement("div");
			container.innerHTML = `
				<h2>Test Concept</h2>
				<p>Some markdown text content</p>
				<div class="curiosity-spark"><h4>Curious to explore more?</h4></div>
				<div class="mermaid-wrapper"><svg width="100" height="100"></svg></div>
			`;

			await exportConceptAsPdf(
				"Understanding Classic RAG and Its Limits",
				container,
				1,
				"Basic",
			);

			const html2canvas = (await import("html2canvas-pro")).default;
			expect(html2canvas).toHaveBeenCalled();
			expect(mockSave).toHaveBeenCalledWith("Understanding Classic RAG and Its Limits.pdf");
		});
	});
});

