"""Hygiene Agent - LLM-based data quality evaluation and fixing.

Replaces rule-based scanning with intelligent evaluation using a checklist,
priority queue, and logbook for full auditability.
"""

import logging
from typing import Optional, Iterator, Callable
from enum import Enum

import langwatch
from agno.agent import Agent
from agno.models.anthropic import Claude

from app.db.memgraph import execute_and_fetch
from app.hygiene.checklist import (
    CheckPriority,
    get_checks_by_priority,
    get_check_by_id,
)
from app.hygiene.logbook import get_logbook, HygieneLogbook
from app.hygiene.priority_queue import (
    get_queue,
    HygieneQueue,
    QueueItem,
    ItemStatus,
)
from app.hygiene.check_handlers import (
    handle_p1_check,
    handle_p2_check,
    handle_p3_check,
    handle_duplicate_check,
    handle_research_check,
    handle_deep_check,
)
from app.hygiene.tools import (
    check_whitespace,
    check_case_normalization,
    check_known_transcription_errors,
    check_brand_in_graph,
    find_duplicates_for_item,
    check_orphaned_node,
    check_provenance,
    check_data_completeness,
    check_weight_consistency,
    apply_field_update,
    apply_brand_standardization,
    merge_duplicate_items,
    clear_invalid_brand,
    remove_brand_from_name,
    verify_brand_via_web,
    research_missing_weight,
    research_current_price,
)

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    """Current status of the hygiene agent."""

    IDLE = "idle"
    TRIAGING = "triaging"
    PROCESSING = "processing"
    PAUSED = "paused"
    ERROR = "error"


def evaluate_brand_validity(brand: str, name: str, entity_id: str) -> dict:
    """Evaluate if a brand name is valid or generic."""
    graph_result = check_brand_in_graph(brand)

    generic_terms = {
        "backpack", "tent", "bag", "ultralight", "gear", "sleeping bag",
        "down jacket", "hiking", "camping", "outdoor", "trail",
    }

    result = {
        "entity_id": entity_id,
        "brand": brand,
        "name": name,
        "is_generic": brand.lower() in generic_terms,
        "exists_in_graph": graph_result.get("brand_exists", False),
        "item_count": graph_result.get("item_count", 0),
        "similar_brands": graph_result.get("similar_brands", []),
    }

    if result["is_generic"]:
        result["recommendation"] = "clear_brand"
        result["reasoning"] = f"'{brand}' is a generic term, not a brand name"
    elif result["item_count"] >= 3:
        result["recommendation"] = "keep"
        result["reasoning"] = f"Brand has {result['item_count']} items, likely valid"
    elif result["similar_brands"]:
        result["recommendation"] = "review"
        result["reasoning"] = f"Brand not found, similar: {result['similar_brands']}"
    else:
        result["recommendation"] = "verify_web"
        result["reasoning"] = "Brand has few items, may need verification"

    return result


def evaluate_name_redundancy(brand: str, name: str, entity_id: str) -> dict:
    """Evaluate if product name redundantly contains the brand."""
    result = {
        "entity_id": entity_id,
        "brand": brand,
        "name": name,
        "contains_brand": brand.lower() in name.lower() if brand else False,
    }

    if not result["contains_brand"]:
        result["is_redundant"] = False
        result["reasoning"] = "Brand not found in name"
        result["recommendation"] = "no_action"
        return result

    name_lower = name.lower()
    brand_lower = brand.lower()

    if name_lower.startswith(brand_lower):
        potential_new_name = name[len(brand):].strip()
        if potential_new_name.startswith("-"):
            potential_new_name = potential_new_name[1:].strip()

        result["potential_new_name"] = potential_new_name
        result["needs_llm_judgment"] = True
        result["reasoning"] = (
            f"Brand '{brand}' appears at start of name. "
            f"Potential simplified name: '{potential_new_name}'. "
            f"Needs judgment to determine if redundant or part of model name."
        )
        result["recommendation"] = "needs_review"
    else:
        result["is_redundant"] = False
        result["needs_llm_judgment"] = False
        result["reasoning"] = (
            f"Brand '{brand}' appears in name but not at start. "
            f"Usually valid (product line name contains brand word)."
        )
        result["recommendation"] = "no_action"

    return result


# All agent tools
HYGIENE_TOOLS = [
    evaluate_brand_validity,
    evaluate_name_redundancy,
    check_whitespace,
    check_case_normalization,
    check_known_transcription_errors,
    check_brand_in_graph,
    find_duplicates_for_item,
    check_orphaned_node,
    check_provenance,
    check_data_completeness,
    check_weight_consistency,
    apply_field_update,
    apply_brand_standardization,
    merge_duplicate_items,
    clear_invalid_brand,
    remove_brand_from_name,
    verify_brand_via_web,
    research_missing_weight,
    research_current_price,
]


def _get_system_prompt() -> str:
    """Fetch the hygiene evaluator prompt from LangWatch."""
    try:
        prompt = langwatch.prompts.get("hygiene-evaluator")
        messages = prompt.messages if hasattr(prompt, "messages") else []
        for msg in messages:
            if msg.get("role") == "system":
                return msg.get("content", "")
    except Exception as e:
        logger.warning(f"Could not fetch LangWatch prompt: {e}")

    return _get_fallback_prompt()


def _get_fallback_prompt() -> str:
    """Fallback prompt if LangWatch is unavailable."""
    return """You are a data quality agent for a hiking/backpacking gear database.

Your role is to evaluate gear items for data hygiene issues and decide on fixes.

## Philosophy: Be Conservative
- Flag issues when uncertain rather than auto-fixing
- Understand context before suggesting changes
- "Big Agnes Big House 6" is VALID - "Big House" is the product name

## Response Format
Always respond with structured JSON:
{
    "check_id": "the check being performed",
    "issue_found": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "detailed explanation",
    "decision": "auto_fix|flag_for_review|skip|no_issue",
    "fix": null | {"field": "...", "old_value": "...", "new_value": "..."}
}
"""


class HygieneAgent:
    """LLM-based hygiene evaluation agent."""

    def __init__(
        self,
        model: str = "sonnet",
        logbook_path: Optional[str] = None,
    ):
        """Initialize the hygiene agent."""
        self.logbook = get_logbook(logbook_path)
        self.queue = get_queue()
        self.status = AgentStatus.IDLE
        self.current_item: Optional[str] = None
        self.last_error: Optional[str] = None

        self.items_processed = 0
        self.issues_found = 0
        self.fixes_applied = 0

        model_map = {
            "haiku": "claude-haiku-4-5-20251001",
            "sonnet": "claude-sonnet-4-5-20250929",
            "opus": "claude-opus-4-5-20251101",
        }
        model_id = model_map.get(model, model_map["sonnet"])

        system_prompt = _get_system_prompt()
        self._agent = Agent(
            name="HygieneAgent",
            model=Claude(id=model_id, max_tokens=4096),
            instructions=system_prompt,
            tools=HYGIENE_TOOLS,
            markdown=False,
        )

    def get_status(self) -> dict:
        """Get current agent status and statistics."""
        queue_stats = self.queue.get_statistics()
        logbook_stats = self.logbook.get_statistics()

        return {
            "status": self.status.value,
            "current_item": self.current_item,
            "last_error": self.last_error,
            "items_processed": self.items_processed,
            "issues_found": self.issues_found,
            "fixes_applied": self.fixes_applied,
            "queue": queue_stats,
            "logbook": logbook_stats,
        }

    def triage_all_items(self, limit: int = 100) -> dict:
        """Load items from database and triage into priority queue."""
        self.status = AgentStatus.TRIAGING

        try:
            query = """
            MATCH (g:GearItem)
            OPTIONAL MATCH (g)-[:EXTRACTED_FROM]->(s:VideoSource)
            OPTIONAL MATCH (g)-[:HAS_TIP]->(i:Insight)
            WITH g,
                 count(DISTINCT s) > 0 as has_sources,
                 count(DISTINCT i) > 0 as has_insights
            RETURN id(g) as id,
                   g.name as name,
                   g.brand as brand,
                   g.category as category,
                   g.weight_grams as weight_grams,
                   g.description as description,
                   g.price_usd as price_usd,
                   has_sources,
                   has_insights
            ORDER BY id(g) DESC
            LIMIT $limit
            """
            results = execute_and_fetch(query, {"limit": limit})

            if not results:
                self.status = AgentStatus.IDLE
                return {"total": 0, "triaged": 0}

            items = [dict(r) for r in results]
            queue_items = self.queue.bulk_triage(items)

            self.status = AgentStatus.IDLE

            return {
                "total": len(items),
                "triaged": len(queue_items),
                "by_priority": self.queue.get_statistics().get("by_priority", {}),
            }

        except Exception as e:
            self.status = AgentStatus.ERROR
            self.last_error = str(e)
            logger.error(f"Triage error: {e}")
            return {"total": 0, "triaged": 0, "error": str(e)}

    def process_priority_level(
        self,
        priority: CheckPriority,
        batch_size: int = 10,
    ) -> list[dict]:
        """Process items at a specific priority level."""
        self.status = AgentStatus.PROCESSING
        results = []

        try:
            items = self.queue.get_items_by_priority(priority)[:batch_size]

            for item in items:
                result = self.process_item(item)
                results.append(result)
                self.items_processed += 1

        except Exception as e:
            self.status = AgentStatus.ERROR
            self.last_error = str(e)
            logger.error(f"Processing error: {e}")

        finally:
            self.status = AgentStatus.IDLE

        return results

    def process_item(self, queue_item: QueueItem) -> dict:
        """Process a single item from the queue."""
        entity_id = queue_item.entity_id
        data = queue_item.entity_data
        name = data.get("name", "Unknown")
        brand = data.get("brand", "")

        self.current_item = f"{brand} {name}" if brand else name

        result = {
            "entity_id": entity_id,
            "name": name,
            "brand": brand,
            "checks_run": [],
            "issues_found": [],
            "fixes_applied": [],
        }

        checks = get_checks_by_priority(queue_item.priority_level)

        for check in checks:
            if check.id in queue_item.checks_completed:
                continue

            check_result = self._run_check(check.id, data, entity_id)
            result["checks_run"].append(check.id)

            if check_result.get("issue_found"):
                result["issues_found"].append(check_result)
                self.issues_found += 1

            if check_result.get("fix_applied"):
                result["fixes_applied"].append(check_result.get("fix"))
                self.fixes_applied += 1

            queue_item.checks_completed.append(check.id)

        self.queue.mark_completed(
            queue_item.id,
            issues=result["issues_found"],
            fixes=result["fixes_applied"],
        )

        self.current_item = None
        return result

    def _run_check(self, check_id: str, data: dict, entity_id: str) -> dict:
        """Run a specific check on an item."""
        check = get_check_by_id(check_id)
        if not check:
            return {"error": f"Unknown check: {check_id}"}

        name = data.get("name", "")
        brand = data.get("brand", "")

        # P1 checks
        if check_id == "whitespace_check":
            result = check_whitespace(name, brand)
            return handle_p1_check(result, entity_id, name, check_id)

        elif check_id == "case_check":
            result = check_case_normalization(name, brand)
            return handle_p1_check(result, entity_id, name, check_id)

        # P2 checks
        elif check_id == "invalid_brand":
            result = evaluate_brand_validity(brand, name, entity_id)
            return handle_p2_check(result, entity_id, name, check_id)

        elif check_id == "brand_in_name":
            result = evaluate_name_redundancy(brand, name, entity_id)
            return handle_p2_check(result, entity_id, name, check_id)

        # P3 checks
        elif check_id == "brand_exists":
            result = check_brand_in_graph(brand)
            return handle_p3_check(result, entity_id, name, brand, check_id)

        elif check_id == "potential_duplicate":
            result = find_duplicates_for_item(name, brand)
            return handle_duplicate_check(result, entity_id, name, brand)

        elif check_id == "transcription_error":
            result = check_known_transcription_errors(name, brand)
            return handle_p1_check(result, entity_id, name, check_id)

        # P4 checks
        elif check_id == "verify_brand":
            result = verify_brand_via_web(brand)
            return handle_research_check(result, entity_id, name, brand, check_id)

        elif check_id == "missing_price":
            # Skip for now - price research not yet implemented
            return {"issue_found": False, "reasoning": "Price research not yet implemented"}

        elif check_id == "missing_weight":
            if not data.get("weight_grams"):
                result = research_missing_weight(name, brand)
                return handle_research_check(result, entity_id, name, brand, check_id)
            return {"issue_found": False, "reasoning": "Weight already present"}

        # P5 checks
        elif check_id == "orphaned_node":
            result = check_orphaned_node(entity_id)
            return handle_deep_check(result, entity_id, name, check_id)

        elif check_id == "missing_provenance":
            result = check_provenance(entity_id)
            return handle_deep_check(result, entity_id, name, check_id)

        elif check_id == "data_completeness":
            result = check_data_completeness(data)
            return handle_deep_check(result, entity_id, name, check_id)

        elif check_id == "copyright_concern":
            # Skip for now - requires LLM evaluation of description
            return {"issue_found": False, "reasoning": "Copyright check not yet implemented"}

        return {"error": f"Unhandled check: {check_id}"}

    def evaluate_item_comprehensive(
        self,
        name: str,
        brand: str,
        entity_id: Optional[str] = None,
    ) -> dict:
        """Run full LLM-based comprehensive evaluation on an item."""
        prompt = f"""Evaluate this gear item for data quality issues:

**Name:** {name}
**Brand:** {brand}
**Entity ID:** {entity_id or 'N/A'}

Use the available tools to check:
1. evaluate_brand_validity - Is the brand valid or generic?
2. evaluate_name_redundancy - Does the name redundantly contain the brand?
3. check_brand_in_graph - How many items have this brand?
4. find_duplicates_for_item - Are there potential duplicates?
5. check_data_completeness - What data is missing?

Be conservative - flag for review rather than auto-fix when uncertain.

IMPORTANT: "Big Agnes Big House 6" is VALID - "Big House" is the product name.
"""

        response = self._agent.run(prompt)
        return {
            "name": name,
            "brand": brand,
            "entity_id": entity_id,
            "evaluation": str(response.content) if response.content else "",
        }

    def process_batch_streaming(
        self,
        batch_size: int = 10,
        on_progress: Optional[Callable[[str, str], None]] = None,
    ) -> Iterator[dict]:
        """Process a batch with streaming progress updates."""
        self.status = AgentStatus.PROCESSING

        yield {"event": "started", "detail": "Loading items..."}

        if self.queue.get_statistics()["pending"] == 0:
            yield {"event": "progress", "detail": "Triaging items..."}
            self.triage_all_items(limit=batch_size * 2)

        batch = self.queue.get_next_batch(batch_size)

        for i, item in enumerate(batch):
            name = item.entity_data.get("name", "Unknown")
            brand = item.entity_data.get("brand", "")

            yield {
                "event": "processing",
                "detail": f"[{i+1}/{len(batch)}] {brand} {name}",
                "item": {"name": name, "brand": brand},
            }

            if on_progress:
                on_progress("processing", f"{brand} {name}")

            result = self.process_item(item)

            yield {
                "event": "item_complete",
                "detail": f"Completed: {name}",
                "result": result,
            }

        self.status = AgentStatus.IDLE
        yield {
            "event": "completed",
            "detail": f"Processed {len(batch)} items",
            "stats": self.get_status(),
        }


# Global agent instance
_hygiene_agent: Optional[HygieneAgent] = None


def get_hygiene_agent(model: str = "sonnet") -> HygieneAgent:
    """Get or create the global hygiene agent instance."""
    global _hygiene_agent
    if _hygiene_agent is None:
        _hygiene_agent = HygieneAgent(model=model)
    return _hygiene_agent


def reset_hygiene_agent():
    """Reset the global agent (for testing)."""
    global _hygiene_agent
    _hygiene_agent = None
