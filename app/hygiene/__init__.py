"""GearGraph Data Hygiene System.

A continuous, AI-agent-based system that scans the database for data quality
issues, auto-fixes low-risk problems, queues high-risk fixes for human approval,
and learns from feedback to improve over time.

Modules:
- issues: Issue type definitions and data classes
- scanner: Scans database for quality issues
- auto_fixer: Applies low-risk fixes automatically
- approval_queue: Manages high-risk fixes awaiting approval
- learning: Tracks corrections, builds patterns, adjusts thresholds
- copyright_detector: Compares descriptions to manufacturer pages
- rewriter: AI-powered marketing copy to neutral language
- metrics: Tracks hygiene progress and learning accuracy
"""

from app.hygiene.issues import (
    IssueType,
    RiskLevel,
    FixType,
    HygieneIssue,
    Fix,
    CorrectionRecord,
    CorrectionPattern,
)

__all__ = [
    "IssueType",
    "RiskLevel",
    "FixType",
    "HygieneIssue",
    "Fix",
    "CorrectionRecord",
    "CorrectionPattern",
]
