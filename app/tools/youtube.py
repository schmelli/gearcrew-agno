"""YouTube transcript extraction tool."""

import re
from typing import Optional
from youtube_transcript_api import YouTubeTranscriptApi


def extract_video_id(url_or_id: str) -> Optional[str]:
    """Extract YouTube video ID from URL or return as-is if already an ID.

    Args:
        url_or_id: YouTube URL or video ID

    Returns:
        Video ID or None if extraction failed
    """
    if len(url_or_id) == 11 and not url_or_id.startswith("http"):
        return url_or_id

    patterns = [
        r"(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})",
        r"youtube\.com\/shorts\/([a-zA-Z0-9_-]{11})",
    ]

    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)

    return None


def get_youtube_transcript(url_or_id: str, languages: list[str] = None) -> str:
    """Fetch transcript from a YouTube video.

    Args:
        url_or_id: YouTube video URL or ID
        languages: Preferred languages (default: ['en'])

    Returns:
        Full transcript text

    Raises:
        ValueError: If video ID cannot be extracted or transcript unavailable
    """
    if languages is None:
        languages = ["en"]

    video_id = extract_video_id(url_or_id)
    if not video_id:
        raise ValueError(f"Could not extract video ID from: {url_or_id}")

    try:
        ytt = YouTubeTranscriptApi()

        # Try to fetch transcript with preferred languages
        try:
            transcript_data = ytt.fetch(video_id, languages=languages)
        except Exception:
            # Fall back to any available transcript
            transcript_data = ytt.fetch(video_id)

        # Extract text from transcript snippets
        full_text = " ".join(
            snippet.text for snippet in transcript_data
        )
        return full_text

    except Exception as e:
        error_msg = str(e).lower()
        if "disabled" in error_msg:
            raise ValueError(f"Transcripts are disabled for video: {video_id}")
        elif "unavailable" in error_msg or "not found" in error_msg:
            raise ValueError(f"Video unavailable or no transcript: {video_id}")
        else:
            raise ValueError(f"Error fetching transcript for {video_id}: {str(e)}")
