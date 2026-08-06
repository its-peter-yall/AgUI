/**
 * ============================================================================
 * FILE: pdfExportUtils.test.ts
 * LOCATION: client/src/features/learning/pdfExportUtils.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Unit tests for markdown-first PDF/ZIP export helpers.
 *
 * ROLE IN PROJECT:
 *    Ensures filename sanitization, curiosity stripping, Mermaid fence rendering,
 *    single-concept PDF export, and course ZIP packaging.
 *
 * KEY COMPONENTS:
 *    - sanitizeFilename tests
 *    - stripCuriosityFromMarkdown tests
 *    - renderMermaidFencesInMarkdown tests
 *    - exportConceptAsPdf tests
 *    - exportCourseAsZip tests
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: ./pdfExportUtils, @/lib/learningApi
 * ============================================================================
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import {
	sanitizeFilename,
	stripCuriosityFromMarkdown,
	renderMermaidFencesInMarkdown,
	exportConceptAsPdf,
	exportCourseAsZip,
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
const mockOutput = vi
	.fn()
	.mockReturnValue(new Blob(["mock pdf"], { type: "application/pdf" }));
const mockAddImage = vi.fn();
const mockAddPage = vi.fn();

vi.mock("html2canvas-pro", () => {
	const mockCanvas = {
		width: 1600,
		height: 1200,
		toDataURL: vi.fn().mockReturnValue("data:image/jpeg;base64,mock"),
	};
	return {
		default: vi.fn().mockImplementation(() => Promise.resolve(mockCanvas)),
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
const mockGenerateAsync = vi
	.fn()
	.mockResolvedValue(new Blob(["mock zip"], { type: "application/zip" }));

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
			session: {
				id: "session-1",
				course_title: "Mastering Knowledge Graphs and GraphRAG",
			},
			nodes: [
				{
					id: "node-1",
					title: "What is GraphRAG?",
					sequence_index: 0,
					content_markdown:
						"## What is GraphRAG?\nGraphRAG is a retrieval technique.",
					complexity: "Basic",
				},
				{
					id: "node-2",
					title: "Building Knowledge Graphs",
					sequence_index: 1,
					content_markdown:
						"## Building Knowledge Graphs\nNodes and edges representation.",
					complexity: "Intermediate",
				},
				{
					id: "node-empty",
					title: "Empty Module",
					sequence_index: 2,
					content_markdown: "",
					complexity: "Basic",
				},
			],
		}),
	};
});

const mockMermaidRender = vi.fn().mockResolvedValue({
	svg: '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><text>diagram</text></svg>',
});
const mockMermaidInitialize = vi.fn();

vi.mock("mermaid", () => {
	return {
		default: {
			initialize: (...args: unknown[]) => mockMermaidInitialize(...args),
			render: (...args: unknown[]) => mockMermaidRender(...args),
		},
	};
});

describe("pdfExportUtils", () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockOutput.mockReturnValue(
			new Blob(["mock pdf"], { type: "application/pdf" }),
		);
		mockMermaidRender.mockResolvedValue({
			svg: '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50"><text>diagram</text></svg>',
		});
	});

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

	describe("stripCuriosityFromMarkdown", () => {
		it("returns empty string for empty input", () => {
			expect(stripCuriosityFromMarkdown("")).toBe("");
		});

		it("strips curiosity section and keeps main content", () => {
			const md = [
				"## Main Concept",
				"Body paragraph.",
				"",
				"## Curious to explore more?",
				"- What is a knowledge graph?",
				"- How does GraphRAG work?",
			].join("\n");

			const result = stripCuriosityFromMarkdown(md);
			expect(result).toContain("Main Concept");
			expect(result).toContain("Body paragraph.");
			expect(result).not.toContain("Curious to explore more");
			expect(result).not.toContain("What is a knowledge graph?");
		});

		it("returns full markdown when no curiosity marker", () => {
			const md = "## Only content\nNo curiosity here.";
			expect(stripCuriosityFromMarkdown(md)).toBe(md);
		});
	});

	describe("renderMermaidFencesInMarkdown", () => {
		it("replaces mermaid fences with inline figure+svg", async () => {
			const md = [
				"Intro text",
				"",
				"```mermaid",
				"graph TD",
				"A-->B",
				"```",
				"",
				"After diagram",
			].join("\n");

			const result = await renderMermaidFencesInMarkdown(md);

			expect(mockMermaidRender).toHaveBeenCalled();
			expect(result).toContain('class="pdf-diagram"');
			expect(result).toContain("<svg");
			expect(result).toContain("Intro text");
			expect(result).toContain("After diagram");
			expect(result).not.toContain("```mermaid");
			expect(result).not.toContain("Diagrams");
		});

		it("uses error pre on mermaid failure, never loading placeholder", async () => {
			mockMermaidRender.mockRejectedValueOnce(new Error("bad chart"));

			const md = "```mermaid\ngraph TD\nA-->B\n```";
			const result = await renderMermaidFencesInMarkdown(md);

			expect(result).toContain('class="pdf-diagram-error"');
			expect(result).toContain("Diagram failed to render.");
			expect(result).not.toContain("Rendering diagram");
		});

		it("leaves non-mermaid fences untouched", async () => {
			const md = "```ts\nconst x = 1;\n```";
			const result = await renderMermaidFencesInMarkdown(md);
			expect(result).toContain("```ts");
			expect(mockMermaidRender).not.toHaveBeenCalled();
		});

		it("replaces vector-plot fences with inline SVG figure", async () => {
			const md = [
				"Before",
				"",
				"```vector-plot",
				JSON.stringify({
					vectors: [
						{ name: "A", x: 2, y: 3, color: "#ffb74d" },
						{ name: "B", x: 3, y: 4, color: "#4caf50" },
					],
					grid: true,
					xAxisLabel: "SemanticDepth",
					yAxisLabel: "GraphConnectivity",
				}),
				"```",
				"",
				"After",
			].join("\n");

			const result = await renderMermaidFencesInMarkdown(md);

			expect(result).toContain('class="pdf-diagram pdf-vector-diagram"');
			expect(result).toContain("<svg");
			expect(result).toContain("SemanticDepth");
			expect(result).toContain("Before");
			expect(result).toContain("After");
			expect(result).not.toContain("```vector-plot");
			expect(mockMermaidRender).not.toHaveBeenCalled();
		});
	});

	describe("exportConceptAsPdf", () => {
		it("renders markdown host, captures canvas, and saves PDF", async () => {
			await exportConceptAsPdf(
				"Understanding Classic RAG and Its Limits",
				"## Test Concept\n\nSome markdown text content",
				1,
				"Basic",
			);

			const html2canvas = (await import("html2canvas-pro")).default;
			expect(html2canvas).toHaveBeenCalled();
			expect(mockSave).toHaveBeenCalledWith(
				"Understanding Classic RAG and Its Limits.pdf",
			);
		});

		it("throws when markdown is empty after strip", async () => {
			await expect(exportConceptAsPdf("Empty", "")).rejects.toThrow(
				"No content to export.",
			);
			await expect(
				exportConceptAsPdf(
					"Only curiosity",
					"## Curious to explore more?\n- Q1",
				),
			).rejects.toThrow("No content to export.");
		});
	});

	describe("exportCourseAsZip", () => {
		it("builds sequential PDFs and skips empty modules", async () => {
			const mockClick = vi
				.spyOn(HTMLAnchorElement.prototype, "click")
				.mockImplementation(() => {});

			await exportCourseAsZip(
				"session-1",
				"Mastering Knowledge Graphs and GraphRAG",
			);

			expect(mockZipFile).toHaveBeenCalledTimes(2);
			expect(mockZipFile).toHaveBeenNthCalledWith(
				1,
				"01_What is GraphRAG-.pdf",
				expect.any(Blob),
			);
			expect(mockZipFile).toHaveBeenNthCalledWith(
				2,
				"02_Building Knowledge Graphs.pdf",
				expect.any(Blob),
			);
			expect(mockGenerateAsync).toHaveBeenCalledWith({ type: "blob" });

			mockClick.mockRestore();
		});
	});
});
