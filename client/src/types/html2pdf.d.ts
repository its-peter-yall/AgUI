declare module "html2pdf.js" {
	export interface Html2PdfOptions {
		margin?: number | [number, number] | [number, number, number, number];
		filename?: string;
		image?: { type?: "jpeg" | "png" | "webp"; quality?: number };
		enableLinks?: boolean;
		html2canvas?: {
			scale?: number;
			useCORS?: boolean;
			logging?: boolean;
			backgroundColor?: string | null;
			[key: string]: unknown;
		};
		jsPDF?: {
			unit?: string;
			format?: string | [number, number];
			orientation?: "portrait" | "landscape";
			[key: string]: unknown;
		};
		pagebreak?: {
			mode?: string | string[];
			before?: string | string[];
			after?: string | string[];
			avoid?: string | string[];
		};
	}

	interface Html2PdfWorker {
		set(options: Html2PdfOptions): Html2PdfWorker;
		from(element: HTMLElement | string): Html2PdfWorker;
		save(): Promise<void>;
		output(type: string, options?: unknown): Promise<unknown>;
		toPdf(): Html2PdfWorker;
		get(type: string, cb?: (pdf: unknown) => void): Html2PdfWorker;
	}

	function html2pdf(): Html2PdfWorker;
	function html2pdf(element: HTMLElement, options?: Html2PdfOptions): Html2PdfWorker;

	export default html2pdf;
}
