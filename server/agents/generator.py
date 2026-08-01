"""
============================================================================
FILE: generator.py
LOCATION: server/agents/generator.py
============================================================================
PURPOSE:
    Generator Agent that creates engaging, pedagogically-sound
    educational content for each topic in a learning path.
ROLE IN PROJECT:
    Second agent in the content generation pipeline.
    - Receives TopicNodes from PlannerAgent
    - Produces GeneratedContent consumed by the learning UI
KEY COMPONENTS:
    - GeneratedContent: Pydantic model with content_markdown and takeaways
    - GeneratorAgent: Agent class for generating educational explanations
    - generate_explanation(): Main method with adjacent-topic context
    - generator_agent: Singleton instance for application-wide use
DEPENDENCIES:
    - External: pydantic
    - Internal: server.agents.base, server.schemas.learning
USAGE:
    ```python
    from server.agents.generator import generator_agent
    content = await generator_agent.generate_explanation(
        topic=topic, prev_summary='...', next_summary='...'
    )
    ```
============================================================================
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from server.agents.base import BaseAgent
from server.schemas.learning import TopicNode
from server.schemas.llm import LLMContext
from server.utils.mermaid_validator import validate_mermaid_code


logger = logging.getLogger(__name__)


from server.schemas.generation import (
    GenerationBrief,
    GroundingStatus,
    SourceCitation,
)
from server.services.citation_validation import sanitize_grounded_content


class GeneratedContent(BaseModel):
    """Output model for generated educational content."""

    model_config = ConfigDict(from_attributes=True, extra="allow")

    content_markdown: str = Field(
        ...,
        description="The full educational content in Markdown format",
        min_length=300,
    )
    key_takeaways: List[str] = Field(
        ...,
        description="3-5 key takeaways the learner should remember",
        min_length=3,
        max_length=5,
    )
    thinking_content: Optional[str] = Field(
        default=None,
        description="Thinking/reasoning content from models that support it (e.g., Claude)",
    )
    citations: List[SourceCitation] = Field(
        default_factory=list,
        max_length=20,
        description="Source citations supporting claims in the content",
    )
    warnings: List[str] = Field(
        default_factory=list,
        max_length=20,
        description="Generation or sanitization warnings",
    )


GENERATOR_SYSTEM_PROMPT = """You are an expert educational content creator specializing in engaging, learner-centered explanations.

## Your Role
Your goal is to create concise, targeted explanations that maximize comprehension and retention. You transform abstract concepts into clear, memorable content using analogies, examples, and active learning prompts.

## Content Guidelines

### Depth and Thoroughness
- There is NO word limit. Adjust depth naturally based on topic complexity
- Simple concepts may need 2-3 paragraphs. Complex topics may need multiple pages
- Complex topics require meticulous explanation with trivial, real-world examples
- Use multiple examples and analogies — one example is rarely enough for complex ideas
- Address common misconceptions explicitly — this prevents lingering doubts
- The learner should finish each topic with ZERO remaining confusion
- The goal is expert-level understanding, not surface-level overview

### Pedagogical Framework (5E Model)
Structure your explanations using this proven educational approach (These are phases not titles, use them to guide your explanation):

1. **Engage**: Open with a hook—a relatable scenario, surprising fact, or thought-provoking question
2. **Explore**: Present the core concept with clear examples and analogies
3. **Explain**: Define key terminology and relationships precisely
4. **Elaborate**: Show how this concept connects to prior knowledge or real-world applications
5. **Evaluate**: End with a reflection prompt or check-for-understanding question

### Context Injection for Narrative Coherence
You will receive context about adjacent topics in the learning path:
- **Previous Topic Summary**: Bridge from this concept—assume the learner just finished it
- **Next Topic Summary**: Foreshadow this concept—create anticipation for what's coming

Use these summaries to:
- Reference prior knowledge ("Building on what we learned about...")
- Create smooth transitions ("Now that we understand X, let's explore Y...")
- Plant seeds for upcoming concepts ("This foundation will be essential when we...")

### Scaffolding Principles
- **Build on prior knowledge**: Assume the learner has completed previous topics
- **Start simple, increase complexity**: Lead with intuition before formalism
- **Chunk information**: Break complex ideas into digestible pieces
- **Use concrete before abstract**: Examples first, then generalizations

### Active Learning Integration
- Include **1-2 reflection prompts** within the content (e.g., "Think about...", "Consider why...")
- Pose questions that encourage the learner to pause and think
- Avoid passive consumption—make the learner an active participant

### Markdown Formatting Requirements (IMPORTANT!)
Structure your content for readability:
- Use **headers** (##, ###) to organize sections
- **Bold** key terms when first introduced
- Use *italics* for emphasis on important points
- Create **bulleted lists** for key points or examples
- Keep paragraph structure clean
- Make use of **Mermaid diagrams/flowcharts** (using ```mermaid code blocks) for visual demonstration of complex processes or hierarchies when necessary. IMPORTANT: Always wrap node labels in double quotes if they contain spaces, special characters, or `<br>` line breaks (e.g. `A["Label<br>Detail"]` instead of `A[Label]<br>Detail`). If a node label contains double quotes internally, replace them with single quotes (e.g. `A["Can 'see' context"]` instead of `A["Can "see" context"]`) to avoid syntax parsing errors. DO NOT use style commands with fill colors (e.g., style A fill:#24483f). Just use default Mermaid, no colours.
- Make use of **Vector plots** (using ```vector-plot JSON code blocks) to draw mathematical 2D coordinate graphs for explaining concepts like vector representation, cosine similarity, vector operations, linear algebra, etc. Example structure:
  ```json
  {
    "vectors": [
      {"name": "A", "x": 3, "y": 4, "color": "#ffb74d"},
      {"name": "B", "x": 4, "y": 1, "color": "#4caf50"}
    ],
    "grid": true,
    "xAxisLabel": "x",
    "yAxisLabel": "y"
  }
  ```


### Tone and Voice
- Be **enthusiastic and encouraging**—learning should feel exciting
- Use "you" and "we" to create connection
- Avoid jargon unless defining it as a key term
- Be precise but approachable—like a knowledgeable friend explaining
- Always use easy-to-understand examples and analogies
- Always underestimate user's understanding and over-explain. It is better to be too clear than too confusing.

## Topic Summary and Curiosity Spark

After the main content and key takeaways, end each topic with:

1. **Summary**: A brief recap of what was covered — the 3-5 most important ideas restated concisely. This reinforces learning and gives the learner a quick reference.

2. **Curiosity Spark**: End with 2-3 open-ended, thought-provoking questions that:
   - Connect the topic to the learner's real world
   - Hint at deeper complexities not yet covered
   - Create genuine wonder and desire to explore further
   - These questions should be phrased naturally, as if a curious learner would ask them

Example ending:
> ### Summary
> In this topic, you learned how neural networks adjust weights through backpropagation. The key ideas were: (1) the chain rule enables gradient computation, (2) gradients flow backward from output to input, (3) learning rate controls step size, and (4) vanishing gradients are a real challenge for deep networks.
>
> ### Curious to explore more?
> - How do neural networks decide which weights to adjust first?
> - What happens when a network gets stuck in a local minimum?
> - Can backpropagation work with non-differentiable functions?

## Key Takeaways Generation
After generating content, extract **3-5 key takeaways**:
- Each should be a single, memorable sentence
- Focus on the most important concepts
- These serve as quick review points for the learner

## Example Content Structure

```markdown
## [Topic Title]

[Hook: Engaging opening question or scenario]

### Understanding [Core Concept]

[Clear explanation with analogy or example]

**Key Term**: [Definition]

[Deeper exploration with examples]

> Think about: [Reflection prompt]

### Connecting the Dots

[How this relates to previous/next topics]

### Key Points

- [Bullet point 1]
- [Bullet point 2]
- [Bullet point 3]

### Summary
[Brief recap of the 3-5 most important ideas from this topic]

### Curious to explore more?
- [Open-ended question 1 that sparks deeper interest]
- [Open-ended question 2 connecting to real-world applications]
- [Open-ended question 3 hinting at advanced concepts]
```

Remember: Your content will be read by learners eager to understand. Leave them feeling like an expert on this topic — with zero remaining doubts and genuine curiosity to explore further."""


class GeneratorAgent(BaseAgent):
    """
    Generator Agent for creating educational content with context injection.

    Produces engaging, pedagogically-sound explanations for each topic in a
    learning path. Uses context from adjacent topics (prev_summary, next_summary)
    to maintain narrative coherence throughout the course.

    The Generator is the second agent in the pipeline. It receives TopicNodes
    from the Planner and produces GeneratedContent for display to learners.
    """

    def __init__(self) -> None:
        """Initialize the GeneratorAgent with the 'generator' role."""
        super().__init__(role="generator")
        logger.debug("GeneratorAgent initialized")

    @property
    def system_prompt(self) -> str:
        """
        Return the system prompt for the Generator Agent.

        The prompt defines the agent's role as an educational content creator,
        specifies formatting requirements, and provides pedagogical guidelines.

        Returns:
            The GENERATOR_SYSTEM_PROMPT constant
        """
        return GENERATOR_SYSTEM_PROMPT

    async def generate_explanation(
        self,
        topic: TopicNode,
        brief: Optional[GenerationBrief] = None,
        prev_summary: Optional[str] = None,
        next_summary: Optional[str] = None,
        llm_context: Optional[LLMContext] = None,
    ) -> GeneratedContent:
        """
        Generate educational content for a topic with context injection.

        Injects context from adjacent topics and generation brief to maintain
        narrative coherence across the learning path.

        Args:
            topic: The TopicNode to generate content for
            brief: Optional GenerationBrief specifying detailed requirements
            prev_summary: Summary of the previous topic (None if first topic)
            next_summary: Summary of the next topic (None if last topic)
            llm_context: Optional OpenRouter context

        Returns:
            GeneratedContent containing content_markdown and key_takeaways

        Raises:
            Exception: If generation fails after retries
        """
        user_message = self._build_user_message(
            topic, brief, prev_summary, next_summary
        )

        logger.info(
            f"GeneratorAgent generating content for topic {topic.index}: "
            f"'{topic.title}'"
        )

        approved_source_ids = brief.approved_source_ids if brief else set()

        max_attempts = 3
        current_attempt = 1
        last_error = None
        active_user_message = user_message

        while current_attempt <= max_attempts:
            content = await self.generate(
                response_model=GeneratedContent,
                user_message=active_user_message,
                llm_context=llm_context,
            )

            # Check Mermaid syntax
            mermaid_blocks = re.findall(
                r"```mermaid\s*\n(.*?)\n```", content.content_markdown, re.DOTALL
            )
            invalid_block_err = None
            for idx, block in enumerate(mermaid_blocks):
                err = validate_mermaid_code(block)
                if err:
                    invalid_block_err = f"Mermaid Block #{idx + 1} is invalid: {err}"
                    break

            if invalid_block_err:
                logger.warning(
                    f"GeneratorAgent attempt {current_attempt} generated invalid Mermaid syntax: {invalid_block_err}"
                )
                active_user_message = (
                    f"{user_message}\n\n"
                    f"--- RETRY FEEDBACK (ATTEMPT {current_attempt}/{max_attempts}) ---\n"
                    f"Your previous response had a Mermaid diagram rendering/parsing error:\n"
                    f"{invalid_block_err}\n\n"
                    f"Please correct the Mermaid diagram syntax and regenerate."
                )
                last_error = invalid_block_err
                current_attempt += 1
                continue

            # Check citations against approved_source_ids & web links
            invalid_citations = [
                cite for cite in content.citations if cite.source_id not in approved_source_ids
            ]
            has_web_links = bool(re.search(r"https?://\S+", content.content_markdown))

            if (invalid_citations or has_web_links) and current_attempt == 1:
                logger.warning(
                    "GeneratorAgent generated unapproved citations/links on attempt 1. Requesting correction."
                )
                active_user_message = (
                    f"{user_message}\n\n"
                    f"--- RETRY FEEDBACK (ATTEMPT {current_attempt}/{max_attempts}) ---\n"
                    f"Your response included unsupported citations or web URLs.\n"
                    f"Approved source IDs: {sorted(list(approved_source_ids))}\n"
                    f"You MUST NOT include raw HTTP/HTTPS URLs. Return citations as SourceCitation objects using ONLY approved source IDs.\n"
                )
                current_attempt += 1
                continue

            # If still invalid or attempt > 1, sanitize and proceed
            cleaned_markdown, valid_citations, warnings = sanitize_grounded_content(
                markdown=content.content_markdown,
                citations=content.citations,
                approved_source_ids=approved_source_ids,
            )

            all_warnings = list(content.warnings)
            for w in warnings:
                if w not in all_warnings:
                    all_warnings.append(w)

            return content.model_copy(
                update={
                    "content_markdown": cleaned_markdown,
                    "citations": valid_citations,
                    "warnings": all_warnings,
                }
            )

        logger.error(
            f"GeneratorAgent failed after {max_attempts} attempts. Last error: {last_error}"
        )
        return content

    def _build_user_message(
        self,
        topic: TopicNode,
        brief: Optional[GenerationBrief],
        prev_summary: Optional[str],
        next_summary: Optional[str],
    ) -> str:
        """Build user message with topic, brief, and adjacent context."""
        parts = [
            f"Create educational content for the following topic:\n",
            f"## Topic: {topic.title}",
            f"**Summary**: {topic.summary_for_context}",
            f"**Key Terms to Emphasize**: {', '.join(topic.key_terms)}",
        ]

        if brief:
            parts.append("\n## Generation Brief")
            parts.append(f"- **Scope**: {brief.topic_scope}")
            parts.append(f"- **Objectives**: {', '.join(brief.learning_objectives)}")
            parts.append(f"- **Pedagogical Guidance**: {brief.pedagogical_guidance}")
            if brief.source_excerpts:
                parts.append("\n### Approved Research Source Excerpts")
                parts.append("<UNTRUSTED_RESEARCH_EXCERPTS>")
                for exc in brief.source_excerpts:
                    parts.append(f"Source [{exc.source_id}]: {exc.excerpt}")
                parts.append("</UNTRUSTED_RESEARCH_EXCERPTS>")
                parts.append(
                    f"Citations MUST use source_id values from approved list: {sorted(list(brief.approved_source_ids))}. Do NOT invent URLs or links."
                )

        # Context injection section
        parts.append("\n## Adjacent Topic Context")

        if prev_summary:
            parts.append(
                f"\n**Previous Topic Summary**: {prev_summary}\n"
                f"- Bridge this explanation from the previous topic\n"
                f"- Assume the learner just completed this content"
            )
        else:
            parts.append(
                "\n**Previous Topic**: None (this is the first topic)\n"
                "- This is the learner's entry point\n"
                "- Provide foundational context and motivate the learning journey"
            )

        if next_summary:
            parts.append(
                f"\n**Next Topic Summary**: {next_summary}\n"
                f"- Foreshadow the next topic in your closing\n"
                f"- Create anticipation for what's coming next"
            )
        else:
            parts.append(
                "\n**Next Topic**: None (this is the final topic)\n"
                "- This is the concluding topic\n"
                "- Synthesize the learning journey and celebrate completion"
            )

        parts.append(
            "\n## Requirements"
            "\n- Target 300-500 words (2-3 minutes reading time)"
            "\n- Use the 5E pedagogical model"
            "\n- Include 1-2 reflection prompts"
            "\n- Bold all key terms"
            "\n- Extract 3-5 key takeaways"
        )

        return "\n".join(parts)


# Singleton instance for use throughout the application
generator_agent = GeneratorAgent()
