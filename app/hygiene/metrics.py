"""Metrics collection and reporting for the hygiene system."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.hygiene.issues import IssueType, RiskLevel


@dataclass
class HygieneMetrics:
    """Metrics for the hygiene system."""

    # Issue counts
    total_issues_detected: int = 0
    issues_by_type: dict[str, int] = field(default_factory=dict)
    issues_by_risk: dict[str, int] = field(default_factory=dict)

    # Fix rates
    auto_fixed_count: int = 0
    pending_approval_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0

    # Learning metrics
    patterns_learned: int = 0
    pattern_matches: int = 0
    threshold_adjustments: int = 0

    # Data quality scores
    avg_completeness_score: float = 0.0
    provenance_coverage: float = 0.0
    duplicate_estimate: int = 0
    orphan_count: int = 0

    # Copyright status
    flagged_descriptions: int = 0
    rewritten_count: int = 0

    # Timestamps
    last_scan_at: Optional[datetime] = None
    last_fix_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "total_issues_detected": self.total_issues_detected,
            "issues_by_type": self.issues_by_type,
            "issues_by_risk": self.issues_by_risk,
            "auto_fixed_count": self.auto_fixed_count,
            "pending_approval_count": self.pending_approval_count,
            "approved_count": self.approved_count,
            "rejected_count": self.rejected_count,
            "patterns_learned": self.patterns_learned,
            "pattern_matches": self.pattern_matches,
            "threshold_adjustments": self.threshold_adjustments,
            "avg_completeness_score": self.avg_completeness_score,
            "provenance_coverage": self.provenance_coverage,
            "duplicate_estimate": self.duplicate_estimate,
            "orphan_count": self.orphan_count,
            "flagged_descriptions": self.flagged_descriptions,
            "rewritten_count": self.rewritten_count,
            "last_scan_at": self.last_scan_at.isoformat() if self.last_scan_at else None,
            "last_fix_at": self.last_fix_at.isoformat() if self.last_fix_at else None,
        }


class MetricsCollector:
    """Collects and aggregates hygiene metrics."""

    def __init__(self):
        """Initialize the metrics collector."""
        self.metrics = HygieneMetrics()

    def record_scan(self, scan_result: dict):
        """Record metrics from a scan result.

        Args:
            scan_result: Result from HygieneScanner.run_full_scan()
        """
        self.metrics.total_issues_detected = scan_result.get("total_issues", 0)
        self.metrics.issues_by_type = scan_result.get("by_type", {})

        # Convert risk counts
        by_risk = scan_result.get("by_risk", {})
        self.metrics.issues_by_risk = {
            "low": by_risk.get("low", 0),
            "medium": by_risk.get("medium", 0),
            "high": by_risk.get("high", 0),
        }

        self.metrics.pending_approval_count = scan_result.get("approval_required", 0)
        self.metrics.last_scan_at = datetime.now()

    def record_fix(self, fix_result):
        """Record metrics from a fix result.

        Args:
            fix_result: Result from AutoFixer.apply_fix()
        """
        if fix_result.success:
            if fix_result.was_auto_fixed:
                self.metrics.auto_fixed_count += 1
            else:
                self.metrics.approved_count += 1
            self.metrics.last_fix_at = datetime.now()

    def record_rejection(self):
        """Record a rejected fix."""
        self.metrics.rejected_count += 1

    def record_pattern_learned(self):
        """Record a newly learned pattern."""
        self.metrics.patterns_learned += 1

    def record_pattern_match(self):
        """Record a pattern match."""
        self.metrics.pattern_matches += 1

    def record_threshold_adjustment(self):
        """Record a threshold adjustment."""
        self.metrics.threshold_adjustments += 1

    def update_data_quality_metrics(
        self,
        avg_completeness: float,
        provenance_coverage: float,
        duplicate_estimate: int,
        orphan_count: int,
    ):
        """Update data quality metrics.

        Args:
            avg_completeness: Average completeness score across items
            provenance_coverage: % of fields with provenance tracking
            duplicate_estimate: Estimated number of duplicates
            orphan_count: Number of orphaned nodes
        """
        self.metrics.avg_completeness_score = avg_completeness
        self.metrics.provenance_coverage = provenance_coverage
        self.metrics.duplicate_estimate = duplicate_estimate
        self.metrics.orphan_count = orphan_count

    def update_copyright_metrics(self, flagged: int, rewritten: int):
        """Update copyright-related metrics.

        Args:
            flagged: Number of flagged descriptions
            rewritten: Number of rewritten descriptions
        """
        self.metrics.flagged_descriptions = flagged
        self.metrics.rewritten_count = rewritten

    def get_metrics(self) -> HygieneMetrics:
        """Get current metrics.

        Returns:
            Current HygieneMetrics
        """
        return self.metrics

    def get_summary(self) -> dict:
        """Get a human-readable summary.

        Returns:
            Summary dict
        """
        m = self.metrics

        total_fixes = m.auto_fixed_count + m.approved_count
        total_decisions = total_fixes + m.rejected_count

        return {
            "total_issues": m.total_issues_detected,
            "issues_by_risk": m.issues_by_risk,
            "pending_approval": m.pending_approval_count,
            "total_fixes_applied": total_fixes,
            "auto_fix_rate": (
                m.auto_fixed_count / total_fixes if total_fixes > 0 else 0
            ),
            "approval_rate": (
                m.approved_count / total_decisions if total_decisions > 0 else 0
            ),
            "rejection_rate": (
                m.rejected_count / total_decisions if total_decisions > 0 else 0
            ),
            "patterns_learned": m.patterns_learned,
            "data_quality": {
                "avg_completeness": f"{m.avg_completeness_score:.0%}",
                "provenance_coverage": f"{m.provenance_coverage:.0%}",
                "estimated_duplicates": m.duplicate_estimate,
                "orphaned_nodes": m.orphan_count,
            },
            "copyright": {
                "flagged": m.flagged_descriptions,
                "rewritten": m.rewritten_count,
            },
        }


# Global metrics collector instance
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector instance.

    Returns:
        MetricsCollector instance
    """
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def get_current_metrics() -> dict:
    """Get current metrics as a dictionary.

    Returns:
        Metrics dict
    """
    return get_metrics_collector().get_metrics().to_dict()


def get_metrics_summary() -> dict:
    """Get human-readable metrics summary.

    Returns:
        Summary dict
    """
    return get_metrics_collector().get_summary()
