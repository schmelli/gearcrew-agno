"""Auto-fixer module for applying low-risk fixes automatically."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.db.memgraph import execute_cypher, execute_and_fetch
from app.hygiene.issues import (
    IssueType,
    RiskLevel,
    FixType,
    ApprovalStatus,
    HygieneIssue,
    Fix,
    CorrectionRecord,
)


@dataclass
class FixResult:
    """Result of applying a fix."""

    success: bool
    issue: HygieneIssue
    message: str
    was_auto_fixed: bool
    applied_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "issue_id": self.issue.id,
            "issue_type": self.issue.issue_type.value,
            "message": self.message,
            "was_auto_fixed": self.was_auto_fixed,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
        }


class AutoFixer:
    """Applies fixes for low-risk hygiene issues automatically."""

    def __init__(self):
        """Initialize the auto-fixer."""
        self.fix_history: list[FixResult] = []
        self.correction_records: list[CorrectionRecord] = []

    def can_auto_fix(self, issue: HygieneIssue) -> bool:
        """Check if an issue can be auto-fixed.

        Args:
            issue: The hygiene issue to check

        Returns:
            True if the issue can be auto-fixed
        """
        # Only auto-fix LOW risk issues
        if issue.risk_level != RiskLevel.LOW:
            return False

        # Check confidence threshold
        if not issue.can_auto_fix:
            return False

        # Check if we have a fixer for this fix type
        fix_type = issue.suggested_fix.fix_type
        return fix_type in [FixType.UPDATE_FIELD]

    def apply_fix(self, issue: HygieneIssue, force: bool = False) -> FixResult:
        """Apply a fix for the given issue.

        Args:
            issue: The hygiene issue to fix
            force: If True, apply even if not auto-fixable (for approved fixes)

        Returns:
            FixResult with success status and message
        """
        # Check if we can auto-fix (unless forced by approval)
        if not force and not self.can_auto_fix(issue):
            return FixResult(
                success=False,
                issue=issue,
                message=f"Cannot auto-fix: risk level is {issue.risk_level.value}, "
                       f"confidence is {issue.confidence:.0%}",
                was_auto_fixed=False,
            )

        fix = issue.suggested_fix

        try:
            # Route to appropriate fixer
            if fix.fix_type == FixType.UPDATE_FIELD:
                result = self._apply_field_update(issue)
            elif fix.fix_type == FixType.MERGE_ENTITIES:
                result = self._apply_merge(issue)
            elif fix.fix_type == FixType.DELETE_ENTITY:
                result = self._apply_delete(issue)
            else:
                return FixResult(
                    success=False,
                    issue=issue,
                    message=f"Unsupported fix type: {fix.fix_type.value}",
                    was_auto_fixed=False,
                )

            # Record the correction for learning
            if result.success:
                self._record_correction(issue, result)
                issue.status = ApprovalStatus.APPROVED

            # Store in history
            self.fix_history.append(result)
            return result

        except Exception as e:
            return FixResult(
                success=False,
                issue=issue,
                message=f"Error applying fix: {str(e)}",
                was_auto_fixed=False,
            )

    def _apply_field_update(self, issue: HygieneIssue) -> FixResult:
        """Apply a field update fix.

        Args:
            issue: The issue with field update fix

        Returns:
            FixResult
        """
        fix = issue.suggested_fix
        entity_type = fix.target_entity_type
        entity_id = fix.target_entity_id
        field = fix.target_field
        new_value = fix.new_value

        # Handle brand-wide updates (special case)
        if entity_id.startswith("brand:"):
            old_brand = entity_id.replace("brand:", "")
            return self._apply_brand_standardization(old_brand, new_value)

        # Build the Cypher query for regular field update
        if entity_type == "GearItem":
            query = f"""
            MATCH (g:GearItem)
            WHERE id(g) = $id
            SET g.{field} = $value, g.updatedAt = datetime()
            RETURN g.name AS name, g.brand AS brand
            """
        elif entity_type == "OutdoorBrand":
            query = f"""
            MATCH (b:OutdoorBrand)
            WHERE id(b) = $id
            SET b.{field} = $value, b.updatedAt = datetime()
            RETURN b.name AS name
            """
        else:
            return FixResult(
                success=False,
                issue=issue,
                message=f"Unsupported entity type: {entity_type}",
                was_auto_fixed=False,
            )

        try:
            # Convert entity_id to int
            id_int = int(entity_id)

            result = execute_and_fetch(query, {"id": id_int, "value": new_value})

            if result:
                item = result[0]
                name = item.get("name", "Unknown")
                brand = item.get("brand", "")

                return FixResult(
                    success=True,
                    issue=issue,
                    message=f"Updated {field} for '{name}' ({brand}): "
                           f"'{fix.old_value}' -> '{new_value}'",
                    was_auto_fixed=issue.can_auto_fix,
                    applied_at=datetime.now(),
                )
            else:
                return FixResult(
                    success=False,
                    issue=issue,
                    message=f"Entity not found: {entity_type} id={entity_id}",
                    was_auto_fixed=False,
                )

        except Exception as e:
            return FixResult(
                success=False,
                issue=issue,
                message=f"Database error: {str(e)}",
                was_auto_fixed=False,
            )

    def _apply_brand_standardization(self, old_brand: str, new_brand: str) -> FixResult:
        """Apply brand standardization across all items.

        Args:
            old_brand: The non-standard brand name
            new_brand: The canonical brand name

        Returns:
            FixResult
        """
        query = """
        MATCH (g:GearItem)
        WHERE g.brand = $old_brand
        SET g.brand = $new_brand, g.updatedAt = datetime()
        RETURN count(g) AS updated_count
        """

        try:
            result = execute_and_fetch(query, {
                "old_brand": old_brand,
                "new_brand": new_brand
            })

            if result:
                count = result[0].get("updated_count", 0)
                return FixResult(
                    success=True,
                    issue=HygieneIssue(
                        issue_type=IssueType.BRAND_STANDARDIZATION,
                        entity_type="GearItem",
                        entity_id=f"brand:{old_brand}",
                        description=f"Standardized brand: '{old_brand}' -> '{new_brand}'",
                        suggested_fix=Fix(
                            fix_type=FixType.UPDATE_FIELD,
                            target_entity_type="GearItem",
                            target_entity_id=f"brand:{old_brand}",
                            target_field="brand",
                            old_value=old_brand,
                            new_value=new_brand,
                            confidence=0.95,
                            reasoning="Brand standardization",
                        ),
                        confidence=0.95,
                    ),
                    message=f"Standardized brand '{old_brand}' -> '{new_brand}' "
                           f"for {count} items",
                    was_auto_fixed=True,
                    applied_at=datetime.now(),
                )
            else:
                return FixResult(
                    success=False,
                    issue=HygieneIssue(
                        issue_type=IssueType.BRAND_STANDARDIZATION,
                        entity_type="GearItem",
                        entity_id=f"brand:{old_brand}",
                        description="Brand standardization failed",
                        suggested_fix=Fix(
                            fix_type=FixType.UPDATE_FIELD,
                            target_entity_type="GearItem",
                            target_entity_id=f"brand:{old_brand}",
                            target_field="brand",
                            old_value=old_brand,
                            new_value=new_brand,
                            confidence=0.95,
                            reasoning="Brand standardization",
                        ),
                        confidence=0.95,
                    ),
                    message="No items found with this brand",
                    was_auto_fixed=False,
                )

        except Exception as e:
            return FixResult(
                success=False,
                issue=HygieneIssue(
                    issue_type=IssueType.BRAND_STANDARDIZATION,
                    entity_type="GearItem",
                    entity_id=f"brand:{old_brand}",
                    description="Brand standardization failed",
                    suggested_fix=Fix(
                        fix_type=FixType.UPDATE_FIELD,
                        target_entity_type="GearItem",
                        target_entity_id=f"brand:{old_brand}",
                        target_field="brand",
                        old_value=old_brand,
                        new_value=new_brand,
                        confidence=0.95,
                        reasoning="Brand standardization",
                    ),
                    confidence=0.95,
                ),
                message=f"Database error: {str(e)}",
                was_auto_fixed=False,
            )

    def _apply_merge(self, issue: HygieneIssue) -> FixResult:
        """Apply a merge entities fix.

        Args:
            issue: The issue with merge fix

        Returns:
            FixResult
        """
        fix = issue.suggested_fix
        source_id = fix.target_entity_id
        target_id = fix.merge_target_id

        if not target_id:
            return FixResult(
                success=False,
                issue=issue,
                message="No merge target specified",
                was_auto_fixed=False,
            )

        try:
            # Convert IDs to int
            source_id_int = int(source_id)
            target_id_int = int(target_id)

            # Transfer relationships from source to target
            # 1. Transfer EXTRACTED_FROM relationships
            query1 = """
            MATCH (source:GearItem)-[r:EXTRACTED_FROM]->(v:VideoSource)
            WHERE id(source) = $source_id
            MATCH (target:GearItem)
            WHERE id(target) = $target_id
            MERGE (target)-[:EXTRACTED_FROM]->(v)
            DELETE r
            RETURN count(*) AS transferred
            """
            execute_cypher(query1, {"source_id": source_id_int, "target_id": target_id_int})

            # 2. Transfer HAS_TIP relationships
            query2 = """
            MATCH (source:GearItem)-[r:HAS_TIP]->(i:Insight)
            WHERE id(source) = $source_id
            MATCH (target:GearItem)
            WHERE id(target) = $target_id
            MERGE (target)-[:HAS_TIP]->(i)
            DELETE r
            RETURN count(*) AS transferred
            """
            execute_cypher(query2, {"source_id": source_id_int, "target_id": target_id_int})

            # 3. Get info before deleting
            query_info = """
            MATCH (source:GearItem)
            WHERE id(source) = $source_id
            RETURN source.name AS source_name, source.brand AS source_brand
            """
            info = execute_and_fetch(query_info, {"source_id": source_id_int})
            source_name = info[0].get("source_name", "Unknown") if info else "Unknown"
            source_brand = info[0].get("source_brand", "") if info else ""

            # 4. Delete the source node
            query_delete = """
            MATCH (source:GearItem)
            WHERE id(source) = $source_id
            DETACH DELETE source
            """
            execute_cypher(query_delete, {"source_id": source_id_int})

            return FixResult(
                success=True,
                issue=issue,
                message=f"Merged '{source_name}' ({source_brand}) into target (id={target_id})",
                was_auto_fixed=False,  # Merges are never auto-fixed
                applied_at=datetime.now(),
            )

        except Exception as e:
            return FixResult(
                success=False,
                issue=issue,
                message=f"Merge failed: {str(e)}",
                was_auto_fixed=False,
            )

    def _apply_delete(self, issue: HygieneIssue) -> FixResult:
        """Apply a delete entity fix.

        Args:
            issue: The issue with delete fix

        Returns:
            FixResult
        """
        fix = issue.suggested_fix
        entity_type = fix.target_entity_type
        entity_id = fix.target_entity_id

        try:
            id_int = int(entity_id)

            # Get info before deleting
            query_info = f"""
            MATCH (n:{entity_type})
            WHERE id(n) = $id
            RETURN n.name AS name
            """
            info = execute_and_fetch(query_info, {"id": id_int})
            name = info[0].get("name", "Unknown") if info else "Unknown"

            # Delete the node
            query_delete = f"""
            MATCH (n:{entity_type})
            WHERE id(n) = $id
            DETACH DELETE n
            """
            execute_cypher(query_delete, {"id": id_int})

            return FixResult(
                success=True,
                issue=issue,
                message=f"Deleted {entity_type} '{name}' (id={entity_id})",
                was_auto_fixed=False,  # Deletes are never auto-fixed
                applied_at=datetime.now(),
            )

        except Exception as e:
            return FixResult(
                success=False,
                issue=issue,
                message=f"Delete failed: {str(e)}",
                was_auto_fixed=False,
            )

    def _record_correction(self, issue: HygieneIssue, result: FixResult):
        """Record a correction for the learning system.

        Args:
            issue: The fixed issue
            result: The fix result
        """
        fix = issue.suggested_fix

        record = CorrectionRecord(
            issue_type=issue.issue_type,
            original_value=str(fix.old_value) if fix.old_value else "",
            corrected_value=str(fix.new_value) if fix.new_value else "",
            was_approved=True,
            was_auto_fixed=result.was_auto_fixed,
            confidence_at_time=issue.confidence,
            source_channel=issue.source_channel,
            entity_type=issue.entity_type,
            field_name=fix.target_field,
        )

        self.correction_records.append(record)

    def apply_auto_fixes(self, issues: list[HygieneIssue]) -> list[FixResult]:
        """Apply all auto-fixable issues from a list.

        Args:
            issues: List of hygiene issues

        Returns:
            List of fix results
        """
        results = []

        for issue in issues:
            if self.can_auto_fix(issue):
                result = self.apply_fix(issue)
                results.append(result)

                if result.success:
                    print(f"  [AUTO-FIX] {result.message}")
                else:
                    print(f"  [FAILED] {result.message}")

        return results

    def get_fix_summary(self) -> dict:
        """Get summary of all fixes applied.

        Returns:
            Summary dict
        """
        successful = [r for r in self.fix_history if r.success]
        failed = [r for r in self.fix_history if not r.success]
        auto_fixed = [r for r in successful if r.was_auto_fixed]

        return {
            "total_applied": len(self.fix_history),
            "successful": len(successful),
            "failed": len(failed),
            "auto_fixed": len(auto_fixed),
            "corrections_recorded": len(self.correction_records),
        }
