"""Checklist definitions for hygiene evaluation criteria."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CheckCategory(Enum):
    """Categories of hygiene checks."""

    BRAND_VALIDITY = "brand_validity"
    NAME_QUALITY = "name_quality"
    DATA_COMPLETENESS = "data_completeness"
    NODE_RICHNESS = "node_richness"
    PRICING = "pricing"
    PROVENANCE = "provenance"
    RELATIONSHIPS = "relationships"


class CheckPriority(Enum):
    """Priority levels for checks - determines processing order."""

    P1_INSTANT = 1  # Whitespace, case - auto-apply immediately
    P2_QUICK = 2  # Brand in name, invalid brands - LLM quick decision
    P3_CONTEXT = 3  # Brand validity, duplicates - query graph for context
    P4_RESEARCH = 4  # Missing specs, verify brand - external web calls
    P5_DEEP = 5  # Relationships, copyright, enrichment - most effort


@dataclass
class CheckItem:
    """A single evaluation check."""

    id: str
    name: str
    description: str
    category: CheckCategory
    priority: CheckPriority

    # Function name to call for deterministic checks
    check_function: Optional[str] = None

    # For LLM-based checks, the question to ask
    evaluation_prompt: Optional[str] = None

    # Processing flags
    requires_llm: bool = False
    requires_graph_query: bool = False
    requires_web_research: bool = False

    # Auto-fix settings
    can_auto_fix: bool = False
    auto_fix_confidence_threshold: float = 0.95


@dataclass
class CheckResult:
    """Result of running a check."""

    check_id: str
    passed: bool
    issue_found: bool = False
    confidence: float = 1.0
    details: str = ""
    reasoning: str = ""
    suggested_fix: Optional[dict] = None
    evidence: list[str] = field(default_factory=list)
    auto_fixable: bool = False


# Define all checklist items
HYGIENE_CHECKLIST: list[CheckItem] = [
    # P1: Instant fixes - deterministic, auto-apply
    CheckItem(
        id="whitespace_check",
        name="Whitespace Normalization",
        description="Check for leading/trailing whitespace or multiple spaces",
        category=CheckCategory.NAME_QUALITY,
        priority=CheckPriority.P1_INSTANT,
        check_function="check_whitespace",
        requires_llm=False,
        can_auto_fix=True,
        auto_fix_confidence_threshold=0.99,
    ),
    CheckItem(
        id="case_check",
        name="Case Normalization",
        description="Check for improper casing (all caps, all lowercase)",
        category=CheckCategory.NAME_QUALITY,
        priority=CheckPriority.P1_INSTANT,
        check_function="check_case_normalization",
        requires_llm=False,
        can_auto_fix=True,
        auto_fix_confidence_threshold=0.95,
    ),
    # P2: Quick LLM judgment
    CheckItem(
        id="brand_in_name",
        name="Redundant Brand in Name",
        description="Check if brand name appears redundantly in product name",
        category=CheckCategory.NAME_QUALITY,
        priority=CheckPriority.P2_QUICK,
        evaluation_prompt=(
            "The product is '{name}' by brand '{brand}'. "
            "Is the brand name redundantly included in the product name? "
            "Note: Some products legitimately include brand words "
            "(like 'Big Agnes Big House' where 'Big House' is the product name). "
            "Only flag if truly redundant (e.g., 'Osprey Osprey Pack')."
        ),
        requires_llm=True,
        can_auto_fix=False,  # Always needs review
    ),
    CheckItem(
        id="invalid_brand",
        name="Invalid/Generic Brand",
        description="Check if brand is a generic term rather than actual brand",
        category=CheckCategory.BRAND_VALIDITY,
        priority=CheckPriority.P2_QUICK,
        evaluation_prompt=(
            "Is '{brand}' a legitimate outdoor gear brand name, or is it a "
            "generic term (like 'sleeping bag', 'ultralight', 'backpack', "
            "'down jacket')? Generic terms should not be used as brand names."
        ),
        requires_llm=True,
        can_auto_fix=False,
    ),
    # P3: Context lookup - query graph then evaluate
    CheckItem(
        id="brand_exists",
        name="Brand Exists in Graph",
        description="Check if brand has multiple entries in database",
        category=CheckCategory.BRAND_VALIDITY,
        priority=CheckPriority.P3_CONTEXT,
        check_function="check_brand_in_graph",
        requires_graph_query=True,
        requires_llm=False,
    ),
    CheckItem(
        id="potential_duplicate",
        name="Potential Duplicate",
        description="Check for similar items that might be duplicates",
        category=CheckCategory.RELATIONSHIPS,
        priority=CheckPriority.P3_CONTEXT,
        check_function="find_duplicates_for_item",
        requires_graph_query=True,
        requires_llm=False,
    ),
    CheckItem(
        id="transcription_error",
        name="Transcription Error",
        description="Check for common YouTube transcription errors",
        category=CheckCategory.NAME_QUALITY,
        priority=CheckPriority.P3_CONTEXT,
        check_function="check_known_transcription_errors",
        requires_graph_query=True,
        can_auto_fix=True,
        auto_fix_confidence_threshold=0.90,
    ),
    # P4: Web research - external validation
    CheckItem(
        id="verify_brand",
        name="Verify Brand Exists",
        description="Verify brand is a real outdoor gear company via web",
        category=CheckCategory.BRAND_VALIDITY,
        priority=CheckPriority.P4_RESEARCH,
        check_function="verify_brand_via_web",
        requires_web_research=True,
        requires_llm=False,
    ),
    CheckItem(
        id="missing_weight",
        name="Missing Weight",
        description="Item lacks weight data - research to find it",
        category=CheckCategory.DATA_COMPLETENESS,
        priority=CheckPriority.P4_RESEARCH,
        check_function="research_missing_weight",
        requires_web_research=True,
        can_auto_fix=False,  # Needs verification
    ),
    CheckItem(
        id="missing_price",
        name="Missing/Outdated Price",
        description="Item lacks price or price is outdated",
        category=CheckCategory.PRICING,
        priority=CheckPriority.P4_RESEARCH,
        check_function="research_current_price",
        requires_web_research=True,
        can_auto_fix=False,
    ),
    # P5: Deep enrichment - comprehensive analysis
    CheckItem(
        id="orphaned_node",
        name="Orphaned Node",
        description="Node has no relationships to other entities",
        category=CheckCategory.NODE_RICHNESS,
        priority=CheckPriority.P5_DEEP,
        check_function="check_orphaned_node",
        requires_graph_query=True,
    ),
    CheckItem(
        id="missing_provenance",
        name="Missing Provenance",
        description="Data lacks source attribution",
        category=CheckCategory.PROVENANCE,
        priority=CheckPriority.P5_DEEP,
        check_function="check_provenance",
        requires_graph_query=True,
    ),
    CheckItem(
        id="data_completeness",
        name="Data Completeness",
        description="Check overall data completeness score",
        category=CheckCategory.DATA_COMPLETENESS,
        priority=CheckPriority.P5_DEEP,
        check_function="check_data_completeness",
        requires_llm=False,
    ),
    CheckItem(
        id="copyright_concern",
        name="Copyright Concern",
        description="Description may contain copyrighted content",
        category=CheckCategory.DATA_COMPLETENESS,
        priority=CheckPriority.P5_DEEP,
        evaluation_prompt=(
            "Does this description appear to be directly copied from a "
            "manufacturer or retailer website (marketing language, "
            "superlatives, promotional tone)? Description: '{description}'"
        ),
        requires_llm=True,
        can_auto_fix=False,
    ),
]


def get_checks_by_priority(priority: CheckPriority) -> list[CheckItem]:
    """Get all checks for a specific priority level.

    Args:
        priority: Priority level to filter by

    Returns:
        List of CheckItems at that priority
    """
    return [c for c in HYGIENE_CHECKLIST if c.priority == priority]


def get_checks_by_category(category: CheckCategory) -> list[CheckItem]:
    """Get all checks in a category.

    Args:
        category: Category to filter by

    Returns:
        List of CheckItems in that category
    """
    return [c for c in HYGIENE_CHECKLIST if c.category == category]


def get_check_by_id(check_id: str) -> Optional[CheckItem]:
    """Get a specific check by ID.

    Args:
        check_id: The check ID

    Returns:
        CheckItem or None if not found
    """
    for check in HYGIENE_CHECKLIST:
        if check.id == check_id:
            return check
    return None


def get_auto_fixable_checks() -> list[CheckItem]:
    """Get all checks that support auto-fixing.

    Returns:
        List of CheckItems that can auto-fix
    """
    return [c for c in HYGIENE_CHECKLIST if c.can_auto_fix]


def get_llm_checks() -> list[CheckItem]:
    """Get all checks that require LLM evaluation.

    Returns:
        List of CheckItems requiring LLM
    """
    return [c for c in HYGIENE_CHECKLIST if c.requires_llm]
