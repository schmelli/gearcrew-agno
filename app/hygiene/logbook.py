"""Logbook for tracking all hygiene decisions."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import json
import uuid


class DecisionType(Enum):
    """Types of decisions the agent can make."""

    AUTO_FIXED = "auto_fixed"  # Applied automatically
    FLAGGED_FOR_REVIEW = "flagged"  # Needs human review
    SKIPPED = "skipped"  # Decided not to act
    NO_ISSUE = "no_issue"  # Check passed, no problem found
    APPROVED = "approved"  # Human approved fix
    REJECTED = "rejected"  # Human rejected fix
    DEFERRED = "deferred"  # Postponed for later


class ActionType(Enum):
    """Types of actions taken."""

    CHECK_PERFORMED = "check"
    FIX_APPLIED = "fix_applied"
    FIX_PROPOSED = "fix_proposed"
    RESEARCH_CONDUCTED = "research"
    CONTEXT_GATHERED = "context"


@dataclass
class LogEntry:
    """A single logbook entry."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)

    # What was evaluated
    entity_type: str = ""  # GearItem, OutdoorBrand, etc.
    entity_id: str = ""  # Database ID
    entity_name: str = ""  # Human-readable name
    entity_brand: str = ""  # Brand if applicable

    # What check was performed
    check_id: str = ""  # From checklist
    check_name: str = ""
    priority: int = 0

    # Decision made
    decision: DecisionType = DecisionType.SKIPPED
    action: ActionType = ActionType.CHECK_PERFORMED

    # Reasoning (critical for auditability)
    reasoning: str = ""  # LLM's reasoning for decision
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)

    # Fix details (if applicable)
    fix_type: Optional[str] = None
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None

    # Context gathered
    context_used: dict = field(default_factory=dict)

    # Review status
    reviewed_by: Optional[str] = None  # human or agent_id
    reviewed_at: Optional[datetime] = None
    review_notes: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "entity_brand": self.entity_brand,
            "check_id": self.check_id,
            "check_name": self.check_name,
            "priority": self.priority,
            "decision": self.decision.value,
            "action": self.action.value,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "fix_type": self.fix_type,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "context_used": self.context_used,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "review_notes": self.review_notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LogEntry":
        """Create from dictionary."""
        entry = cls(
            id=data["id"],
            entity_type=data["entity_type"],
            entity_id=data["entity_id"],
            entity_name=data.get("entity_name", ""),
            entity_brand=data.get("entity_brand", ""),
            check_id=data["check_id"],
            check_name=data.get("check_name", ""),
            priority=data.get("priority", 0),
            decision=DecisionType(data["decision"]),
            action=ActionType(data["action"]),
            reasoning=data["reasoning"],
            confidence=data.get("confidence", 0.0),
            evidence=data.get("evidence", []),
            fix_type=data.get("fix_type"),
            old_value=data.get("old_value"),
            new_value=data.get("new_value"),
            context_used=data.get("context_used", {}),
            reviewed_by=data.get("reviewed_by"),
            review_notes=data.get("review_notes", ""),
        )
        entry.timestamp = datetime.fromisoformat(data["timestamp"])
        if data.get("reviewed_at"):
            entry.reviewed_at = datetime.fromisoformat(data["reviewed_at"])
        return entry


class HygieneLogbook:
    """Manages the decision log for hygiene operations."""

    def __init__(self, storage_path: Optional[str] = None):
        """Initialize the logbook.

        Args:
            storage_path: Optional path to persist logs (JSON lines file)
        """
        self.entries: list[LogEntry] = []
        self.storage_path = storage_path
        self._session_id = str(uuid.uuid4())[:8]

        if storage_path:
            self._load_from_file()

    def log(
        self,
        entity_type: str,
        entity_id: str,
        check_id: str,
        decision: DecisionType,
        reasoning: str,
        **kwargs,
    ) -> LogEntry:
        """Log a decision.

        Args:
            entity_type: Type of entity evaluated
            entity_id: Database ID of entity
            check_id: Which check was performed
            decision: Decision made
            reasoning: Explanation for the decision
            **kwargs: Additional fields (entity_name, confidence, etc.)

        Returns:
            The created LogEntry
        """
        entry = LogEntry(
            entity_type=entity_type,
            entity_id=entity_id,
            check_id=check_id,
            decision=decision,
            reasoning=reasoning,
            **kwargs,
        )
        self.entries.append(entry)

        if self.storage_path:
            self._save_entry(entry)

        return entry

    def log_check(
        self,
        entity_id: str,
        entity_name: str,
        check_id: str,
        decision: DecisionType,
        reasoning: str,
        confidence: float = 1.0,
        entity_brand: str = "",
        check_name: str = "",
        priority: int = 0,
        fix_details: Optional[dict] = None,
    ) -> LogEntry:
        """Log a check result.

        Args:
            entity_id: Database ID
            entity_name: Product/item name
            check_id: Check identifier
            decision: Decision type made
            reasoning: Explanation
            confidence: Confidence in the assessment (0.0-1.0)
            entity_brand: Brand name (optional)
            check_name: Human-readable check name (optional)
            priority: Priority level (1-5, optional)
            fix_details: Dict with fix info (optional)

        Returns:
            The created LogEntry
        """
        action = ActionType.CHECK_PERFORMED
        if decision == DecisionType.AUTO_FIXED:
            action = ActionType.FIX_APPLIED
        elif decision == DecisionType.FLAGGED_FOR_REVIEW:
            action = ActionType.FIX_PROPOSED

        entry = LogEntry(
            entity_type="GearItem",
            entity_id=entity_id,
            entity_name=entity_name,
            entity_brand=entity_brand,
            check_id=check_id,
            check_name=check_name or check_id,
            priority=priority,
            decision=decision,
            action=action,
            reasoning=reasoning,
            confidence=confidence,
        )

        if fix_details:
            entry.fix_type = fix_details.get("fix_type")
            entry.old_value = fix_details.get("old_value")
            entry.new_value = fix_details.get("new_value")

        self.entries.append(entry)

        if self.storage_path:
            self._save_entry(entry)

        return entry

    def get_entries_for_entity(self, entity_id: str) -> list[LogEntry]:
        """Get all log entries for a specific entity."""
        return [e for e in self.entries if e.entity_id == entity_id]

    def get_entries_by_decision(self, decision: DecisionType) -> list[LogEntry]:
        """Get all entries with a specific decision type."""
        return [e for e in self.entries if e.decision == decision]

    def get_entries_by_check(self, check_id: str) -> list[LogEntry]:
        """Get all entries for a specific check."""
        return [e for e in self.entries if e.check_id == check_id]

    def get_pending_reviews(self) -> list[LogEntry]:
        """Get entries flagged for review that haven't been reviewed."""
        return [
            e
            for e in self.entries
            if e.decision == DecisionType.FLAGGED_FOR_REVIEW and e.reviewed_at is None
        ]

    def get_auto_fixed(self) -> list[LogEntry]:
        """Get all auto-fixed entries."""
        return [e for e in self.entries if e.decision == DecisionType.AUTO_FIXED]

    def mark_reviewed(
        self, entry_id: str, reviewer: str, approved: bool, notes: str = ""
    ) -> Optional[LogEntry]:
        """Mark a log entry as reviewed.

        Args:
            entry_id: ID of the entry
            reviewer: Who reviewed (username or 'agent')
            approved: Whether the decision was approved
            notes: Optional review notes

        Returns:
            Updated entry or None if not found
        """
        for entry in self.entries:
            if entry.id == entry_id:
                entry.reviewed_by = reviewer
                entry.reviewed_at = datetime.now()
                entry.review_notes = notes
                if approved:
                    entry.decision = DecisionType.APPROVED
                else:
                    entry.decision = DecisionType.REJECTED
                return entry
        return None

    def get_session_summary(self) -> dict:
        """Get summary statistics for current session."""
        return self.get_statistics()

    def get_statistics(self) -> dict:
        """Get summary statistics."""
        total = len(self.entries)
        by_decision: dict[str, int] = {}
        by_check: dict[str, int] = {}
        by_priority: dict[int, int] = {}

        for entry in self.entries:
            dec = entry.decision.value
            by_decision[dec] = by_decision.get(dec, 0) + 1

            check = entry.check_id
            by_check[check] = by_check.get(check, 0) + 1

            p = entry.priority
            by_priority[p] = by_priority.get(p, 0) + 1

        return {
            "session_id": self._session_id,
            "total_entries": total,
            "by_decision": by_decision,
            "by_check": by_check,
            "by_priority": by_priority,
            "pending_reviews": len(self.get_pending_reviews()),
            "auto_fixed": len(self.get_auto_fixed()),
        }

    def export_for_review(self, format: str = "json") -> str:
        """Export log entries for external review.

        Args:
            format: Output format ('json' or 'markdown')

        Returns:
            Formatted string
        """
        if format == "json":
            return json.dumps([e.to_dict() for e in self.entries], indent=2)

        elif format == "markdown":
            lines = ["# Hygiene Decision Log\n"]
            lines.append(f"Session: {self._session_id}\n")
            lines.append(f"Total Entries: {len(self.entries)}\n\n")

            # Group by entity
            by_entity: dict[str, list[LogEntry]] = {}
            for entry in self.entries:
                key = f"{entry.entity_name} ({entry.entity_brand})"
                if key not in by_entity:
                    by_entity[key] = []
                by_entity[key].append(entry)

            for entity, entries in by_entity.items():
                lines.append(f"## {entity}\n")
                for entry in entries:
                    icon = {
                        DecisionType.AUTO_FIXED: "v",
                        DecisionType.NO_ISSUE: "o",
                        DecisionType.FLAGGED_FOR_REVIEW: "!",
                        DecisionType.APPROVED: "v",
                        DecisionType.REJECTED: "x",
                    }.get(entry.decision, "-")

                    lines.append(f"- [{icon}] **{entry.check_name}**")
                    lines.append(f"  - Decision: {entry.decision.value}")
                    lines.append(f"  - Confidence: {entry.confidence:.0%}")
                    lines.append(f"  - Reasoning: {entry.reasoning[:100]}...")
                    if entry.fix_type:
                        lines.append(
                            f"  - Fix: `{entry.old_value}` -> `{entry.new_value}`"
                        )
                    lines.append("")

            return "\n".join(lines)

        return ""

    def clear(self):
        """Clear all entries (for testing)."""
        self.entries = []

    def _save_entry(self, entry: LogEntry):
        """Append entry to storage file."""
        if not self.storage_path:
            return
        try:
            with open(self.storage_path, "a") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")
        except Exception:
            pass

    def _load_from_file(self):
        """Load entries from storage file."""
        if not self.storage_path:
            return
        try:
            with open(self.storage_path, "r") as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        self.entries.append(LogEntry.from_dict(data))
        except FileNotFoundError:
            pass


# Global logbook instance
_logbook: Optional[HygieneLogbook] = None


def get_logbook(storage_path: Optional[str] = None) -> HygieneLogbook:
    """Get or create the global logbook instance.

    Args:
        storage_path: Optional path for persistent storage

    Returns:
        HygieneLogbook instance
    """
    global _logbook
    if _logbook is None:
        _logbook = HygieneLogbook(storage_path)
    return _logbook


def reset_logbook():
    """Reset the global logbook (for testing)."""
    global _logbook
    _logbook = None
