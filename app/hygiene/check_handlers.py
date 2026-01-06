"""Check handlers for hygiene evaluation.

Each handler processes results from evaluation tools and determines
the appropriate action (auto-fix, flag for review, etc.).
"""

from typing import Optional

from app.hygiene.logbook import get_logbook, DecisionType
from app.hygiene.tools import (
    apply_field_update,
    clear_invalid_brand,
    verify_brand_via_web,
)


def handle_p1_check(
    result: dict,
    entity_id: str,
    name: str,
    check_id: str,
) -> dict:
    """Handle P1 (instant) check result - auto-apply fixes.

    Args:
        result: Check result from evaluation tool
        entity_id: Database entity ID
        name: Entity name for logging
        check_id: ID of the check

    Returns:
        Processing result dict
    """
    logbook = get_logbook()

    if not result.get("issue_found"):
        logbook.log_check(
            entity_id=entity_id,
            entity_name=name,
            check_id=check_id,
            decision=DecisionType.NO_ISSUE,
            reasoning=result.get("reasoning", "No issues found"),
            confidence=result.get("confidence", 1.0),
        )
        return {"issue_found": False, "check_id": check_id}

    fixes = result.get("suggested_fixes", [])
    fix_applied = False

    for fix in fixes:
        if result.get("auto_fixable", False):
            fix_result = apply_field_update(
                entity_id=entity_id,
                field=fix["field"],
                old_value=fix["old"],
                new_value=fix["new"],
            )

            if fix_result.get("success"):
                fix_applied = True
                logbook.log_check(
                    entity_id=entity_id,
                    entity_name=name,
                    check_id=check_id,
                    decision=DecisionType.AUTO_FIXED,
                    reasoning=result.get("reasoning", ""),
                    confidence=result.get("confidence", 1.0),
                    fix_details=fix,
                )

    return {
        "issue_found": True,
        "check_id": check_id,
        "fix_applied": fix_applied,
        "fix": fixes[0] if fixes else None,
        "reasoning": result.get("reasoning", ""),
    }


def handle_p2_check(
    result: dict,
    entity_id: str,
    name: str,
    check_id: str,
) -> dict:
    """Handle P2 (judgment) check result - may need LLM.

    Args:
        result: Check result
        entity_id: Database entity ID
        name: Entity name
        check_id: Check ID

    Returns:
        Processing result dict
    """
    logbook = get_logbook()
    recommendation = result.get("recommendation", "review")

    if recommendation == "no_action" or recommendation == "keep":
        logbook.log_check(
            entity_id=entity_id,
            entity_name=name,
            check_id=check_id,
            decision=DecisionType.NO_ISSUE,
            reasoning=result.get("reasoning", ""),
            confidence=result.get("confidence", 0.8),
        )
        return {"issue_found": False, "check_id": check_id}

    if recommendation == "clear_brand":
        fix_result = clear_invalid_brand(entity_id)
        if fix_result.get("success"):
            logbook.log_check(
                entity_id=entity_id,
                entity_name=name,
                check_id=check_id,
                decision=DecisionType.AUTO_FIXED,
                reasoning=result.get("reasoning", ""),
                confidence=0.95,
                fix_details={"action": "clear_brand"},
            )
            return {
                "issue_found": True,
                "check_id": check_id,
                "fix_applied": True,
            }

    # Flag for review
    logbook.log_check(
        entity_id=entity_id,
        entity_name=name,
        check_id=check_id,
        decision=DecisionType.FLAGGED_FOR_REVIEW,
        reasoning=result.get("reasoning", ""),
        confidence=result.get("confidence", 0.5),
    )

    return {
        "issue_found": True,
        "check_id": check_id,
        "fix_applied": False,
        "needs_review": True,
        "reasoning": result.get("reasoning", ""),
    }


def handle_p3_check(
    result: dict,
    entity_id: str,
    name: str,
    brand: str,
    check_id: str,
) -> dict:
    """Handle P3 (context) check result.

    Args:
        result: Check result
        entity_id: Database entity ID
        name: Entity name
        brand: Brand name
        check_id: Check ID

    Returns:
        Processing result dict
    """
    logbook = get_logbook()

    if not result.get("issue_found"):
        logbook.log_check(
            entity_id=entity_id,
            entity_name=name,
            check_id=check_id,
            decision=DecisionType.NO_ISSUE,
            reasoning=result.get("reasoning", ""),
            confidence=result.get("confidence", 1.0),
        )
        return {"issue_found": False, "check_id": check_id}

    # Flag for review - context checks need human judgment
    logbook.log_check(
        entity_id=entity_id,
        entity_name=name,
        check_id=check_id,
        decision=DecisionType.FLAGGED_FOR_REVIEW,
        reasoning=result.get("reasoning", ""),
        confidence=result.get("confidence", 0.7),
    )

    return {
        "issue_found": True,
        "check_id": check_id,
        "fix_applied": False,
        "needs_review": True,
        "reasoning": result.get("reasoning", ""),
    }


def handle_duplicate_check(
    result: dict,
    entity_id: str,
    name: str,
    brand: str,
) -> dict:
    """Handle duplicate check result.

    Args:
        result: Check result with duplicates
        entity_id: Database entity ID
        name: Entity name
        brand: Brand name

    Returns:
        Processing result dict
    """
    logbook = get_logbook()

    if not result.get("issue_found"):
        logbook.log_check(
            entity_id=entity_id,
            entity_name=name,
            check_id="duplicate_check",
            decision=DecisionType.NO_ISSUE,
            reasoning="No duplicates found",
            confidence=1.0,
        )
        return {"issue_found": False, "check_id": "duplicate_check"}

    duplicates = result.get("duplicates", [])
    high_conf = result.get("high_confidence_duplicates", [])

    logbook.log_check(
        entity_id=entity_id,
        entity_name=name,
        check_id="duplicate_check",
        decision=DecisionType.FLAGGED_FOR_REVIEW,
        reasoning=result.get("reasoning", ""),
        confidence=result.get("confidence", 0.8),
        fix_details={
            "duplicate_count": len(duplicates),
            "high_confidence_count": len(high_conf),
            "duplicates": duplicates[:3],
        },
    )

    return {
        "issue_found": True,
        "check_id": "duplicate_check",
        "fix_applied": False,
        "needs_review": True,
        "duplicates": duplicates,
        "reasoning": result.get("reasoning", ""),
    }


def handle_research_check(
    result: dict,
    entity_id: str,
    name: str,
    brand: str,
    check_id: str,
) -> dict:
    """Handle P4 (research) check result.

    Args:
        result: Check result
        entity_id: Database entity ID
        name: Entity name
        brand: Brand name
        check_id: Check ID

    Returns:
        Processing result dict
    """
    logbook = get_logbook()

    if check_id == "verify_brand_web":
        verified = result.get("verified", False)
        if verified:
            logbook.log_check(
                entity_id=entity_id,
                entity_name=name,
                check_id=check_id,
                decision=DecisionType.NO_ISSUE,
                reasoning=result.get("reasoning", "Brand verified"),
                confidence=result.get("confidence", 0.9),
            )
            return {"issue_found": False, "check_id": check_id}

        logbook.log_check(
            entity_id=entity_id,
            entity_name=name,
            check_id=check_id,
            decision=DecisionType.FLAGGED_FOR_REVIEW,
            reasoning=result.get("reasoning", ""),
            confidence=result.get("confidence", 0.5),
            fix_details={
                "suggested_correction": result.get("suggested_correction"),
            },
        )
        return {
            "issue_found": True,
            "check_id": check_id,
            "fix_applied": False,
            "needs_review": True,
        }

    elif check_id == "missing_weight":
        if result.get("found"):
            weight = result.get("weight_grams")
            fix_result = apply_field_update(
                entity_id=entity_id,
                field="weight_grams",
                old_value="",
                new_value=str(weight),
            )

            if fix_result.get("success"):
                logbook.log_check(
                    entity_id=entity_id,
                    entity_name=name,
                    check_id=check_id,
                    decision=DecisionType.AUTO_FIXED,
                    reasoning=f"Found weight: {weight}g",
                    confidence=result.get("confidence", 0.7),
                    fix_details={"weight_grams": weight},
                )
                return {
                    "issue_found": True,
                    "check_id": check_id,
                    "fix_applied": True,
                }

        return {"issue_found": False, "check_id": check_id}

    return {"issue_found": False, "check_id": check_id}


def handle_deep_check(
    result: dict,
    entity_id: str,
    name: str,
    check_id: str,
) -> dict:
    """Handle P5 (deep) check result.

    Args:
        result: Check result
        entity_id: Database entity ID
        name: Entity name
        check_id: Check ID

    Returns:
        Processing result dict
    """
    logbook = get_logbook()

    if not result.get("issue_found"):
        logbook.log_check(
            entity_id=entity_id,
            entity_name=name,
            check_id=check_id,
            decision=DecisionType.NO_ISSUE,
            reasoning=result.get("reasoning", ""),
            confidence=result.get("confidence", 1.0),
        )
        return {"issue_found": False, "check_id": check_id}

    # Deep checks always flag for review
    logbook.log_check(
        entity_id=entity_id,
        entity_name=name,
        check_id=check_id,
        decision=DecisionType.FLAGGED_FOR_REVIEW,
        reasoning=result.get("reasoning", ""),
        confidence=result.get("confidence", 0.8),
    )

    return {
        "issue_found": True,
        "check_id": check_id,
        "fix_applied": False,
        "needs_review": True,
        "reasoning": result.get("reasoning", ""),
    }
