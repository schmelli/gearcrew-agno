"""Priority-based work queue for hygiene processing."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from heapq import heappush, heappop
import uuid

from app.hygiene.checklist import CheckPriority, HYGIENE_CHECKLIST


class ItemStatus(Enum):
    """Status of an item in the queue."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    DEFERRED = "deferred"
    FAILED = "failed"


@dataclass(order=True)
class QueueItem:
    """An item in the priority queue."""

    # Priority for heap ordering (lower = higher priority)
    sort_priority: int = field(compare=True)

    # Item details (not used for comparison)
    id: str = field(default_factory=lambda: str(uuid.uuid4()), compare=False)
    entity_type: str = field(default="GearItem", compare=False)
    entity_id: str = field(default="", compare=False)
    entity_data: dict = field(default_factory=dict, compare=False)

    # Processing metadata
    priority_level: CheckPriority = field(
        default=CheckPriority.P3_CONTEXT, compare=False
    )
    checks_to_run: list[str] = field(default_factory=list, compare=False)
    checks_completed: list[str] = field(default_factory=list, compare=False)

    status: ItemStatus = field(default=ItemStatus.PENDING, compare=False)
    added_at: datetime = field(default_factory=datetime.now, compare=False)
    started_at: Optional[datetime] = field(default=None, compare=False)
    completed_at: Optional[datetime] = field(default=None, compare=False)

    # Issue tracking
    issues_found: list[dict] = field(default_factory=list, compare=False)
    fixes_applied: list[dict] = field(default_factory=list, compare=False)

    # Score for prioritization
    hygiene_score: float = field(default=1.0, compare=False)  # 1.0=clean, 0.0=dirty


class HygieneQueue:
    """Priority queue for hygiene processing.

    Items are processed in priority order:
    - P1 (Instant) items are processed first
    - Within each priority, items with lower hygiene scores are processed first
    """

    def __init__(self):
        """Initialize the queue."""
        self._heap: list[QueueItem] = []
        self._items_by_id: dict[str, QueueItem] = {}
        self._entity_index: dict[str, str] = {}  # entity_id -> queue_item_id

    def add_item(
        self,
        entity_type: str,
        entity_id: str,
        entity_data: dict,
        initial_priority: CheckPriority = CheckPriority.P3_CONTEXT,
        hygiene_score: float = 1.0,
    ) -> QueueItem:
        """Add an item to the queue.

        Args:
            entity_type: Type of entity (GearItem, etc.)
            entity_id: Database ID
            entity_data: Entity properties
            initial_priority: Starting priority level
            hygiene_score: Initial cleanliness score (0-1, lower=dirtier)

        Returns:
            The created QueueItem
        """
        # Check if already in queue
        if entity_id in self._entity_index:
            return self._items_by_id[self._entity_index[entity_id]]

        # Determine which checks to run based on priority
        checks = [
            c.id for c in HYGIENE_CHECKLIST if c.priority.value <= initial_priority.value
        ]

        # Calculate sort priority (combines priority level and hygiene score)
        # Lower score = processed sooner
        sort_priority = initial_priority.value * 1000 + int(hygiene_score * 100)

        item = QueueItem(
            sort_priority=sort_priority,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_data=entity_data,
            priority_level=initial_priority,
            checks_to_run=checks,
            hygiene_score=hygiene_score,
        )

        heappush(self._heap, item)
        self._items_by_id[item.id] = item
        self._entity_index[entity_id] = item.id

        return item

    def get_next(self) -> Optional[QueueItem]:
        """Get the next item to process.

        Returns:
            Next item or None if queue empty
        """
        while self._heap:
            item = heappop(self._heap)

            # Skip if already completed or in progress
            if item.status in [ItemStatus.COMPLETED, ItemStatus.IN_PROGRESS]:
                continue

            item.status = ItemStatus.IN_PROGRESS
            item.started_at = datetime.now()
            return item

        return None

    def get_next_batch(self, batch_size: int = 10) -> list[QueueItem]:
        """Get a batch of items to process.

        Args:
            batch_size: Maximum items to return

        Returns:
            List of items to process
        """
        items = []
        for _ in range(batch_size):
            item = self.get_next()
            if item is None:
                break
            items.append(item)
        return items

    def get_items_by_priority(self, priority: CheckPriority) -> list[QueueItem]:
        """Get all pending items at a specific priority level."""
        return [
            self._items_by_id[item.id]
            for item in self._heap
            if item.priority_level == priority and item.status == ItemStatus.PENDING
        ]

    def get_item_by_entity_id(self, entity_id: str) -> Optional[QueueItem]:
        """Get queue item for a specific entity.

        Args:
            entity_id: Database ID

        Returns:
            QueueItem or None
        """
        if entity_id in self._entity_index:
            return self._items_by_id.get(self._entity_index[entity_id])
        return None

    def mark_completed(
        self,
        item_id: str,
        issues: Optional[list[dict]] = None,
        fixes: Optional[list[dict]] = None,
    ):
        """Mark an item as completed.

        Args:
            item_id: Queue item ID
            issues: Issues found during processing
            fixes: Fixes applied
        """
        if item_id not in self._items_by_id:
            return

        item = self._items_by_id[item_id]
        item.status = ItemStatus.COMPLETED
        item.completed_at = datetime.now()

        if issues:
            item.issues_found = issues
        if fixes:
            item.fixes_applied = fixes

    def mark_failed(self, item_id: str, error: str = ""):
        """Mark an item as failed."""
        if item_id not in self._items_by_id:
            return
        item = self._items_by_id[item_id]
        item.status = ItemStatus.FAILED

    def defer_item(self, item_id: str, new_priority: CheckPriority):
        """Defer an item to a later priority level.

        Args:
            item_id: Queue item ID
            new_priority: New priority level (should be higher number)
        """
        if item_id not in self._items_by_id:
            return

        item = self._items_by_id[item_id]
        item.status = ItemStatus.PENDING
        item.priority_level = new_priority
        item.sort_priority = new_priority.value * 1000 + int(item.hygiene_score * 100)

        # Re-add to heap
        heappush(self._heap, item)

    def escalate_priority(self, item_id: str, new_priority: CheckPriority):
        """Escalate an item to a higher priority.

        Args:
            item_id: Queue item ID
            new_priority: New priority (lower number = higher priority)
        """
        if item_id not in self._items_by_id:
            return

        item = self._items_by_id[item_id]

        # Add additional checks for the new priority level
        new_checks = [
            c.id
            for c in HYGIENE_CHECKLIST
            if c.priority == new_priority and c.id not in item.checks_to_run
        ]
        item.checks_to_run.extend(new_checks)

        item.priority_level = new_priority
        item.sort_priority = new_priority.value * 1000 + int(item.hygiene_score * 100)
        item.status = ItemStatus.PENDING

        heappush(self._heap, item)

    def get_statistics(self) -> dict:
        """Get queue statistics."""
        total = len(self._items_by_id)
        by_status: dict[str, int] = {}
        by_priority: dict[str, int] = {}

        for item in self._items_by_id.values():
            status = item.status.value
            by_status[status] = by_status.get(status, 0) + 1

            priority = f"P{item.priority_level.value}"
            by_priority[priority] = by_priority.get(priority, 0) + 1

        pending_count = sum(1 for item in self._heap if item.status == ItemStatus.PENDING)

        issues_total = sum(len(item.issues_found) for item in self._items_by_id.values())
        fixes_total = sum(len(item.fixes_applied) for item in self._items_by_id.values())

        return {
            "total_items": total,
            "pending": pending_count,
            "by_status": by_status,
            "by_priority": by_priority,
            "total_issues_found": issues_total,
            "total_fixes_applied": fixes_total,
        }

    def bulk_triage(self, items: list[dict]) -> list[QueueItem]:
        """Triage multiple items and add to queue based on initial assessment.

        Args:
            items: List of entity data dicts with at least 'name', 'brand', 'id'

        Returns:
            List of created QueueItems
        """
        queue_items = []

        for item_data in items:
            # Calculate initial hygiene score
            score = self._calculate_initial_score(item_data)

            # Determine initial priority based on score and data completeness
            if score < 0.3:
                priority = CheckPriority.P2_QUICK  # Needs immediate attention
            elif score < 0.6:
                priority = CheckPriority.P3_CONTEXT  # Needs investigation
            elif score < 0.8:
                priority = CheckPriority.P4_RESEARCH  # Needs enrichment
            else:
                priority = CheckPriority.P5_DEEP  # Just deep checks

            queue_item = self.add_item(
                entity_type=item_data.get("entity_type", "GearItem"),
                entity_id=str(item_data.get("id", item_data.get("node_id", ""))),
                entity_data=item_data,
                initial_priority=priority,
                hygiene_score=score,
            )
            queue_items.append(queue_item)

        return queue_items

    def _calculate_initial_score(self, item: dict) -> float:
        """Calculate initial hygiene score for triage.

        Higher score = cleaner data (needs less work)
        """
        score = 1.0
        penalties = []

        # Check for common issues
        name = item.get("name", "")
        brand = item.get("brand", "")

        # Whitespace issues
        if name != name.strip() or "  " in name:
            score -= 0.1
            penalties.append("whitespace")

        # Missing brand
        if not brand:
            score -= 0.2
            penalties.append("no_brand")

        # Brand looks generic
        generic_terms = {
            "backpack",
            "tent",
            "bag",
            "ultralight",
            "gear",
            "sleeping bag",
            "down jacket",
        }
        if brand.lower() in generic_terms:
            score -= 0.3
            penalties.append("generic_brand")

        # Brand in name (potential redundancy) - light penalty, needs evaluation
        if brand and brand.lower() in name.lower():
            score -= 0.05  # Light penalty - agent will evaluate
            penalties.append("brand_in_name_candidate")

        # Missing key data
        if not item.get("weight_grams"):
            score -= 0.1
            penalties.append("no_weight")

        if not item.get("description"):
            score -= 0.1
            penalties.append("no_description")

        if not item.get("category"):
            score -= 0.05
            penalties.append("no_category")

        # Has relationships (good sign)
        if item.get("has_sources") or item.get("has_insights"):
            score += 0.1

        return max(0.0, min(1.0, score))

    def clear(self):
        """Clear the queue (for testing)."""
        self._heap = []
        self._items_by_id = {}
        self._entity_index = {}


# Global queue instance
_queue: Optional[HygieneQueue] = None


def get_queue() -> HygieneQueue:
    """Get or create the global queue instance."""
    global _queue
    if _queue is None:
        _queue = HygieneQueue()
    return _queue


def reset_queue():
    """Reset the global queue (for testing)."""
    global _queue
    _queue = None
