"""Background task queue for agent extractions.

Allows agent tasks to run in the background while the user navigates
between views in the Streamlit app.
"""

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Callable, Any
import queue


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    """Represents a background task."""
    id: str
    description: str
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    model_tier: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        """Get task duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        elif self.started_at:
            return (datetime.now() - self.started_at).total_seconds()
        return None


class TaskQueue:
    """Thread-safe task queue for background processing."""

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._task_queue: queue.Queue = queue.Queue()

    def submit(self, prompt: str, description: str = "Processing...") -> str:
        """Submit a new task to the queue.

        Args:
            prompt: The prompt to send to the agent
            description: Human-readable task description

        Returns:
            Task ID
        """
        task_id = str(uuid.uuid4())[:8]
        task = Task(
            id=task_id,
            description=description,
            prompt=prompt,
        )

        with self._lock:
            self._tasks[task_id] = task

        self._task_queue.put(task_id)
        self._ensure_worker_running()

        return task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[Task]:
        """Get all tasks, newest first."""
        with self._lock:
            return sorted(
                self._tasks.values(),
                key=lambda t: t.created_at,
                reverse=True
            )

    def get_active_tasks(self) -> list[Task]:
        """Get tasks that are pending or running."""
        with self._lock:
            return [
                t for t in self._tasks.values()
                if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
            ]

    def get_recent_completed(self, limit: int = 5) -> list[Task]:
        """Get recently completed tasks."""
        with self._lock:
            completed = [
                t for t in self._tasks.values()
                if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
            ]
            return sorted(
                completed,
                key=lambda t: t.completed_at or t.created_at,
                reverse=True
            )[:limit]

    def clear_completed(self):
        """Remove completed and failed tasks from history."""
        with self._lock:
            self._tasks = {
                tid: task for tid, task in self._tasks.items()
                if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
            }

    def _ensure_worker_running(self):
        """Start the worker thread if not already running."""
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._stop_event.clear()
            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                daemon=True
            )
            self._worker_thread.start()

    def _worker_loop(self):
        """Background worker that processes tasks."""
        while not self._stop_event.is_set():
            try:
                # Wait for a task with timeout to allow checking stop event
                try:
                    task_id = self._task_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                task = self.get_task(task_id)
                if task is None:
                    continue

                # Update task status
                with self._lock:
                    task.status = TaskStatus.RUNNING
                    task.started_at = datetime.now()

                try:
                    # Import here to avoid circular imports
                    from app.agent import run_agent_chat_with_tier

                    response, model_tier = run_agent_chat_with_tier(task.prompt)

                    with self._lock:
                        task.status = TaskStatus.COMPLETED
                        task.result = response
                        task.model_tier = model_tier
                        task.completed_at = datetime.now()

                except Exception as e:
                    with self._lock:
                        task.status = TaskStatus.FAILED
                        task.error = str(e)
                        task.completed_at = datetime.now()

                self._task_queue.task_done()

            except Exception as e:
                # Log but don't crash the worker
                print(f"Worker error: {e}")

    def stop(self):
        """Stop the worker thread."""
        self._stop_event.set()
        if self._worker_thread:
            self._worker_thread.join(timeout=5.0)


# Global task queue instance
_task_queue: Optional[TaskQueue] = None


def get_task_queue() -> TaskQueue:
    """Get or create the global task queue."""
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue()
    return _task_queue
