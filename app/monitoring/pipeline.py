"""Automated playlist monitoring and processing pipeline."""

import os
from typing import Optional
from datetime import datetime

from app.tools.youtube import get_playlist_videos, get_playlist_info
from app.monitoring.tracker import VideoTracker
from app.monitoring.notifier import EmailNotifier
from app.agent import run_agent_chat


class PlaylistMonitor:
    """Monitor YouTube playlist and process new videos."""

    def __init__(
        self,
        playlist_url: str,
        tracker: Optional[VideoTracker] = None,
        notifier: Optional[EmailNotifier] = None,
    ):
        """Initialize playlist monitor.

        Args:
            playlist_url: YouTube playlist URL to monitor
            tracker: Video tracker instance (default: creates new one)
            notifier: Email notifier instance (default: creates new one if env vars set)
        """
        self.playlist_url = playlist_url
        self.tracker = tracker or VideoTracker()

        # Only create notifier if email is configured
        try:
            self.notifier = notifier or EmailNotifier()
        except ValueError:
            print("⚠️  Email not configured. Set SENDER_EMAIL, SENDER_PASSWORD, and RECIPIENT_EMAIL env vars.")
            self.notifier = None

    def check_and_process(self, dry_run: bool = False) -> dict:
        """Check playlist for new videos and process them.

        Args:
            dry_run: If True, only identify new videos without processing

        Returns:
            Dict with statistics: new_videos, processed, failed, gear_extracted
        """
        print(f"🔍 Checking playlist: {self.playlist_url}")

        # Fetch playlist info
        try:
            playlist_info = get_playlist_info(self.playlist_url)
            print(f"📋 Playlist: {playlist_info['title']}")
            print(f"📊 Total videos: {playlist_info['video_count']}")
        except Exception as e:
            print(f"❌ Failed to fetch playlist info: {e}")
            return {"error": str(e)}

        # Fetch all videos
        try:
            all_videos = get_playlist_videos(self.playlist_url)
        except Exception as e:
            print(f"❌ Failed to fetch playlist videos: {e}")
            return {"error": str(e)}

        # Identify new videos
        new_videos = self.tracker.get_new_videos(all_videos)
        print(f"🆕 New videos found: {len(new_videos)}")

        if len(new_videos) == 0:
            print("✅ No new videos to process")

            # Send heartbeat notification
            if self.notifier:
                self.notifier.send_heartbeat(
                    playlist_title=playlist_info["title"],
                    total_videos=playlist_info["video_count"],
                    tracked_videos=len(all_videos) - len(new_videos),
                )

            return {
                "new_videos": 0,
                "processed": 0,
                "failed": 0,
                "gear_extracted": 0,
            }

        if dry_run:
            print("\n🏃 Dry run mode - skipping processing")
            for video in new_videos:
                print(f"  • {video['title']}")
            return {
                "new_videos": len(new_videos),
                "processed": 0,
                "failed": 0,
                "gear_extracted": 0,
            }

        # Process each new video
        stats = {
            "new_videos": len(new_videos),
            "processed": 0,
            "failed": 0,
            "gear_extracted": 0,
        }

        for i, video in enumerate(new_videos, 1):
            print(f"\n📹 Processing video {i}/{len(new_videos)}: {video['title']}")
            print(f"🔗 {video['url']}")

            try:
                result = self._process_video(video)
                stats["processed"] += 1
                stats["gear_extracted"] += result["gear_count"]

                # Mark as processed
                self.tracker.mark_processed(video["video_id"])
                print(f"✅ Successfully processed - {result['gear_count']} gear items extracted")

                # Send individual notification
                if self.notifier:
                    self.notifier.send_processing_report(
                        video_title=video["title"],
                        video_url=video["url"],
                        gear_items=result.get("gear_items", []),
                        insights=result.get("insights", []),
                        success=True,
                    )

            except Exception as e:
                stats["failed"] += 1
                print(f"❌ Failed to process: {e}")

                # Send error notification
                if self.notifier:
                    self.notifier.send_processing_report(
                        video_title=video["title"],
                        video_url=video["url"],
                        gear_items=[],
                        insights=[],
                        success=False,
                        error_message=str(e),
                    )

        # Send summary report
        if self.notifier and stats["new_videos"] > 0:
            self.notifier.send_summary_report(
                playlist_title=playlist_info["title"],
                new_videos_count=stats["new_videos"],
                successful_count=stats["processed"],
                failed_count=stats["failed"],
                total_gear_extracted=stats["gear_extracted"],
            )

        print(f"\n📊 Summary:")
        print(f"  • New videos: {stats['new_videos']}")
        print(f"  • Processed: {stats['processed']}")
        print(f"  • Failed: {stats['failed']}")
        print(f"  • Gear extracted: {stats['gear_extracted']}")

        return stats

    def _process_video(self, video: dict) -> dict:
        """Process a single video with the agent.

        Args:
            video: Video dict with url, title, etc.

        Returns:
            Dict with gear_count, gear_items, insights

        Raises:
            Exception: If processing fails
        """
        # Use the agent to process the video
        message = f"Please extract all gear information from this YouTube video: {video['url']}"

        result = run_agent_chat(message)

        # Parse the result to extract gear items and insights
        # This is a simple implementation - you may want to enhance this
        gear_items = self._extract_gear_items_from_result(result)
        insights = self._extract_insights_from_result(result)

        return {
            "gear_count": len(gear_items),
            "gear_items": gear_items,
            "insights": insights,
        }

    def _extract_gear_items_from_result(self, result: str) -> list[str]:
        """Extract gear item names from agent result.

        Args:
            result: Agent response text

        Returns:
            List of gear item names
        """
        # Simple extraction - look for lines that might be gear items
        # This is a basic implementation - enhance as needed
        gear_items = []
        lines = result.split("\n")

        for line in lines:
            line = line.strip()
            # Look for lines that mention brand names or gear patterns
            if any(keyword in line.lower() for keyword in ["tent", "bag", "pack", "jacket", "shoe", "boot", "stove", "filter"]):
                gear_items.append(line[:100])  # Limit length

        return gear_items[:100]  # Allow up to 100 items for reporting

    def _extract_insights_from_result(self, result: str) -> list[str]:
        """Extract key insights from agent result.

        Args:
            result: Agent response text

        Returns:
            List of insight strings
        """
        # Simple extraction - look for insight-like content
        insights = []
        lines = result.split("\n")

        for line in lines:
            line = line.strip()
            # Look for lines that contain insights/recommendations
            if any(keyword in line.lower() for keyword in ["recommends", "suggests", "tip", "advice", "important", "note"]):
                insights.append(line[:200])  # Limit length

        return insights[:50]  # Allow up to 50 insights for reporting


def run_monitoring(
    playlist_url: str = None,
    dry_run: bool = False,
) -> dict:
    """Run playlist monitoring (convenience function).

    Args:
        playlist_url: Playlist URL (default: from PLAYLIST_URL env var)
        dry_run: If True, only check for new videos without processing

    Returns:
        Processing statistics
    """
    if playlist_url is None:
        playlist_url = os.getenv("PLAYLIST_URL")
        if not playlist_url:
            raise ValueError("No playlist URL provided. Set PLAYLIST_URL env var or pass as argument.")

    monitor = PlaylistMonitor(playlist_url)
    return monitor.check_and_process(dry_run=dry_run)
