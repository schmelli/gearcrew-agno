"""Automated playlist monitoring and processing pipeline."""

import os
from typing import Optional
from datetime import datetime

from app.tools.youtube import get_playlist_videos, get_playlist_info, get_video_details
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
        # Fetch full video details INCLUDING DESCRIPTION (critical for gear lists!)
        video_details = None
        description_text = ""
        try:
            video_details = get_video_details(video['url'])
            description_text = video_details.get('description', '')
            print(f"  📝 Video description: {len(description_text)} chars")
        except Exception as e:
            print(f"  ⚠️ Could not fetch video details: {e}")

        # Use the agent to process the video with a comprehensive extraction prompt
        message = f"""# Wissens-Extraktion aus YouTube-Video

**Video:** {video['title']}
**URL:** {video['url']}
**Channel:** {video.get('channel', 'Unknown')}

## VIDEO-BESCHREIBUNG (WICHTIG - enthält oft vollständige Gear-Listen!):

```
{description_text[:8000] if description_text else "Keine Beschreibung verfügbar"}
```

## DEINE AUFGABE: Extrahiere ALLES wertvolle Wissen!

Der GearGraph ist ein **WISSENS-GRAPH**, nicht nur eine Produktdatenbank!

### 0. VIDEO-BESCHREIBUNG PARSEN (ZUERST!)
**Die Beschreibung oben enthält oft eine VOLLSTÄNDIGE Gear-Liste!**
- Parse ALLE Produkte aus der Beschreibung (Brand + Produktname)
- Links zeigen exakte Produkte (Amazon, Hersteller-Links)
- Gewichte stehen oft dabei (z.B. "1 lb 7.6 oz")
- Kategorien sind oft schon gegliedert (Pack, Shelter, Sleep System, etc.)
- **JEDES Produkt aus der Beschreibung = 1x `save_gear_to_graph()`**

### 0b. TRANSCRIPT HOLEN & ZWEI-PASS-VERIFIZIERUNG (PFLICHT!)

**⚠️ WICHTIG: Die Beschreibung hat nur {len(description_text)} Zeichen!**
{"🔴 KURZE BESCHREIBUNG ERKANNT! Du MUSST die Zwei-Pass-Verifizierung für JEDES Produkt aus dem Transcript nutzen!" if len(description_text) < 1000 else "Die Beschreibung enthält möglicherweise eine Gear-Liste. Prüfe trotzdem das Transcript!"}

**SCHRITT 1: Transcript holen (PFLICHT)**
```
fetch_youtube_transcript("{video['url']}")
```

**SCHRITT 2: Produkt-Kandidaten sammeln**
Suche im Transcript nach ALLEN Gear-Erwähnungen:
- "my [Brand] [Product]" → Kandidat
- "I'm using a [Product]" → Kandidat
- "this [Product] weighs..." → Kandidat
- Jede Marken-Erwähnung (Zpacks, Gossamer Gear, ULA, etc.) → Kandidat

⚠️ ACHTUNG: Audio-Transkription macht HÄUFIG Fehler bei Markennamen!
- "gossamer here" → Gossamer Gear
- "u l a" / "you la" → ULA (Ultra Light Adventure)
- "enlightened equipment" / "e e" → Enlightened Equipment
- "hyper light" / "HMG" → Hyperlite Mountain Gear

**SCHRITT 3: JEDEN Kandidaten verifizieren (PFLICHT bei kurzer Beschreibung!)**
🔴 **Du MUSST `verify_gear_mention()` für JEDEN Produkt-Kandidaten aufrufen!**

Beispiel für JEDEN gefundenen Kandidaten:
```python
# Kandidat 1
verify_gear_mention(
    product_name="Arc Blast",
    possible_brand="Zpacks",
    context="er nutzt ihn für lange Thru-Hikes"
)

# Kandidat 2
verify_gear_mention(
    product_name="revelation quilt",
    possible_brand="enlightened equipment",
    context="sein liebster Quilt für 3-Jahreszeiten"
)

# ... für JEDEN weiteren Kandidaten
```

**SCHRITT 4: Specs recherchieren (wenn Gewicht/Preis fehlt)**
```python
research_gear_specs(
    product_name="Arc Blast",  # Verifizierter Name aus Schritt 3
    brand="Zpacks"
)
```

**SCHRITT 5: Erst DANN speichern**
Nur mit verifizierten Daten `save_gear_to_graph()` aufrufen!

---
📊 **CHECKLISTE für Transcript-Extraktion:**
- [ ] `fetch_youtube_transcript()` aufgerufen?
- [ ] Alle Produkt-Erwähnungen gesammelt?
- [ ] `verify_gear_mention()` für JEDEN Kandidaten aufgerufen?
- [ ] Bei fehlenden Specs: `research_gear_specs()` aufgerufen?
- [ ] Nur verifizierte Produkte gespeichert?

Das Transcript enthält oft:
- Erfahrungsberichte und Meinungen zu Produkten
- Vergleiche zwischen verschiedenen Gear-Optionen
- Tipps und Tricks aus der Praxis
- Details, die nicht in der Beschreibung stehen

### 1. WISSEN & ERFAHRUNGEN (Höchste Priorität!)
- **Praxis-Erfahrungen**: "Nach 500 Meilen auf dem Trail..." → `save_product_opinion(type="experience")`
- **Tipps & Tricks**: "Pro-Tipp: Kombiniere X mit Y..." → `save_product_opinion(type="tip")`
- **Warnungen**: "Achtung bei Temperaturen unter..." → `save_product_opinion(type="warning")`
- **Pros/Cons**: Jedes erwähnte Pro/Contra → `save_product_opinion(type="pro/con")`
- **Allgemeine Insights**: "Beim Ultralight gilt..." → `save_insight_to_graph()`

### 2. BEZIEHUNGEN & KONTEXT (Zweite Priorität!)
- **Einsatzkontexte**: Wann/wo funktioniert das Gear? → `save_recommended_usage()`
- **Vergleiche**: Wenn Produkte verglichen werden → `save_product_comparison()`
- **Alternativen**: Budget-Optionen, Ersatzprodukte → `save_product_alternative()`
- **Kompatibilität**: Was passt zusammen? → `save_gear_compatibility()`

### 3. PRODUKTDATEN (Dritte Priorität)
- **Duplikat-Check ZUERST**: `find_similar_gear(name, brand)`
- **Brand verifizieren**: `verify_product_brand()` bei Audio-Quellen
- **Speichern**: `save_gear_to_graph()` mit ALLEN verfügbaren Specs
- **Verlinken**: `link_extracted_gear_to_source()`

### 4. PROVENIENZ
- Für jedes Feld: `track_field_source()` mit Confidence-Score

### 5. ABSCHLUSS (PFLICHT!)
Rufe am Ende UNBEDINGT auf:
```
save_extraction_result(
    url="{video['url']}",
    title="{video['title']}",
    channel="...",  # Aus dem Video
    gear_items_found=X,
    insights_found=Y,
    extraction_summary="..."  # Markdown-Zusammenfassung
)
```

**WICHTIG:** Jede Erfahrung, jeder Tipp, jede Warnung ist wertvoll!
Der GearGraph wird durch dein extrahiertes Wissen klüger!

Beginne jetzt mit der Extraktion."""

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
