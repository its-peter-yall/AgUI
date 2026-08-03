"""
============================================================================
FILE: bundle.py
LOCATION: server/database/repositories/bundle.py
============================================================================
PURPOSE:
    Typed aggregate of all repository ports swapped as one value.
ROLE IN PROJECT:
    StorageContext holds one RepositoryBundle per backend; never swaps
    individual repositories independently.
DEPENDENCIES:
    - External: dataclasses
    - Internal: server.database.repositories.protocols
USAGE:
    from server.database.repositories.bundle import RepositoryBundle
============================================================================
"""

from __future__ import annotations

from dataclasses import dataclass

from server.database.repositories.protocols import (
    AppSettingsRepository,
    GenerationArtifactRepository,
    GenerationJobRepository,
    LearningRepository,
    ProgressEventRepository,
    ResearchRepository,
)


@dataclass(frozen=True)
class RepositoryBundle:
    """Complete backend implementation swapped as one value."""

    learning: LearningRepository
    jobs: GenerationJobRepository
    artifacts: GenerationArtifactRepository
    research: ResearchRepository
    progress: ProgressEventRepository
    app_settings: AppSettingsRepository
