"""
============================================================================
FILE: __init__.py
LOCATION: server/schemas/__init__.py
============================================================================
PURPOSE:
    Public API surface for the A2UI schema models module. Exports commonly
    used schemas and mixins for consumption by routers, services, and
    external modules.
ROLE IN PROJECT:
    Aggregates schema exports into a single importable namespace.
    - Exposes ResponseBase and TimestampMixin for reuse across the server
    - Provides a stable public contract for all learning domain schemas
KEY COMPONENTS:
    - ResponseBase: Base class providing id field for all resource responses
    - TimestampMixin: Adds created_at and updated_at datetime fields
    - NodeStatus, QuizCard, CourseOutline: Core learning domain schemas
    - ConceptNodeResponse, LearningSessionResponse: API response models
DEPENDENCIES:
    - External: None
    - Internal: server.schemas.common, server.schemas.learning
USAGE:
    ```python
    from server.schemas import ResponseBase, NodeStatus, ConceptNodeResponse
    ```
============================================================================
"""

from server.schemas.common import ResponseBase, TimestampMixin
from server.schemas.generation import (
    BriefSourceExcerpt,
    GenerationBrief,
    GenerationBriefBatch,
    GenerationCounts,
    GenerationCursor,
    GenerationStage,
    GenerationWarning,
    GroundingStatus,
    ResearchCursor,
    SourceCitation,
)
from server.schemas.learning import (
    NodeStatus,
    QuizDifficulty,
    QuizOption,
    QuizCard,
    TopicNode,
    CourseOutline,
    ConceptNodeBase,
    ConceptNodeCreate,
    ConceptNodeResponse,
    LearningSessionBase,
    LearningSessionCreate,
    LearningSessionResponse,
    RevisionMode,
    RevisionCreateRequest,
    RevisionSessionResponse,
    RevisionNodeProgress,
    RevisionNodeProgressWithDetails,
    RevisionSessionWithProgress,
    QuizSubmission,
    QuizResult,
    QuizAttemptBase,
    QuizAttemptCreate,
    QuizAttemptResponse,
    QuizAttemptHistory,
)
