"""Video tracking system for monitoring processed videos."""

import json
from pathlib import Path
from typing import Set
from datetime import datetime


class VideoTracker:
    """Track which videos have been processed."""

    def __init__(self, tracking_file: str = "data/processed_videos.json"):
        """Initialize video tracker.

        Args:
            tracking_file: Path to JSON file storing processed video IDs
        """
        self.tracking_file = Path(tracking_file)
        self.tracking_file.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self) -> None:
        """Load processed video data from file."""
        if self.tracking_file.exists():
            with open(self.tracking_file, "r") as f:
                data = json.load(f)
                self.processed_videos = set(data.get("video_ids", []))
                self.last_check = data.get("last_check")
        else:
            self.processed_videos: Set[str] = set()
            self.last_check = None

    def _save(self) -> None:
        """Save processed video data to file."""
        data = {
            "video_ids": sorted(list(self.processed_videos)),
            "last_check": datetime.now().isoformat(),
            "total_processed": len(self.processed_videos),
        }
        with open(self.tracking_file, "w") as f:
            json.dump(data, f, indent=2)

    def is_processed(self, video_id: str) -> bool:
        """Check if a video has been processed.

        Args:
            video_id: YouTube video ID

        Returns:
            True if video has been processed
        """
        return video_id in self.processed_videos

    def mark_processed(self, video_id: str) -> None:
        """Mark a video as processed.

        Args:
            video_id: YouTube video ID
        """
        self.processed_videos.add(video_id)
        self._save()

    def get_new_videos(self, all_videos: list[dict]) -> list[dict]:
        """Filter out already-processed videos.

        Args:
            all_videos: List of video dicts with 'video_id' key

        Returns:
            List of videos that haven't been processed yet
        """
        return [
            video for video in all_videos
            if not self.is_processed(video["video_id"])
        ]

    def get_stats(self) -> dict:
        """Get tracking statistics.

        Returns:
            Dict with total_processed and last_check timestamp
        """
        return {
            "total_processed": len(self.processed_videos),
            "last_check": self.last_check,
        }
