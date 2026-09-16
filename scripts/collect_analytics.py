"""Collects yesterday's YouTube stats for every uploaded video across all
channels (spec section 16: "일정 기간마다 수집"). Meant to be run on a
schedule - e.g. a daily cron job - not from the admin UI.

Usage:
    ./.venv/bin/python scripts/collect_analytics.py                # yesterday
    ./.venv/bin/python scripts/collect_analytics.py --date 2026-09-10

Uses whatever YOUTUBE_ANALYTICS_PROVIDER is set to in .env (mock by
default). Example crontab entry (runs daily at 04:00, after YouTube's
Analytics data for the previous day has settled):
    0 4 * * * cd /path/to/youtube-playlist-automation && ./.venv/bin/python scripts/collect_analytics.py >> data/analytics_collect.log 2>&1
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.providers.youtube.analytics_factory import get_youtube_analytics_provider  # noqa: E402
from app.services.analytics_collection_service import AnalyticsCollectionService  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date", type=str, default=None,
        help="Date to collect, YYYY-MM-DD (default: yesterday, since today's data is usually incomplete)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    target_date = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        provider = get_youtube_analytics_provider()
        service = AnalyticsCollectionService(db, provider)
        rows = service.collect_for_all_channels(target_date)

        print(f"Collected stats for {target_date.isoformat()} using provider '{provider.name}': {len(rows)} video(s)")
        for row in rows:
            print(f"  video_row_id={row.youtube_video_id} views={row.views} watch_time_min={row.watch_time_min} ctr={row.ctr}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
