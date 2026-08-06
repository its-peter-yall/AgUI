/**
 * ============================================================================
 * FILE: vectorPlotUtils.ts
 * LOCATION: client/src/features/learning/vectorPlotUtils.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Pure SVG builder for ```vector-plot``` JSON diagrams (export + shared use).
 *
 * ROLE IN PROJECT:
 *    Lets PDF export inline vector graphs without React VectorPlot lifecycle.
 *
 * KEY COMPONENTS:
 *    - renderVectorPlotSvg: JSON string → SVG markup
 *
 * DEPENDENCIES:
 *    - External: None
 *    - Internal: None
 *
 * USAGE:
 *    const svg = renderVectorPlotSvg(fenceBody);
 * ============================================================================
 */

type VectorPoint = {
	name: string;
	x: number;
	y: number;
	color?: string;
};

type VectorPlotData = {
	vectors: VectorPoint[];
	grid?: boolean;
	xAxisLabel?: string;
	yAxisLabel?: string;
};

function escapeXml(text: string): string {
	return text
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;");
}

/**
 * Renders vector-plot JSON into a standalone SVG string.
 * Returns empty string on invalid input.
 */
export function renderVectorPlotSvg(data: string): string {
	if (!data?.trim()) return "";

	let plotData: VectorPlotData;
	try {
		plotData = JSON.parse(data) as VectorPlotData;
	} catch {
		return "";
	}

	if (!plotData.vectors || !Array.isArray(plotData.vectors) || plotData.vectors.length === 0) {
		return "";
	}

	const width = 380;
	const height = 300;
	const paddingX = 70;
	const paddingY = 30;

	const allX = plotData.vectors.flatMap((v) => [0, Number(v.x) || 0]);
	const allY = plotData.vectors.flatMap((v) => [0, Number(v.y) || 0]);
	const minX = Math.min(...allX, -2);
	const maxX = Math.max(...allX, 5);
	const minY = Math.min(...allY, -2);
	const maxY = Math.max(...allY, 5);

	const domainX: [number, number] = [minX - 1, maxX + 1];
	const domainY: [number, number] = [minY - 1, maxY + 1];

	const mapX = (val: number) =>
		paddingX +
		((val - domainX[0]) / (domainX[1] - domainX[0])) * (width - 2 * paddingX);
	const mapY = (val: number) =>
		height -
		(paddingY +
			((val - domainY[0]) / (domainY[1] - domainY[0])) *
				(height - 2 * paddingY));

	const originX = mapX(0);
	const originY = mapY(0);
	const gridStroke = "#e4e4e7";
	const axisStroke = "#a1a1aa";
	const axisTextFill = "#71717a";
	const originTextFill = "#a1a1aa";

	const parts: string[] = [];
	parts.push(
		`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" class="pdf-vector-plot">`,
	);
	parts.push("<defs>");

	plotData.vectors.forEach((v, i) => {
		const color = escapeXml(v.color || "#ffb74d");
		parts.push(
			`<marker id="pdf-arrow-${i}" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 1.5 L 10 5 L 0 8.5 z" fill="${color}"/></marker>`,
		);
	});
	parts.push("</defs>");

	if (plotData.grid !== false) {
		for (let x = Math.ceil(domainX[0]); x <= Math.floor(domainX[1]); x++) {
			if (x === 0) continue;
			const mx = mapX(x);
			parts.push(
				`<line x1="${mx}" y1="${paddingY}" x2="${mx}" y2="${height - paddingY}" stroke="${gridStroke}" stroke-width="0.5"/>`,
			);
		}
		for (let y = Math.ceil(domainY[0]); y <= Math.floor(domainY[1]); y++) {
			if (y === 0) continue;
			const my = mapY(y);
			parts.push(
				`<line x1="${paddingX}" y1="${my}" x2="${width - paddingX}" y2="${my}" stroke="${gridStroke}" stroke-width="0.5"/>`,
			);
		}
	}

	parts.push(
		`<line x1="${paddingX}" y1="${originY}" x2="${width - paddingX}" y2="${originY}" stroke="${axisStroke}" stroke-width="1.5"/>`,
	);
	parts.push(
		`<line x1="${originX}" y1="${paddingY}" x2="${originX}" y2="${height - paddingY}" stroke="${axisStroke}" stroke-width="1.5"/>`,
	);

	const xLabel = escapeXml(plotData.xAxisLabel || "x");
	const yLabel = escapeXml(plotData.yAxisLabel || "y");
	parts.push(
		`<text x="${width - paddingX + 5}" y="${originY + 4}" fill="${axisTextFill}" font-size="10" text-anchor="start">${xLabel}</text>`,
	);
	parts.push(
		`<text x="${originX}" y="${paddingY - 8}" fill="${axisTextFill}" font-size="10" text-anchor="middle">${yLabel}</text>`,
	);
	parts.push(
		`<text x="${originX - 8}" y="${originY + 12}" fill="${originTextFill}" font-size="8" text-anchor="end">0</text>`,
	);

	plotData.vectors.forEach((v, i) => {
		const vx = mapX(Number(v.x) || 0);
		const vy = mapY(Number(v.y) || 0);
		const color = escapeXml(v.color || "#ffb74d");
		const nameLines = String(v.name || "").split(/<br\s*\/?>/i);
		const lines = [...nameLines];
		lines[lines.length - 1] = `${lines[lines.length - 1]} (${v.x}, ${v.y})`;

		const textAnchor = (Number(v.x) || 0) >= 0 ? "start" : "end";
		const textX = vx + ((Number(v.x) || 0) >= 0 ? 8 : -8);
		const lineHeight = 14;
		const totalHeight = (lines.length - 1) * lineHeight;
		const startY =
			vy +
			((Number(v.y) || 0) >= 0 ? -4 : 8) -
			((Number(v.y) || 0) >= 0 ? totalHeight : 0);

		parts.push("<g>");
		parts.push(
			`<line x1="${originX}" y1="${originY}" x2="${vx}" y2="${vy}" stroke="${color}" stroke-width="2.5" marker-end="url(#pdf-arrow-${i})"/>`,
		);
		parts.push(
			`<text x="${textX}" y="${startY}" fill="${color}" font-size="11" font-weight="bold" text-anchor="${textAnchor}">`,
		);
		lines.forEach((line, idx) => {
			const dy = idx === 0 ? 0 : lineHeight;
			parts.push(
				`<tspan x="${textX}" dy="${dy}">${escapeXml(line)}</tspan>`,
			);
		});
		parts.push("</text></g>");
	});

	parts.push("</svg>");
	return parts.join("");
}
