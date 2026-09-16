from sqlalchemy.orm import Session

from .models import Channel


def ensure_default_channel(db: Session) -> Channel:
    channel = db.query(Channel).first()
    if channel:
        return channel

    channel = Channel(
        name="Late Night Coding Beats",
        niche="Vocal-less lo-fi / jazz / ambient BGM for coding, focus and late-night work",
        description=(
            "Single-niche mood-music channel. Every playlist targets one concrete "
            "listening situation (coding, rainy cafe work, studying, night driving, etc.) "
            "with consistent visual branding across thumbnails and videos."
        ),
        visual_theme="Warm, low-light interior scenes; muted color grading; minimal on-screen text",
    )
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return channel
