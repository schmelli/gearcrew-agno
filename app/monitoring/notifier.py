"""Email notification system for monitoring alerts."""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional


class EmailNotifier:
    """Send email notifications about processed videos."""

    def __init__(
        self,
        smtp_server: Optional[str] = None,
        smtp_port: Optional[int] = None,
        sender_email: Optional[str] = None,
        sender_password: Optional[str] = None,
        recipient_email: Optional[str] = None,
    ):
        """Initialize email notifier.

        Args:
            smtp_server: SMTP server address (default: from SMTP_SERVER env var)
            smtp_port: SMTP server port (default: from SMTP_PORT env var or 587)
            sender_email: Sender email address (default: from SENDER_EMAIL env var)
            sender_password: Sender email password (default: from SENDER_PASSWORD env var)
            recipient_email: Recipient email address (default: from RECIPIENT_EMAIL env var)
        """
        self.smtp_server = smtp_server or os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = smtp_port or int(os.getenv("SMTP_PORT", "587"))
        self.sender_email = sender_email or os.getenv("SENDER_EMAIL")
        self.sender_password = sender_password or os.getenv("SENDER_PASSWORD")
        self.recipient_email = recipient_email or os.getenv("RECIPIENT_EMAIL")

        if not all([self.sender_email, self.sender_password, self.recipient_email]):
            raise ValueError(
                "Email configuration incomplete. Set SENDER_EMAIL, SENDER_PASSWORD, "
                "and RECIPIENT_EMAIL environment variables."
            )

    def send_processing_report(
        self,
        video_title: str,
        video_url: str,
        gear_items: list[str],
        insights: list[str],
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> bool:
        """Send email report about video processing.

        Args:
            video_title: Title of the processed video
            video_url: URL of the video
            gear_items: List of extracted gear item names
            insights: List of key insights extracted
            success: Whether processing was successful
            error_message: Error message if processing failed

        Returns:
            True if email sent successfully
        """
        subject = f"{'✅' if success else '❌'} Gear Extraction: {video_title}"

        # Build email body
        if success:
            body = self._build_success_email(
                video_title, video_url, gear_items, insights
            )
        else:
            body = self._build_error_email(video_title, video_url, error_message)

        return self._send_email(subject, body)

    def _build_success_email(
        self,
        video_title: str,
        video_url: str,
        gear_items: list[str],
        insights: list[str],
    ) -> str:
        """Build success email body."""
        gear_list = "\n".join(f"  • {item}" for item in gear_items) if gear_items else "  None extracted"
        insights_list = "\n".join(f"  • {insight[:200]}..." if len(insight) > 200 else f"  • {insight}" for insight in insights) if insights else "  None extracted"

        return f"""
New video processed from your monitored playlist!

📹 Video: {video_title}
🔗 URL: {video_url}

🎒 Gear Items Extracted ({len(gear_items)}):
{gear_list}

💡 Key Insights ({len(insights)}):
{insights_list}

---
This is an automated notification from GearCrew Agno.
View the full data in your GearGraph database.
"""

    def _build_error_email(
        self,
        video_title: str,
        video_url: str,
        error_message: Optional[str],
    ) -> str:
        """Build error email body."""
        return f"""
Failed to process video from your monitored playlist.

📹 Video: {video_title}
🔗 URL: {video_url}

❌ Error:
{error_message or "Unknown error occurred"}

---
This is an automated notification from GearCrew Agno.
Please check the logs for more details.
"""

    def _send_email(self, subject: str, body: str) -> bool:
        """Send email via SMTP.

        Args:
            subject: Email subject
            body: Email body text

        Returns:
            True if sent successfully
        """
        try:
            msg = MIMEMultipart()
            msg["From"] = self.sender_email
            msg["To"] = self.recipient_email
            msg["Subject"] = subject

            msg.attach(MIMEText(body, "plain"))

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.send_message(msg)

            return True

        except Exception as e:
            print(f"Failed to send email: {e}")
            return False

    def send_summary_report(
        self,
        playlist_title: str,
        new_videos_count: int,
        successful_count: int,
        failed_count: int,
        total_gear_extracted: int,
    ) -> bool:
        """Send summary report for monitoring run.

        Args:
            playlist_title: Name of the monitored playlist
            new_videos_count: Number of new videos found
            successful_count: Number successfully processed
            failed_count: Number that failed processing
            total_gear_extracted: Total gear items extracted

        Returns:
            True if email sent successfully
        """
        if new_videos_count == 0:
            # Don't send email if no new videos
            return True

        subject = f"📊 Playlist Monitoring Summary: {playlist_title}"

        body = f"""
Playlist monitoring run completed.

📋 Playlist: {playlist_title}

📊 Summary:
  • New videos found: {new_videos_count}
  • Successfully processed: {successful_count}
  • Failed: {failed_count}
  • Total gear items extracted: {total_gear_extracted}

---
This is an automated summary from GearCrew Agno.
"""

        return self._send_email(subject, body)

    def send_heartbeat(
        self,
        playlist_title: str,
        total_videos: int,
        tracked_videos: int,
    ) -> bool:
        """Send heartbeat notification when no new videos found.

        Args:
            playlist_title: Name of the monitored playlist
            total_videos: Total videos in playlist
            tracked_videos: Number of videos already processed

        Returns:
            True if email sent successfully
        """
        subject = f"💚 Playlist Monitor Active: {playlist_title}"

        body = f"""
Playlist monitoring check completed - no new videos found.

📋 Playlist: {playlist_title}

📊 Status:
  • Total videos in playlist: {total_videos}
  • Already processed: {tracked_videos}
  • New videos: 0

✅ Everything is up to date! Will check again in 6 hours.

---
This is an automated heartbeat from GearCrew Agno.
"""

        return self._send_email(subject, body)
