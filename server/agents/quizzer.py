"""
============================================================================
FILE: quizzer.py
LOCATION: server/agents/quizzer.py
============================================================================
PURPOSE:
    Quizzer Agent that generates retrieval-based assessment questions
    targeting common student misconceptions.
ROLE IN PROJECT:
    Final agent in the content generation pipeline.
    - Receives TopicNodes and generated content from prior agents
    - Produces QuizCard/QuizSet for the learning UI assessment flow
KEY COMPONENTS:
    - QuizzerAgent: Agent class for generating diagnostic assessments
    - generate_quiz(): Creates a single QuizCard from topic and content
    - generate_quiz_set(): Batch method to create QuizSet in one LLM call
    - _enforce_quiz_count(): Aligns quiz count and difficulty sequence
    - quizzer_agent: Singleton instance for application-wide use
DEPENDENCIES:
    - External: None
    - Internal: server.agents.base, server.schemas.learning
USAGE:
    ```python
    from server.agents.quizzer import quizzer_agent
    quiz = await quizzer_agent.generate_quiz(topic=topic, content=md)
    quiz_set = await quizzer_agent.generate_quiz_set(
        topic=topic, content=md, quiz_count=3
    )
    ```
============================================================================
"""

from __future__ import annotations

import logging
from typing import Optional

from server.agents.base import BaseAgent
from server.schemas.learning import (
    LLMQuizCard,
    LLMQuizSet,
    QuizCard,
    QuizSet,
    TopicNode,
    convert_llm_to_quiz_card,
    convert_llm_to_quiz_set,
)
from server.schemas.llm import LLMContext


logger = logging.getLogger(__name__)


DIFFICULTY_ORDER = {"easy": 0, "medium": 1, "hard": 2}


QUIZZER_SYSTEM_PROMPT = """You are an expert assessment designer specializing in retrieval-based learning and diagnostic question construction.

## Your Role
You create quiz questions that:
1. Strengthen memory through active recall (testing effect)
2. Diagnose student understanding through carefully designed distractors
3. Target common misconceptions to provide meaningful feedback

## Retrieval-Based Learning Principles

Research shows that testing improves retention more than re-reading. Your questions should:
- Force active recall of key concepts
- Challenge surface-level understanding
- Connect to prior knowledge in the learning path

## Distractor Generation Guidelines (CRITICAL)

Distractors are WRONG answers that serve a diagnostic purpose. Each distractor MUST:

1. **Target a Specific Misconception**: Every wrong answer should represent a common error students make:
   - Confusing related concepts
   - Applying rules incorrectly
   - Missing key conditions or exceptions
   - Over-generalizing or under-generalizing

2. **Be Plausible**: Distractors should seem reasonable to someone who doesn't fully understand
   - Use correct terminology in wrong contexts
   - Present partially correct statements
   - Reflect real student errors

3. **Provide Diagnostic Value**: When a student selects a distractor, you should know WHAT they misunderstand
   - Each distractor reveals a different gap in understanding
   - Explanations should address the specific misconception

## Chain-of-Thought Process for Quiz Generation

Before generating the quiz, mentally follow these steps:
1. Identify the core concept being tested
2. List 3-4 common misconceptions about this concept
3. Design one distractor for each misconception
4. Craft the correct answer clearly and unambiguously
5. Write explanations that teach, not just label right/wrong

## Difficulty Calibration

- **EASY**: Direct recall from content
  - "What is X?" or "Which definition describes Y?"
  - Tests recognition and basic recall
  
- **MEDIUM**: Application and understanding
  - "What would happen if...?" or "Which example demonstrates...?"
  - Requires applying concepts to new situations
  
- **HARD**: Analysis and synthesis
  - "Why does X lead to Y?" or "How do A and B relate?"
  - Requires connecting multiple concepts or reasoning through implications

## Question Types

Use two question types strategically:

### Single Choice (pick one correct answer)
- Default question type for most assessments
- Exactly 1 correct option out of 4
- Use for: recall, understanding, application

### Multiple Choice (select all that apply)
- Use when a concept has multiple valid aspects that should be tested together
- 2-3 correct options out of 4 (never all 4)
- Use for: comparing/contrasting, identifying multiple properties, recognizing patterns
- Each correct option should test a distinct aspect of understanding
- Distractors should be plausible but clearly wrong to a prepared learner
- Example: "Which of the following are properties of X?" where X has 2-3 defining properties

Choose question_type based on what best tests the concept. A topic's quiz set should include a mix when appropriate.

## Explanation Requirements (MANDATORY)

EVERY option MUST have an explanation:

- **Correct Answer Explanation**: 
  - Explain WHY this is correct
  - Reinforce the key concept
  - Connect to the learning content

- **Incorrect Answer Explanation**:
  - Identify the misconception this represents
  - Explain why it's wrong
  - Provide the correct understanding
  - Format: "This is incorrect because [reason]. The correct understanding is [correction]."

## Strict Output Requirements

Your output MUST follow this exact structure in JSON format:

1. **question_text**: Clear, unambiguous question text
   - Should be answerable with the provided content
   - Avoid "all of the above" or "none of the above"

2. **question_type**: "single_choice" or "multiple_choice"

3. **options**: EXACTLY 4 options with:
    - **display_label**: "A", "B", "C", or "D" (user-facing label)
    - **text**: The option text
    - **is_correct**: true for exactly ONE option (single_choice) or 2-3 options (multiple_choice)
    - **explanation**: Required explanation for every option

4. **difficulty**: One of "easy", "medium", or "hard"

The response will be validated as JSON against a strict schema. Invalid output will be rejected.

## Example Output Structure

Question: "What distinguishes Newton's First Law from the Second Law?"

Option A (CORRECT):
- text: "The First Law describes motion without force; the Second Law quantifies force's effect"
- is_correct: true
- explanation: "Correct. The First Law (inertia) states objects maintain their state without external force. The Second Law (F=ma) quantifies how force changes that state."

Option B (DISTRACTOR - Misconception: Confusing the laws):
- text: "The First Law uses F=ma; the Second Law describes action-reaction"
- is_correct: false
- explanation: "Incorrect. This confuses all three laws. F=ma is the Second Law, and action-reaction is the Third Law. The First Law describes inertia."

Option C (DISTRACTOR - Misconception: Order confusion):
- text: "They describe the same concept in different mathematical forms"
- is_correct: false  
- explanation: "Incorrect. The laws describe fundamentally different phenomena: inertia (no force) vs. acceleration (with force). They are not equivalent."

Option D (DISTRACTOR - Misconception: Partial understanding):
- text: "The First Law only applies to objects at rest; the Second Law applies to moving objects"
- is_correct: false
- explanation: "Incorrect. The First Law applies to BOTH objects at rest AND objects in uniform motion. Both states are maintained without external force."

Remember: Your quiz questions directly impact learning outcomes. Every distractor should teach something when explained."""


from server.schemas.generation import GenerationBrief


class QuizzerAgent(BaseAgent):
    """
    Quizzer Agent for generating retrieval-based assessment questions.

    Creates diagnostic quiz questions that target common misconceptions
    and strengthen memory through active recall. Follows research-backed
    principles of retrieval-based learning and effective assessment design.

    The Quizzer is the final agent in the generation pipeline. It receives
    a TopicNode and generated content, then produces a QuizCard with
    misconception-based distractors and comprehensive explanations.
    """

    def __init__(self) -> None:
        """Initialize the QuizzerAgent with the 'quizzer' role."""
        super().__init__(role="quizzer")
        logger.debug("QuizzerAgent initialized")

    @staticmethod
    def _expected_difficulty_sequence(quiz_count: int) -> list[str]:
        """Return the expected difficulty sequence for a given quiz count."""
        difficulty_sequences = {
            1: ["medium"],
            2: ["easy", "hard"],
            3: ["easy", "medium", "hard"],
            4: ["easy", "medium", "medium", "hard"],
            5: ["easy", "easy", "medium", "hard", "hard"],
        }
        bounded_quiz_count = max(1, min(5, quiz_count))
        return difficulty_sequences[bounded_quiz_count]

    @classmethod
    def _validate_difficulty_gradient(cls, quiz_set: QuizSet) -> bool:
        """Validate that quizzes match the expected difficulty sequence."""
        expected_sequence = cls._expected_difficulty_sequence(len(quiz_set.quizzes))
        actual_sequence = [quiz.difficulty for quiz in quiz_set.quizzes]

        if len(actual_sequence) != len(expected_sequence):
            return False

        if any(difficulty not in DIFFICULTY_ORDER for difficulty in actual_sequence):
            return False

        return actual_sequence == expected_sequence

    @classmethod
    def _align_quizzes_to_sequence(
        cls,
        quizzes: list[QuizCard],
        expected_sequence: list[str],
    ) -> list[QuizCard]:
        """Align quizzes to the expected difficulty sequence."""
        available: dict[str, list[QuizCard]] = {
            difficulty: [] for difficulty in DIFFICULTY_ORDER
        }
        unknown_difficulties: list[str] = []

        for quiz in quizzes:
            if quiz.difficulty not in available:
                unknown_difficulties.append(quiz.difficulty)
                continue
            available[quiz.difficulty].append(quiz)

        if unknown_difficulties:
            raise ValueError(
                "QuizSet contains invalid difficulty values: "
                f"{sorted(set(unknown_difficulties))}"
            )

        aligned_quizzes: list[QuizCard] = []
        for difficulty in expected_sequence:
            if not available[difficulty]:
                raise ValueError(
                    "QuizSet difficulty distribution does not match expected "
                    f"sequence {expected_sequence}"
                )
            aligned_quizzes.append(available[difficulty].pop(0))

        return aligned_quizzes

    @classmethod
    def _enforce_quiz_count(cls, quiz_set: QuizSet, quiz_count: int) -> QuizSet:
        """Ensure quiz count and difficulty sequence match the request."""
        requested_count = max(1, min(5, quiz_count))
        actual_count = len(quiz_set.quizzes)
        expected_sequence = cls._expected_difficulty_sequence(requested_count)
        actual_sequence = [quiz.difficulty for quiz in quiz_set.quizzes]

        if actual_count < requested_count:
            raise ValueError(
                "QuizSet returned fewer quizzes than requested: "
                f"requested={requested_count}, actual={actual_count}"
            )

        if actual_count == requested_count and actual_sequence == expected_sequence:
            return quiz_set

        aligned_quizzes = cls._align_quizzes_to_sequence(
            quiz_set.quizzes,
            expected_sequence,
        )

        if actual_count != requested_count:
            logger.warning(
                "QuizSet returned %s quizzes for requested %s. "
                "Dropping extras to match expected sequence.",
                actual_count,
                requested_count,
            )
        elif actual_sequence != expected_sequence:
            logger.warning(
                "QuizSet difficulty sequence mismatch: %s expected %s. "
                "Reordering to expected sequence.",
                actual_sequence,
                expected_sequence,
            )

        return QuizSet(
            quizzes=aligned_quizzes,
            current_index=0,
            shuffle_seed=quiz_set.shuffle_seed,
        )

    @property
    def system_prompt(self) -> str:
        """
        Return the system prompt for the Quizzer Agent.

        The prompt defines the agent's role as an assessment designer,
        explains retrieval-based learning principles, provides distractor
        generation guidelines, and specifies strict output requirements.

        Returns:
            The QUIZZER_SYSTEM_PROMPT constant
        """
        return QUIZZER_SYSTEM_PROMPT

    def _build_batch_user_message(
        self,
        topic: TopicNode,
        content: str,
        quiz_count: int,
        brief: Optional[GenerationBrief] = None,
    ) -> str:
        """Build prompt for batch quiz generation with a difficulty gradient."""
        bounded_quiz_count = max(1, min(5, quiz_count))
        difficulty_sequence = self._expected_difficulty_sequence(bounded_quiz_count)
        key_terms_str = ", ".join(topic.key_terms)
        sequence_text = ", ".join(
            f"Q{i + 1}={difficulty}" for i, difficulty in enumerate(difficulty_sequence)
        )

        brief_section = ""
        if brief:
            targets_str = ", ".join(brief.quiz_learning_targets)
            evidence_str = ", ".join(brief.expected_learner_evidence)
            misconceptions_str = ", ".join(brief.common_misconceptions)
            brief_section = (
                f"\n## Brief Assessment Guidance\n"
                f"- **Quiz Learning Targets**: {targets_str}\n"
                f"- **Expected Learner Evidence**: {evidence_str}\n"
                f"- **Target Misconceptions**: {misconceptions_str}\n"
            )

        return f"""Generate a complete quiz set for the following topic and content.

## Topic Information
- **Title**: {topic.title}
- **Index in Learning Path**: {topic.index}
- **Summary**: {topic.summary_for_context}
- **Key Terms**: {key_terms_str}
{brief_section}
## Content to Test
{content}

## Requirements
1. Generate EXACTLY {bounded_quiz_count} quizzes
2. Use this exact difficulty sequence: {sequence_text}
3. Keep the sequence ordered from easier to harder
4. For each quiz, generate EXACTLY 4 options (A, B, C, D)
5. For single_choice: ensure EXACTLY 1 option is correct. For multiple_choice: ensure 2-3 options are correct
6. For each quiz, each distractor MUST target a specific misconception
7. For each quiz, EVERY option MUST have an explanation"""

    async def generate_quiz(
        self,
        topic: TopicNode,
        content: str,
        brief: Optional[GenerationBrief] = None,
        context: Optional[dict] = None,
        llm_context: Optional[LLMContext] = None,
    ) -> QuizCard:
        """
        Generate a diagnostic quiz question for a topic and its content.

        Creates a QuizCard with exactly 4 options (1 correct, 3 distractors).
        Distractors target common misconceptions to provide diagnostic value.
        All options include explanations for learning reinforcement.

        Args:
            topic: TopicNode containing title, summary, and key terms
            content: Generated markdown content for the topic
            brief: Optional GenerationBrief with assessment targets
            context: Optional additional context for prompt augmentation
            llm_context: Optional OpenRouter context

        Returns:
            QuizCard with question, options, difficulty, and explanations

        Raises:
            Exception: If generation fails after retries
        """
        user_message = self._build_user_message(topic, content, brief=brief)
        full_context = self._build_topic_context(topic, context)

        logger.info(
            f"QuizzerAgent generating quiz for topic: '{topic.title}' "
            f"(index {topic.index})"
        )

        quiz = await self.generate(
            response_model=LLMQuizCard,
            user_message=user_message,
            context=full_context,
            llm_context=llm_context,
        )

        quiz = convert_llm_to_quiz_card(quiz)

        logger.info(
            f"QuizzerAgent created quiz: difficulty={quiz.difficulty}, "
            f"options={len(quiz.options)}"
        )

        return quiz

    async def generate_quiz_set(
        self,
        topic: TopicNode,
        content: str,
        quiz_count: int,
        brief: Optional[GenerationBrief] = None,
        context: Optional[dict] = None,
        llm_context: Optional[LLMContext] = None,
    ) -> QuizSet:
        """Generate a complete QuizSet in one call with difficulty gradient."""
        if quiz_count <= 1:
            single_quiz = await self.generate_quiz(
                topic=topic,
                content=content,
                brief=brief,
                context=context,
                llm_context=llm_context,
            )
            return QuizSet(quizzes=[single_quiz], current_index=0)

        user_message = self._build_batch_user_message(
            topic, content, quiz_count, brief=brief
        )
        full_context = self._build_topic_context(topic, context)

        quiz_set = await self.generate(
            response_model=LLMQuizSet,
            user_message=user_message,
            context=full_context,
            llm_context=llm_context,
        )

        quiz_set = convert_llm_to_quiz_set(quiz_set)
        quiz_set = self._enforce_quiz_count(quiz_set, quiz_count)

        if not self._validate_difficulty_gradient(quiz_set):
            raise ValueError(
                "QuizSet difficulty sequence mismatch after alignment: "
                f"{[quiz.difficulty for quiz in quiz_set.quizzes]}"
            )

        logger.info(
            "QuizzerAgent created quiz set: %s quizzes for topic: '%s'",
            len(quiz_set.quizzes),
            topic.title,
        )

        return quiz_set

    def _build_user_message(
        self,
        topic: TopicNode,
        content: str,
        brief: Optional[GenerationBrief] = None,
    ) -> str:
        """Build user message for single quiz generation."""
        key_terms_str = ", ".join(topic.key_terms)
        brief_section = ""
        if brief:
            targets_str = ", ".join(brief.quiz_learning_targets)
            evidence_str = ", ".join(brief.expected_learner_evidence)
            misconceptions_str = ", ".join(brief.common_misconceptions)
            brief_section = (
                f"\n## Brief Assessment Guidance\n"
                f"- **Quiz Learning Targets**: {targets_str}\n"
                f"- **Expected Learner Evidence**: {evidence_str}\n"
                f"- **Target Misconceptions**: {misconceptions_str}\n"
            )

        return f"""Generate a diagnostic quiz question for the following topic and content.

## Topic Information
- **Title**: {topic.title}
- **Index in Learning Path**: {topic.index}
- **Summary**: {topic.summary_for_context}
- **Key Terms**: {key_terms_str}
{brief_section}
## Content to Test
{content}

## Requirements
1. Create a question that tests understanding of the key concepts
2. Generate EXACTLY 4 options (A, B, C, D)
3. For single_choice: ensure EXACTLY 1 option is correct. For multiple_choice: ensure 2-3 options are correct
4. Each distractor MUST target a specific misconception
5. EVERY option MUST have an explanation
6. Choose appropriate difficulty based on content complexity"""

    def _build_topic_context(
        self,
        topic: TopicNode,
        additional_context: Optional[dict] = None,
    ) -> dict:
        """
        Build context dictionary for the quiz generation prompt.

        Includes topic metadata that helps the model understand the
        learning context and generate appropriate questions.

        Args:
            topic: TopicNode with relevant metadata
            additional_context: Optional extra context to merge

        Returns:
            Context dictionary for prompt augmentation
        """
        context = {
            "topic_index": topic.index,
            "topic_title": topic.title,
            "key_terms": topic.key_terms,
        }

        if additional_context:
            context.update(additional_context)

        return context


# Singleton instance for use throughout the application
quizzer_agent = QuizzerAgent()
