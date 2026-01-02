#!/usr/bin/env python3
"""CLI script to monitor YouTube playlist for new videos."""

import argparse
import sys
from dotenv import load_dotenv

from app.monitoring.pipeline import run_monitoring


def main():
    """Run playlist monitoring from command line."""
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Monitor YouTube playlist and process new videos"
    )
    parser.add_argument(
        "--playlist",
        type=str,
        help="YouTube playlist URL (or set PLAYLIST_URL env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check for new videos without processing them",
    )

    args = parser.parse_args()

    try:
        stats = run_monitoring(
            playlist_url=args.playlist,
            dry_run=args.dry_run,
        )

        if "error" in stats:
            print(f"\n❌ Monitoring failed: {stats['error']}")
            sys.exit(1)

        print("\n✅ Monitoring completed successfully")
        sys.exit(0)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
