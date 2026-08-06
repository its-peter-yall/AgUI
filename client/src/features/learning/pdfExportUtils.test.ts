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
 *    Ensures filename sanitization, CuriositySpark stripping, diagram relocation,
 *    and ZIP export functionality work reliably.
 *
 * KEY COMPONENTS:
 *    - sanitizeFilename tests: Verifies illegal character removal and extension handling
 *    - exportConceptAsPdf tests: Verifies html2canvas-pro and jsPDF caller behavior
 *    - exportCourseAsZip tests: Verifies ZIP creation and packaging for completed courses
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: ./pdfExportUtils, @/lib/learningApi
 * ============================================================================
 */
import { describe, it, expect, vi } from "vitest";
import {
	sanitizeFilename,
	exportConceptAsPdf,
	exportCourseAsZip,
	stripCuriositySpark,
	moveDiagramsToDedicatedSection,
} from "./pdfExportUtils";

if (typeof window !== "undefined") {
	if (!URL.createObjectURL) {
		URL.createObjectURL = vi.fn().mockReturnValue("blob:mock-url");
	}
	if (!URL.revokeObjectURL) {
		URL.revokeObjectURL = vi.fn();
	}
}

const mockSave = vi.fn();
const mockOutput = vi.fn().mockReturnValue(new Blob(["mock pdf"], { type: "application/pdf" }));
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
			output: mockOutput,
		})),
	};
});

const mockZipFile = vi.fn();
const mockGenerateAsync = vi.fn().mockResolvedValue(new Blob(["mock zip"], { type: "application/zip" }));

vi.mock("jszip", () => {
	return {
		default: vi.fn().mockImplementation(() => ({
			file: mockZipFile,
			generateAsync: mockGenerateAsync,
		})),
	};
});

vi.mock("@/lib/learningApi", () => {
	return {
		getLearningSession: vi.fn().mockResolvedValue({
			session: { id: "session-1", course_title: "Mastering Knowledge Graphs and GraphRAG" },
			nodes: [
				{
					id: "node-1",
					title: "What is GraphRAG?",
					sequence_index: 0,
					content_markdown: "## What is GraphRAG?\nGraphRAG is a retrieval technique.",
					complexity: "Basic",
				},
				{
					id: "node-2",
					title: "Building Knowledge Graphs",
					sequence_index: 1,
					content_markdown: "## Building Knowledge Graphs\nNodes and edges representation.",
					complexity: "Intermediate",
				},
			],
		}),
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
				<div class="curiosity-spark mt-6 p-4 rounded-lg border border-primary/20 bg-primary/5">
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
			expect(container.innerHTML).toContain("Main content explanation");
		});

		it("does not wipe parent card body when curiosity sits inside generic border/rounded wrappers", () => {
			const container = document.createElement("div");
			container.className = "p-4 relative border rounded-lg";
			container.innerHTML = `
				<h2>GraphRAG Basics</h2>
				<p>Body paragraph that must survive export.</p>
				<pre><code>const x = 1;</code></pre>
				<div class="mt-6 p-4 rounded-lg border border-primary/20 bg-primary/5">
					<div class="flex items-center gap-2 mb-3">
						<h4>Curious to explore more?</h4>
					</div>
					<p>Click any question to ask:</p>
					<ul><li>What is a knowledge graph?</li></ul>
				</div>
			`;

			stripCuriositySpark(container);

			expect(container.querySelector("h2")?.textContent).toBe("GraphRAG Basics");
			expect(container.innerHTML).toContain("Body paragraph that must survive export.");
			expect(container.innerHTML).toContain("const x = 1;");
			expect(container.innerHTML).not.toContain("Curious to explore more?");
			expect(container.innerHTML).not.toContain("What is a knowledge graph?");
		});

		it("strips markdown-embedded curiosity heading without deleting prior siblings", () => {
			const container = document.createElement("div");
			container.innerHTML = `
				<h2>Main Concept</h2>
				<p>Keep me</p>
				<h3>Curious to explore more?</h3>
				<p>Follow-up question list intro</p>
				<ul><li>Q1</li></ul>
				<h3>Next Real Section</h3>
				<p>After curiosity</p>
			`;

			stripCuriositySpark(container);

			expect(container.innerHTML).toContain("Keep me");
			expect(container.innerHTML).toContain("Next Real Section");
			expect(container.innerHTML).toContain("After curiosity");
			expect(container.innerHTML).not.toContain("Curious to explore more?");
			expect(container.innerHTML).not.toContain("Follow-up question list intro");
			expect(container.innerHTML).not.toContain("Q1");
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

	describe("exportCourseAsZip", () => {
		it("fetches course nodes, builds PDF for each module, and packages into zip with sequential filenames", async () => {
			// Mock click on anchor element to prevent jsdom navigation error
			const mockClick = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

			await exportCourseAsZip("session-1", "Mastering Knowledge Graphs and GraphRAG");

			expect(mockZipFile).toHaveBeenCalledTimes(2);
			expect(mockZipFile).toHaveBeenNthCalledWith(1, "01_What is GraphRAG-.pdf", expect.any(Blob));
			expect(mockZipFile).toHaveBeenNthCalledWith(2, "02_Building Knowledge Graphs.pdf", expect.any(Blob));
			expect(mockGenerateAsync).toHaveBeenCalledWith({ type: "blob" });

			mockClick.mockRestore();
		});
	});
});

