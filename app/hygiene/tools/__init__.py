"""Agent tools for hygiene evaluation and fixing."""

from app.hygiene.tools.evaluation_tools import (
    check_whitespace,
    check_case_normalization,
    check_known_transcription_errors,
    check_brand_in_graph,
    find_duplicates_for_item,
    check_orphaned_node,
    check_provenance,
    check_data_completeness,
    check_weight_consistency,
)

from app.hygiene.tools.fix_tools import (
    apply_field_update,
    apply_brand_standardization,
    merge_duplicate_items,
    create_source_link,
    clear_invalid_brand,
    remove_brand_from_name,
)

from app.hygiene.tools.research_tools import (
    verify_brand_via_web,
    research_missing_weight,
    research_current_price,
    research_product_details,
)

__all__ = [
    # Evaluation tools
    "check_whitespace",
    "check_case_normalization",
    "check_known_transcription_errors",
    "check_brand_in_graph",
    "find_duplicates_for_item",
    "check_orphaned_node",
    "check_provenance",
    "check_data_completeness",
    "check_weight_consistency",
    # Fix tools
    "apply_field_update",
    "apply_brand_standardization",
    "merge_duplicate_items",
    "create_source_link",
    "clear_invalid_brand",
    "remove_brand_from_name",
    # Research tools
    "verify_brand_via_web",
    "research_missing_weight",
    "research_current_price",
    "research_product_details",
]
