/**
 * ============================================================================
 * FILE: SettingsPage.tsx
 * LOCATION: client/src/features/settings/SettingsPage.tsx
 * ============================================================================
 *
 * PURPOSE:
 *    Separate, dedicated page for configuring AI Provider settings and selecting
 *    the app's appearance theme.
 *
 * ROLE IN PROJECT:
 *    Enables modular management of API keys and appearance preferences outside of
 *    the main dashboards, offering visual theme selection cards and deep
 *    integration with the local ThemeProvider.
 *
 * KEY COMPONENTS:
 *    - SettingsPage: Main visual preferences container
 *    - Visual Theme Selection Cards: Custom Light, Dark, and System selectors
 *    - OpenRouterSettingsPanel: Integrates collapsible API configuration
 *
 * DEPENDENCIES:
 *    - External: react, react-router-dom, lucide-react, framer-motion
 *    - Internal: @/hooks/useTheme, @/features/settings/OpenRouterSettingsPanel, @/lib/utils
 *
 * USAGE:
 *    import { SettingsPage } from '@/features/settings/SettingsPage';
 *    <Route path="/settings" element={<SettingsPage />} />
 * ============================================================================
 */

import { useState, useCallback } from "react";
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import {
	Sun,
	Moon,
	Monitor,
	Check,
	ChevronDown,
	ArrowLeft,
	MessageCircle,
	Bot,
} from "lucide-react";

import { useTheme } from "@/hooks/useTheme";
import { OpenRouterSettingsPanel } from "./OpenRouterSettingsPanel";
import { WebSearchSettingsPanel } from "./WebSearchSettingsPanel";
import { AgentModelsPanel } from "./AgentModelsPanel";
import { ModelPicker } from "./ModelPicker";
import { getProviderSettings, setProviderConfig } from "@/lib/providerSettings";
import type { AIProvider } from "@/types/provider";
import { cn } from "@/lib/utils";

type SettingsSectionKey =
	| "appearance"
	| "ai-provider"
	| "agent-models"
	| "web-search"
	| "chat-model";

type SettingsSectionProps = {
	headingId: string;
	contentId: string;
	title: ReactNode;
	isExpanded: boolean;
	onToggle: () => void;
	children: ReactNode;
};

function SettingsSection({
	headingId,
	contentId,
	title,
	isExpanded,
	onToggle,
	children,
}: SettingsSectionProps) {
	return (
		<section className="space-y-4" aria-labelledby={headingId}>
			<h2
				id={headingId}
				className="text-lg font-semibold tracking-tight border-b pb-2"
			>
				<button
					type="button"
					aria-expanded={isExpanded}
					aria-controls={contentId}
					onClick={onToggle}
					className={cn(
						"flex w-full items-center justify-between text-left",
						"focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ffb74d]",
					)}
				>
					{title}
					<ChevronDown
						aria-hidden="true"
						className={cn(
							"h-5 w-5 shrink-0 text-muted-foreground transition-transform",
							isExpanded && "rotate-180",
						)}
					/>
				</button>
			</h2>
			<div id={contentId} hidden={!isExpanded}>
				{isExpanded && children}
			</div>
		</section>
	);
}

export function SettingsPage() {
	const { theme, setTheme } = useTheme();
	const [settings, setSettings] = useState(() => getProviderSettings());
	const [expandedSections, setExpandedSections] = useState<
		Record<SettingsSectionKey, boolean>
	>({
		appearance: false,
		"ai-provider": false,
		"agent-models": false,
		"web-search": false,
		"chat-model": false,
	});
	const location = useLocation();

	const fromPath = (location.state as { from?: string })?.from || "/learn";

	const handleChatModelSelect = useCallback(
		(provider: AIProvider, modelId: string, modelTitle: string) => {
			setProviderConfig(settings.activeProvider, {
				chatModel: modelId,
				chatModelTitle: modelTitle,
				chatModelProvider: provider,
			});
			setSettings(getProviderSettings());
		},
		[settings.activeProvider],
	);

	const activeConfig = settings.providers[settings.activeProvider];

	const toggleSection = useCallback((section: SettingsSectionKey) => {
		setExpandedSections((current) => ({
			...current,
			[section]: !current[section],
		}));
	}, []);

	const themes = [
		{
			id: "light" as const,
			name: "Light Mode",
			description: "Clean, high-contrast crisp look.",
			icon: Sun,
			color:
				"text-[#ffb74d] bg-[#ffb74d]/10 dark:text-[#ffb74d]/90 dark:bg-[#ffb74d]/5",
			glow: "shadow-[#ffb74d]/10 hover:border-[#ffb74d]/50",
		},
		{
			id: "dark" as const,
			name: "Dark Mode",
			description: "Sleek, eye-strain-friendly dim vibe.",
			icon: Moon,
			color:
				"text-indigo-400 bg-indigo-400/10 dark:text-indigo-300 dark:bg-indigo-300/5",
			glow: "shadow-indigo-500/10 hover:border-indigo-400/50",
		},
		{
			id: "system" as const,
			name: "System Default",
			description: "Synchronize layout with your OS settings.",
			icon: Monitor,
			color:
				"text-emerald-400 bg-emerald-400/10 dark:text-emerald-300 dark:bg-emerald-300/5",
			glow: "shadow-emerald-500/10 hover:border-emerald-400/50",
		},
	];

	return (
		<div className="min-h-screen bg-background flex flex-col">
			{/* Header */}
			<header className="border-b">
				<div className="max-w-4xl mx-auto px-4 py-3 flex items-center justify-between">
					<Link
						to="/learn"
						className={cn(
							"font-semibold text-lg hover:opacity-80 transition-opacity",
							"focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 rounded-md px-2 py-1",
						)}
					>
						A2UI
					</Link>
					<nav className="flex items-center gap-4" aria-label="Main navigation">
						<Link
							to={fromPath}
							className={cn(
								"flex items-center gap-1.5 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors",
								"focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 rounded-md px-2 py-1",
							)}
						>
							<ArrowLeft className="h-4 w-4" />
							<span>Back to Learn</span>
						</Link>
					</nav>
				</div>
			</header>

			{/* Main content area */}
			<main className="flex-1 max-w-2xl w-full mx-auto px-4 py-12 flex flex-col gap-10">
				<div>
					<h1 className="text-3xl font-extrabold tracking-tight mb-2">
						Settings
					</h1>
					<p className="text-muted-foreground">
						Configure system configurations, API credentials, and appearance
						preferences.
					</p>
				</div>

				{/* Section 1: Appearance & Theme */}
				<SettingsSection
					headingId="appearance-heading"
					contentId="appearance-content"
					title="Appearance"
					isExpanded={expandedSections.appearance}
					onToggle={() => toggleSection("appearance")}
				>
					<div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
						{themes.map((t) => {
							const isSelected = theme === t.id;
							const Icon = t.icon;

							return (
								<motion.button
									key={t.id}
									onClick={() => setTheme(t.id)}
									whileHover={{ scale: 1.02, y: -2 }}
									whileTap={{ scale: 0.98 }}
									transition={{ type: "spring", stiffness: 400, damping: 30 }}
									className={cn(
										"relative text-left p-4 rounded-xl border flex flex-col justify-between transition-all duration-200 shadow-sm cursor-pointer h-full min-h-[140px]",
										"bg-card border-border backdrop-blur-md",
										isSelected
											? "border-[#ffb74d] ring-1 ring-[#ffb74d] shadow-md shadow-[#ffb74d]/5 bg-[#ffb74d]/5"
											: t.glow,
										"focus:outline-none focus-visible:ring-2 focus-visible:ring-[#ffb74d]",
									)}
								>
									<div className="flex items-start justify-between w-full mb-3">
										<div className={cn("p-2 rounded-lg shrink-0", t.color)}>
											<Icon className="h-5 w-5" />
										</div>
										{isSelected && (
											<motion.div
												initial={{ scale: 0 }}
												animate={{ scale: 1 }}
												className="h-5 w-5 rounded-full bg-[#ffb74d] flex items-center justify-center text-black shrink-0"
											>
												<Check className="h-3 w-3 stroke-[3]" />
											</motion.div>
										)}
									</div>
									<div>
										<h3 className="font-semibold text-sm mb-1">{t.name}</h3>
										<p className="text-xs text-muted-foreground leading-normal">
											{t.description}
										</p>
									</div>
								</motion.button>
							);
						})}
					</div>
				</SettingsSection>

				{/* Section 2: AI Provider configurations */}
				<SettingsSection
					headingId="ai-provider-heading"
					contentId="ai-provider-content"
					title="AI Provider Credentials"
					isExpanded={expandedSections["ai-provider"]}
					onToggle={() => toggleSection("ai-provider")}
				>
					<div className="bg-card border border-border p-6 rounded-xl shadow-sm">
						<p className="text-xs text-muted-foreground mb-4">
							Keys are stored in this browser. A2UI sends an AI key only for
							model work and sends search keys only when a web-enabled course
							start or resume requires them.
						</p>
						<OpenRouterSettingsPanel />
					</div>
				</SettingsSection>

				{/* Section 3: Agent Models */}
				<SettingsSection
					headingId="agent-models-heading"
					contentId="agent-models-content"
					title={
						<span className="flex items-center gap-2">
							<Bot aria-hidden="true" className="h-5 w-5 text-[#ffb74d]" />
							Agent Models
						</span>
					}
					isExpanded={expandedSections["agent-models"]}
					onToggle={() => toggleSection("agent-models")}
				>
					<div className="bg-card border border-border p-6 rounded-xl shadow-sm">
						<AgentModelsPanel />
					</div>
				</SettingsSection>

				{/* Section 4: Web Search */}
				<SettingsSection
					headingId="web-search-heading"
					contentId="web-search-content"
					title="Web Search"
					isExpanded={expandedSections["web-search"]}
					onToggle={() => toggleSection("web-search")}
				>
					<div className="bg-card border border-border p-6 rounded-xl shadow-sm">
						<WebSearchSettingsPanel />
					</div>
				</SettingsSection>

				{/* Section 5: Chat Assistant Model */}
				<SettingsSection
					headingId="chat-model-heading"
					contentId="chat-model-content"
					title={
						<span className="flex items-center gap-2">
							<MessageCircle
								aria-hidden="true"
								className="h-5 w-5 text-[#ffb74d]"
							/>
							Chat Assistant Model
						</span>
					}
					isExpanded={expandedSections["chat-model"]}
					onToggle={() => toggleSection("chat-model")}
				>
					<div className="bg-card border border-border p-6 rounded-xl shadow-sm">
						<p className="text-xs text-muted-foreground mb-4">
							Select a separate model for the concept chat assistant. If not
							set, the main generation model is used.
						</p>
						<ModelPicker
							openRouterKey={settings.providers.openrouter.apiKey}
							generalComputeKey={settings.providers.generalcompute.apiKey}
							activeProvider={
								activeConfig.chatModelProvider ?? settings.activeProvider
							}
							activeModel={activeConfig.chatModel ?? ""}
							onSelect={handleChatModelSelect}
						/>
						{activeConfig.chatModelTitle && (
							<p className="text-xs text-muted-foreground mt-2">
								Chat model:{" "}
								<span className="font-medium text-foreground">
									{activeConfig.chatModelTitle}
								</span>
							</p>
						)}
					</div>
				</SettingsSection>
			</main>

			{/* Footer */}
			<footer className="border-t py-4 text-center text-sm text-muted-foreground">
				<p>
					A2UI Settings Panel &mdash; configuration persists in Local Storage
				</p>
			</footer>
		</div>
	);
}
