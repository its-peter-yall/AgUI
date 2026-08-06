import { MessageCircleQuestionMark } from "lucide-react";
import { InlineMarkdown } from "./MarkdownRenderer";

interface CuriositySparkProps {
	questions: string[];
	onAskQuestion: (question: string) => void;
}

export function CuriositySpark({ questions, onAskQuestion }: CuriositySparkProps) {
	if (questions.length === 0) return null;
	return (
		<div className="curiosity-spark mt-6 p-4 rounded-lg border border-primary/20 bg-primary/5">
			<div className="flex items-center gap-2 mb-3">
				<MessageCircleQuestionMark className="w-4 h-4 text-primary" />
				<h4 className="text-sm font-semibold text-primary">
					Curious to explore more?
				</h4>
			</div>
			<p className="text-xs text-muted-foreground mb-3">
				Click any question to ask the chatbot and dive deeper:
			</p>
			<ul className="space-y-2">
				{questions.map((q, i) => (
					<li key={i}>
						<button
							type="button"
							onClick={() => onAskQuestion(q)}
							className="w-full text-left px-3 py-2 rounded-md border border-muted bg-card hover:border-primary hover:bg-primary/10 transition-colors text-sm group flex items-start gap-2"
						>
							<MessageCircleQuestionMark className="w-3.5 h-3.5 mt-0.5 text-muted-foreground group-hover:text-primary shrink-0" />
							<span className="text-foreground group-hover:text-primary transition-colors">
								<InlineMarkdown content={q} />
							</span>
						</button>
					</li>
				))}
			</ul>
		</div>
	);
}
