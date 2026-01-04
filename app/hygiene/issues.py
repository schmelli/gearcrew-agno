"""Issue type definitions and data classes for the hygiene system."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import uuid


class IssueType(Enum):
    """Types of data quality issues detected by the scanner."""

    # Low Risk (auto-fixable)
    TYPO = "typo"
    FORMATTING = "formatting"
    CASE_NORMALIZATION = "case_normalization"
    WHITESPACE = "whitespace"
    SPECIAL_CHAR_CLEANUP = "special_char_cleanup"

    # Medium Risk (auto-fix with logging)
    SPELLING_VARIANT = "spelling_variant"
    BRAND_STANDARDIZATION = "brand_standardization"
    CATEGORY_INFERENCE = "category_inference"
    MISSING_PROVENANCE = "missing_provenance"
    INCOMPLETE_DATA = "incomplete_data"

    # High Risk (requires approval)
    DUPLICATE_MERGE = "duplicate_merge"
    DATA_DELETION = "data_deletion"
    MAJOR_PROPERTY_CHANGE = "major_property_change"
    HALLUCINATION_DETECTION = "hallucination_detection"
    COPYRIGHT_REWRITE = "copyright_rewrite"
    ORPHANED_NODE = "orphaned_node"


class RiskLevel(Enum):
    """Risk level determines whether auto-fix is allowed."""

    LOW = "low"  # Auto-fix silently
    MEDIUM = "medium"  # Auto-fix with logging
    HIGH = "high"  # Requires human approval


class FixType(Enum):
    """Types of fixes that can be applied."""

    UPDATE_FIELD = "update_field"
    MERGE_ENTITIES = "merge_entities"
    DELETE_ENTITY = "delete_entity"
    CREATE_RELATIONSHIP = "create_relationship"
    DELETE_RELATIONSHIP = "delete_relationship"
    REWRITE_CONTENT = "rewrite_content"


class ApprovalStatus(Enum):
    """Status of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    MODIFIED = "modified"  # User approved with modifications
    IGNORED = "ignored"  # User chose to ignore


# Default risk levels for each issue type
DEFAULT_RISK_LEVELS: dict[IssueType, RiskLevel] = {
    # Low risk - auto-fix
    IssueType.TYPO: RiskLevel.LOW,
    IssueType.FORMATTING: RiskLevel.LOW,
    IssueType.CASE_NORMALIZATION: RiskLevel.LOW,
    IssueType.WHITESPACE: RiskLevel.LOW,
    IssueType.SPECIAL_CHAR_CLEANUP: RiskLevel.LOW,
    # Medium risk - auto-fix with logging
    IssueType.SPELLING_VARIANT: RiskLevel.MEDIUM,
    IssueType.BRAND_STANDARDIZATION: RiskLevel.MEDIUM,
    IssueType.CATEGORY_INFERENCE: RiskLevel.MEDIUM,
    IssueType.MISSING_PROVENANCE: RiskLevel.LOW,
    IssueType.INCOMPLETE_DATA: RiskLevel.LOW,
    # High risk - requires approval
    IssueType.DUPLICATE_MERGE: RiskLevel.HIGH,
    IssueType.DATA_DELETION: RiskLevel.HIGH,
    IssueType.MAJOR_PROPERTY_CHANGE: RiskLevel.HIGH,
    IssueType.HALLUCINATION_DETECTION: RiskLevel.HIGH,
    IssueType.COPYRIGHT_REWRITE: RiskLevel.HIGH,
    IssueType.ORPHANED_NODE: RiskLevel.HIGH,
}

# Default confidence thresholds for auto-fixing
DEFAULT_THRESHOLDS: dict[IssueType, float] = {
    IssueType.TYPO: 0.90,
    IssueType.FORMATTING: 0.95,
    IssueType.CASE_NORMALIZATION: 0.99,
    IssueType.WHITESPACE: 0.99,
    IssueType.SPECIAL_CHAR_CLEANUP: 0.95,
    IssueType.SPELLING_VARIANT: 0.90,
    IssueType.BRAND_STANDARDIZATION: 0.85,
    IssueType.CATEGORY_INFERENCE: 0.80,
    IssueType.MISSING_PROVENANCE: 0.95,
    IssueType.INCOMPLETE_DATA: 0.95,
    IssueType.DUPLICATE_MERGE: 0.95,
    IssueType.DATA_DELETION: 0.99,
    IssueType.MAJOR_PROPERTY_CHANGE: 0.90,
    IssueType.HALLUCINATION_DETECTION: 0.90,
    IssueType.COPYRIGHT_REWRITE: 0.85,
    IssueType.ORPHANED_NODE: 0.95,
}


@dataclass
class Fix:
    """A proposed fix for a hygiene issue."""

    fix_type: FixType
    target_entity_type: str  # GearItem, OutdoorBrand, etc.
    target_entity_id: str  # Database ID or name+brand combo
    target_field: Optional[str] = None  # Field to update (if UPDATE_FIELD)
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    merge_target_id: Optional[str] = None  # For MERGE_ENTITIES
    confidence: float = 0.0
    reasoning: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "fix_type": self.fix_type.value,
            "target_entity_type": self.target_entity_type,
            "target_entity_id": self.target_entity_id,
            "target_field": self.target_field,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "merge_target_id": self.merge_target_id,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Fix":
        """Create from dictionary."""
        return cls(
            fix_type=FixType(data["fix_type"]),
            target_entity_type=data["target_entity_type"],
            target_entity_id=data["target_entity_id"],
            target_field=data.get("target_field"),
            old_value=data.get("old_value"),
            new_value=data.get("new_value"),
            merge_target_id=data.get("merge_target_id"),
            confidence=data.get("confidence", 0.0),
            reasoning=data.get("reasoning", ""),
        )


@dataclass
class HygieneIssue:
    """A detected data quality issue."""

    issue_type: IssueType
    entity_type: str  # GearItem, OutdoorBrand, VideoSource, etc.
    entity_id: str  # Database ID or identifying key
    description: str
    suggested_fix: Fix
    confidence: float = 0.0
    source_channel: Optional[str] = None  # youtube, web_scrape, lighterpack, etc.
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    detected_at: datetime = field(default_factory=datetime.now)
    status: ApprovalStatus = ApprovalStatus.PENDING

    @property
    def risk_level(self) -> RiskLevel:
        """Determine risk level based on issue type and confidence."""
        base_risk = DEFAULT_RISK_LEVELS.get(self.issue_type, RiskLevel.HIGH)

        # Low confidence always escalates to at least MEDIUM
        if self.confidence < 0.80:
            if base_risk == RiskLevel.LOW:
                return RiskLevel.MEDIUM
            return RiskLevel.HIGH

        # Destructive operations are always HIGH
        if self.suggested_fix.fix_type in [FixType.DELETE_ENTITY, FixType.MERGE_ENTITIES]:
            return RiskLevel.HIGH

        return base_risk

    @property
    def can_auto_fix(self) -> bool:
        """Check if this issue can be auto-fixed based on risk and confidence."""
        threshold = DEFAULT_THRESHOLDS.get(self.issue_type, 0.95)
        return (
            self.risk_level == RiskLevel.LOW
            and self.confidence >= threshold
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "issue_type": self.issue_type.value,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "description": self.description,
            "suggested_fix": self.suggested_fix.to_dict(),
            "confidence": self.confidence,
            "source_channel": self.source_channel,
            "detected_at": self.detected_at.isoformat(),
            "status": self.status.value,
            "risk_level": self.risk_level.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "HygieneIssue":
        """Create from dictionary."""
        issue = cls(
            id=data["id"],
            issue_type=IssueType(data["issue_type"]),
            entity_type=data["entity_type"],
            entity_id=data["entity_id"],
            description=data["description"],
            suggested_fix=Fix.from_dict(data["suggested_fix"]),
            confidence=data.get("confidence", 0.0),
            source_channel=data.get("source_channel"),
            status=ApprovalStatus(data.get("status", "pending")),
        )
        if "detected_at" in data:
            issue.detected_at = datetime.fromisoformat(data["detected_at"])
        return issue


@dataclass
class CorrectionRecord:
    """A record of a correction made, for learning."""

    issue_type: IssueType
    original_value: str
    corrected_value: str
    was_approved: bool
    was_auto_fixed: bool
    confidence_at_time: float
    source_channel: Optional[str] = None
    entity_type: Optional[str] = None
    field_name: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    correction_pattern: Optional[str] = None  # Extracted regex pattern

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "issue_type": self.issue_type.value,
            "original_value": self.original_value,
            "corrected_value": self.corrected_value,
            "was_approved": self.was_approved,
            "was_auto_fixed": self.was_auto_fixed,
            "confidence_at_time": self.confidence_at_time,
            "source_channel": self.source_channel,
            "entity_type": self.entity_type,
            "field_name": self.field_name,
            "timestamp": self.timestamp.isoformat(),
            "correction_pattern": self.correction_pattern,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CorrectionRecord":
        """Create from dictionary."""
        record = cls(
            id=data["id"],
            issue_type=IssueType(data["issue_type"]),
            original_value=data["original_value"],
            corrected_value=data["corrected_value"],
            was_approved=data["was_approved"],
            was_auto_fixed=data["was_auto_fixed"],
            confidence_at_time=data["confidence_at_time"],
            source_channel=data.get("source_channel"),
            entity_type=data.get("entity_type"),
            field_name=data.get("field_name"),
            correction_pattern=data.get("correction_pattern"),
        )
        if "timestamp" in data:
            record.timestamp = datetime.fromisoformat(data["timestamp"])
        return record


@dataclass
class CorrectionPattern:
    """A learned correction pattern extracted from approved fixes."""

    source_pattern: str  # Regex or string pattern
    target_pattern: str  # Replacement string
    issue_type: IssueType
    source_channel: Optional[str] = None  # Where this pattern is most common
    occurrences: int = 0
    success_rate: float = 0.0  # % of times this pattern was approved
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.now)
    last_used_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "source_pattern": self.source_pattern,
            "target_pattern": self.target_pattern,
            "issue_type": self.issue_type.value,
            "source_channel": self.source_channel,
            "occurrences": self.occurrences,
            "success_rate": self.success_rate,
            "created_at": self.created_at.isoformat(),
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CorrectionPattern":
        """Create from dictionary."""
        pattern = cls(
            id=data["id"],
            source_pattern=data["source_pattern"],
            target_pattern=data["target_pattern"],
            issue_type=IssueType(data["issue_type"]),
            source_channel=data.get("source_channel"),
            occurrences=data.get("occurrences", 0),
            success_rate=data.get("success_rate", 0.0),
        )
        if "created_at" in data:
            pattern.created_at = datetime.fromisoformat(data["created_at"])
        if data.get("last_used_at"):
            pattern.last_used_at = datetime.fromisoformat(data["last_used_at"])
        return pattern


# Known transcription error patterns (from YouTube, etc.)
KNOWN_TRANSCRIPTION_ERRORS: dict[str, str] = {
    # Brand name errors
    "Durst": "Durston",
    "Durstin": "Durston",
    "Arc'o": "Arc Haul",
    "Arko": "Arc Haul",
    "Zpack": "Zpacks",
    "Z pack": "Zpacks",
    "Z-pack": "Zpacks",
    "Thermarest": "Therm-a-Rest",
    "Therma rest": "Therm-a-Rest",
    "Therma-rest": "Therm-a-Rest",
    "Thermorest": "Therm-a-Rest",
    "Gossamer": "Gossamer Gear",
    "Six moon": "Six Moon Designs",
    "6 moon": "Six Moon Designs",
    "UL Equipment": "Enlightened Equipment",
    "Enlighten Equipment": "Enlightened Equipment",
    "Hyper Lite": "Hyperlite Mountain Gear",
    "Hyperlite MG": "Hyperlite Mountain Gear",
    "Sea 2 Summit": "Sea to Summit",
    "Sea-to-Summit": "Sea to Summit",
    "Big Agnus": "Big Agnes",
    "Big Agness": "Big Agnes",
    "Nemo Equipment": "NEMO Equipment",
    # Product name errors
    "X Mid": "X-Mid",
    "X-mid": "X-Mid",
    "XMID": "X-Mid",
    "Z Lite": "Z Lite Sol",
    "Zlite": "Z Lite Sol",
    "Neo Air": "NeoAir",
    "Neo-Air": "NeoAir",
    "Atmos 65": "Atmos AG 65",
    "Exos 58": "Exos 58",
}

# Brand name standardization (canonical forms)
CANONICAL_BRANDS: dict[str, str] = {
    # Lowercase variations
    "zpacks": "Zpacks",
    "ZPACKS": "Zpacks",
    "thermarest": "Therm-a-Rest",
    "therm-a-rest": "Therm-a-Rest",
    "THERM-A-REST": "Therm-a-Rest",
    "therma-rest": "Therm-a-Rest",
    "nemo": "NEMO Equipment",
    "NEMO": "NEMO Equipment",
    "msr": "MSR",
    "osprey": "Osprey",
    "OSPREY": "Osprey",
    "big agnes": "Big Agnes",
    "BIG AGNES": "Big Agnes",
    "sea to summit": "Sea to Summit",
    "SEA TO SUMMIT": "Sea to Summit",
    "hyperlite": "Hyperlite Mountain Gear",
    "HYPERLITE": "Hyperlite Mountain Gear",
    "hmg": "Hyperlite Mountain Gear",
    "HMG": "Hyperlite Mountain Gear",
    "gossamer gear": "Gossamer Gear",
    "GOSSAMER GEAR": "Gossamer Gear",
    "gg": "Gossamer Gear",
    "GG": "Gossamer Gear",
    "enlightened equipment": "Enlightened Equipment",
    "ENLIGHTENED EQUIPMENT": "Enlightened Equipment",
    "ee": "Enlightened Equipment",
    "EE": "Enlightened Equipment",
    "ula": "ULA Equipment",
    "ULA": "ULA Equipment",
    "six moon designs": "Six Moon Designs",
    "SIX MOON DESIGNS": "Six Moon Designs",
    "smd": "Six Moon Designs",
    "SMD": "Six Moon Designs",
    "mountain laurel designs": "Mountain Laurel Designs",
    "MLD": "Mountain Laurel Designs",
    "mld": "Mountain Laurel Designs",
    "western mountaineering": "Western Mountaineering",
    "WM": "Western Mountaineering",
    "wm": "Western Mountaineering",
    "katabatic": "Katabatic Gear",
    "KATABATIC": "Katabatic Gear",
    "tarptent": "Tarptent",
    "TARPTENT": "Tarptent",
    "tarp tent": "Tarptent",
    "black diamond": "Black Diamond",
    "BLACK DIAMOND": "Black Diamond",
    "bd": "Black Diamond",
    "BD": "Black Diamond",
    "patagonia": "Patagonia",
    "PATAGONIA": "Patagonia",
    "arc'teryx": "Arc'teryx",
    "arcteryx": "Arc'teryx",
    "ARCTERYX": "Arc'teryx",
    "outdoor research": "Outdoor Research",
    "OUTDOOR RESEARCH": "Outdoor Research",
    "or": "Outdoor Research",
    "OR": "Outdoor Research",
}
