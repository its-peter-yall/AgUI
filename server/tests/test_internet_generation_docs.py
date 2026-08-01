"""
============================================================================
FILE: test_internet_generation_docs.py
LOCATION: server/tests/test_internet_generation_docs.py
============================================================================
PURPOSE:
    Guards user and operator documentation for optional Internet grounding.
ROLE IN PROJECT:
    Prevents release without setup, security, recovery, and limit guidance.
KEY COMPONENTS:
    - InternetGenerationDocumentationTests: Required documentation contract
DEPENDENCIES:
    - External: pathlib, unittest
    - Internal: README and operations runbook
USAGE:
    python -m unittest server.tests.test_internet_generation_docs -v
============================================================================
"""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
OPERATIONS = (
    ROOT
    / "docs"
    / "internet-grounded-course-generation"
    / "operations.md"
)


class InternetGenerationDocumentationTests(unittest.TestCase):
    """Tests required web-grounding documentation content."""

    def test_readme_documents_optional_progressive_generation(self) -> None:
        text = README.read_text(encoding="utf-8")
        required = [
            "Optional Internet Grounding",
            "defaults OFF",
            "Tavily",
            "Exa",
            "Brave Search",
            "SerpAPI",
            "POST /learning/generate",
            "202",
            "GET /learning/sessions/{id}/events",
            "POST /learning/sessions/{id}/resume",
        ]
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, text)

    def test_operations_runbook_covers_security_recovery_and_limits(self) -> None:
        text = OPERATIONS.read_text(encoding="utf-8")
        required_headings = [
            "## Provider Configuration",
            "## Generation Stages",
            "## Secret Boundary",
            "## Cancellation and Resume",
            "## Restart Recovery",
            "## SSE and Polling",
            "## Research Limits",
            "## Troubleshooting",
            "## Verification Commands",
        ]
        for heading in required_headings:
            with self.subTest(heading=heading):
                self.assertIn(heading, text)
        self.assertIn("Keys are stored only in browser localStorage", text)
        self.assertIn("Keys are sent only on generate and resume", text)
        self.assertIn("Cancelled work remains available", text)
        self.assertIn("server\\.venv\\Scripts\\python.exe -m unittest", text)
        self.assertIn("npm run test:generation:coverage", text)


if __name__ == "__main__":
    unittest.main()
