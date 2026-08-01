"""
============================================================================
FILE: agents/__init__.py
LOCATION: server/agents/__init__.py
============================================================================
PURPOSE:
    Package initialization and exports for the agents module.
    Provides a clean public API for the three-agent pipeline.
ROLE IN PROJECT:
    Entry point for the agent pipeline (Plan -> Generate -> Quiz).
    - Exports all agent classes and singleton instances
    - Consumed by the LangGraph course graph to drive content generation
KEY COMPONENTS:
    - BaseAgent: Abstract base class for all agent implementations
    - PlannerAgent / planner_agent: Decomposes queries into outlines
    - GeneratorAgent / generator_agent: Creates educational content
    - QuizzerAgent / quizzer_agent: Generates assessment questions
    - GeneratedContent: Pydantic model for Generator output
DEPENDENCIES:
    - External: None
    - Internal: server.agents.base, server.agents.planner,
      server.agents.generator, server.agents.quizzer
USAGE:
    ```python
    from server.agents import planner_agent, generator_agent, quizzer_agent
    outline = await planner_agent.plan('Python Basics')
    ```
============================================================================
"""

from server.agents.base import BaseAgent
from server.agents.generator import GeneratedContent, GeneratorAgent, generator_agent
from server.agents.planner import PlannerAgent, planner_agent
from server.agents.quizzer import QuizzerAgent, quizzer_agent
from server.agents.researcher import ResearcherAgent, researcher_agent

__all__ = [
    "BaseAgent",
    "GeneratedContent",
    "GeneratorAgent",
    "generator_agent",
    "PlannerAgent",
    "planner_agent",
    "QuizzerAgent",
    "quizzer_agent",
    "ResearcherAgent",
    "researcher_agent",
]
