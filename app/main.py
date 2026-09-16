import tempfile
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine, get_db
from .models import (
    AiCostLog,
    Channel,
    Concept,
    ConceptStatus,
    ContentStrategy,
    Playlist,
    ThumbnailTheme,
    Track,
    TrackStatus,
)
from .providers.factory import get_ai_provider
from .providers.music.factory import get_music_generation_provider
from .providers.youtube.analytics_factory import get_youtube_analytics_provider
from .providers.youtube.factory import get_youtube_upload_provider
from .seed import ensure_default_channel
from .services.analytics_collection_service import AnalyticsCollectionService
from .services.concept_service import ConceptService
from .services.content_strategy_service import ContentStrategyService
from .services.music_prompt_service import MusicPromptService
from .services.playlist_pipeline import build_and_render_playlist
from .services.playlist_service import PlaylistService
from .services.track_quality_service import TrackQualityService
from .services.youtube_metadata_service import YoutubeMetadataService, ensure_thumbnail_theme
from .services.youtube_upload_service import YoutubeUploadService

BASE_DIR = Path(__file__).resolve().parent
AUDIO_STORAGE_DIR = BASE_DIR.parent / "data" / "audio"
PLAYLIST_AUDIO_DIR = BASE_DIR.parent / "data" / "playlist_audio"
PLAYLIST_VIDEO_DIR = BASE_DIR.parent / "data" / "playlist_video"
THUMBNAIL_DIR = BASE_DIR.parent / "data" / "thumbnails"
for _dir in (AUDIO_STORAGE_DIR, PLAYLIST_AUDIO_DIR, PLAYLIST_VIDEO_DIR, THUMBNAIL_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="YouTube Playlist Automation - Admin")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/media/thumbnails", StaticFiles(directory=str(THUMBNAIL_DIR)), name="thumbnails")
app.mount("/media/video", StaticFiles(directory=str(PLAYLIST_VIDEO_DIR)), name="playlist_video")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    try:
        ensure_default_channel(db)
    finally:
        db.close()


@app.get("/")
def root(db: Session = Depends(get_db)):
    channel = db.query(Channel).first()
    if channel:
        return RedirectResponse(url=f"/channels/{channel.id}/concepts")
    return RedirectResponse(url="/channels")


@app.get("/channels")
def list_channels(request: Request, db: Session = Depends(get_db)):
    channels = db.query(Channel).order_by(Channel.id.asc()).all()
    return templates.TemplateResponse(
        "channels_list.html",
        {"request": request, "channels": channels},
    )


@app.post("/channels")
def create_channel(
    name: str = Form(...),
    niche: str = Form(...),
    description: str = Form(""),
    visual_theme: str = Form(""),
    db: Session = Depends(get_db),
):
    channel = Channel(name=name, niche=niche, description=description, visual_theme=visual_theme)
    db.add(channel)
    db.commit()
    db.refresh(channel)
    return RedirectResponse(url=f"/channels/{channel.id}/concepts", status_code=303)


@app.get("/channels/{channel_id}/concepts")
def list_concepts(channel_id: int, request: Request, db: Session = Depends(get_db)):
    channel = db.get(Channel, channel_id)
    concepts = (
        db.query(Concept)
        .filter(Concept.channel_id == channel.id)
        .order_by(Concept.created_at.desc(), Concept.id.desc())
        .all()
    )
    total_cost = sum(log.estimated_cost_usd or 0 for log in db.query(AiCostLog).all())
    strategy = db.query(ContentStrategy).filter(ContentStrategy.channel_id == channel_id).first()
    return templates.TemplateResponse(
        "concepts_list.html",
        {"request": request, "channel": channel, "concepts": concepts, "total_cost": total_cost, "strategy": strategy},
    )


@app.post("/channels/{channel_id}/concepts/generate")
def generate_concepts(channel_id: int, db: Session = Depends(get_db)):
    channel = db.get(Channel, channel_id)
    ai = get_ai_provider()
    service = ConceptService(db, ai)

    concepts = service.generate_and_evaluate(channel, count=10)
    service.select_top(concepts, k=3)

    return RedirectResponse(url=f"/channels/{channel_id}/concepts", status_code=303)


@app.get("/concepts/{concept_id}")
def concept_detail(concept_id: int, request: Request, db: Session = Depends(get_db)):
    concept = db.get(Concept, concept_id)
    tracks = (
        db.query(Track)
        .filter(Track.concept_id == concept_id)
        .order_by(Track.id.asc())
        .all()
    )
    selected_count = sum(1 for t in tracks if t.quality_status in (TrackStatus.SELECTED, TrackStatus.PLAYLIST_READY))
    playlist = db.query(Playlist).filter(Playlist.concept_id == concept_id).first()
    return templates.TemplateResponse(
        "concept_detail.html",
        {
            "request": request,
            "concept": concept,
            "tracks": tracks,
            "selected_count": selected_count,
            "playlist": playlist,
        },
    )


@app.post("/concepts/{concept_id}/approve")
def approve_concept(concept_id: int, db: Session = Depends(get_db)):
    ai = get_ai_provider()
    concept_service = ConceptService(db, ai)
    concept = concept_service.approve(concept_id)

    music_service = MusicPromptService(db, ai)
    music_service.generate_tracks(concept, count=5)

    return RedirectResponse(url=f"/concepts/{concept_id}", status_code=303)


@app.post("/concepts/{concept_id}/tracks/{track_id}/upload")
async def upload_track_audio(
    concept_id: int,
    track_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    track = db.get(Track, track_id)
    if track is None or track.concept_id != concept_id:
        raise HTTPException(status_code=404, detail="Track not found for this concept")

    suffix = Path(file.filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        provider = get_music_generation_provider("manual")
        dest_path = provider.save_uploaded_file(tmp_path, AUDIO_STORAGE_DIR, track.id)
    finally:
        tmp_path.unlink(missing_ok=True)

    track.audio_path = dest_path
    track.generation_provider = provider.name
    db.commit()

    TrackQualityService(db).evaluate(track)

    return RedirectResponse(url=f"/concepts/{concept_id}", status_code=303)


@app.post("/concepts/{concept_id}/playlist/build")
def build_playlist(concept_id: int, target_length_min: int = Form(60), db: Session = Depends(get_db)):
    concept = db.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(status_code=404, detail="Concept not found")

    playlist = build_and_render_playlist(
        db, concept,
        audio_dir=PLAYLIST_AUDIO_DIR,
        video_dir=PLAYLIST_VIDEO_DIR,
        target_length_min=target_length_min,
    )
    return RedirectResponse(url=f"/playlists/{playlist.id}", status_code=303)


@app.get("/playlists/{playlist_id}")
def playlist_detail(playlist_id: int, request: Request, db: Session = Depends(get_db)):
    playlist = db.get(Playlist, playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found")
    track_links = sorted(playlist.track_links, key=lambda pt: pt.position)
    stats_history = []
    if playlist.youtube_video:
        stats_history = sorted(playlist.youtube_video.stats, key=lambda s: s.date, reverse=True)
    return templates.TemplateResponse(
        "playlist_detail.html",
        {"request": request, "playlist": playlist, "track_links": track_links, "stats_history": stats_history},
    )


@app.post("/playlists/{playlist_id}/analytics/collect")
def collect_playlist_analytics(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.get(Playlist, playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found")
    if playlist.youtube_video is None or not playlist.youtube_video.youtube_video_id:
        raise HTTPException(status_code=400, detail="Playlist has not been uploaded yet")

    provider = get_youtube_analytics_provider()
    AnalyticsCollectionService(db, provider).collect_for_video(playlist.youtube_video, date.today())

    return RedirectResponse(url=f"/playlists/{playlist_id}", status_code=303)


@app.post("/playlists/{playlist_id}/metadata/generate")
def generate_playlist_metadata(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.get(Playlist, playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found")

    ai = get_ai_provider()
    YoutubeMetadataService(db, ai).generate_all(playlist, THUMBNAIL_DIR)
    return RedirectResponse(url=f"/playlists/{playlist_id}", status_code=303)


@app.post("/playlists/{playlist_id}/metadata/regenerate-titles")
def regenerate_titles(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.get(Playlist, playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found")

    YoutubeMetadataService(db, get_ai_provider()).generate_titles(playlist)
    return RedirectResponse(url=f"/playlists/{playlist_id}", status_code=303)


@app.post("/playlists/{playlist_id}/metadata/choose-title")
def choose_title(playlist_id: int, title: str = Form(...), db: Session = Depends(get_db)):
    playlist = db.get(Playlist, playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found")

    YoutubeMetadataService(db, get_ai_provider()).choose_title(playlist, title)
    return RedirectResponse(url=f"/playlists/{playlist_id}", status_code=303)


@app.post("/playlists/{playlist_id}/metadata/regenerate-thumbnail")
def regenerate_thumbnail(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.get(Playlist, playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found")

    YoutubeMetadataService(db, get_ai_provider()).generate_thumbnail(playlist, THUMBNAIL_DIR)
    return RedirectResponse(url=f"/playlists/{playlist_id}", status_code=303)


@app.post("/playlists/{playlist_id}/approve")
def approve_playlist(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.get(Playlist, playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found")

    PlaylistService(db).approve(playlist)
    return RedirectResponse(url=f"/playlists/{playlist_id}", status_code=303)


@app.post("/playlists/{playlist_id}/reject")
def reject_playlist(playlist_id: int, db: Session = Depends(get_db)):
    playlist = db.get(Playlist, playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found")

    PlaylistService(db).reject(playlist)
    return RedirectResponse(url=f"/playlists/{playlist_id}", status_code=303)


@app.post("/playlists/{playlist_id}/upload")
def upload_playlist(playlist_id: int, privacy_status: str = Form(""), db: Session = Depends(get_db)):
    playlist = db.get(Playlist, playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found")

    provider = get_youtube_upload_provider()
    service = YoutubeUploadService(db, provider)
    visibility = privacy_status or settings.youtube_default_visibility
    service.upload(playlist, privacy_status=visibility, category_id=settings.youtube_category_id)

    return RedirectResponse(url=f"/playlists/{playlist_id}", status_code=303)


@app.get("/channels/{channel_id}/thumbnail-theme")
def thumbnail_theme_form(channel_id: int, request: Request, db: Session = Depends(get_db)):
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    theme = ensure_thumbnail_theme(db, channel_id)
    return templates.TemplateResponse(
        "thumbnail_theme.html",
        {"request": request, "channel": channel, "theme": theme},
    )



@app.post("/channels/{channel_id}/thumbnail-theme")
def update_thumbnail_theme(
    channel_id: int,
    visual_style: str = Form(...),
    main_character: str = Form(...),
    environment: str = Form(...),
    lighting: str = Form(...),
    camera_angle: str = Form(...),
    text_style: str = Form(...),
    youtube_playlist_id: str = Form(""),
    db: Session = Depends(get_db),
):
    theme = ensure_thumbnail_theme(db, channel_id)
    theme.visual_style = visual_style
    theme.main_character = main_character
    theme.environment = environment
    theme.lighting = lighting
    theme.camera_angle = camera_angle
    theme.text_style = text_style

    channel = db.get(Channel, channel_id)
    channel.youtube_playlist_id = youtube_playlist_id or None

    db.commit()
    return RedirectResponse(url=f"/channels/{channel_id}/thumbnail-theme", status_code=303)


@app.get("/channels/{channel_id}/strategy")
def content_strategy_page(channel_id: int, request: Request, db: Session = Depends(get_db)):
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    strategy = db.query(ContentStrategy).filter(ContentStrategy.channel_id == channel_id).first()
    return templates.TemplateResponse(
        "content_strategy.html",
        {"request": request, "channel": channel, "strategy": strategy},
    )


@app.post("/channels/{channel_id}/strategy/refresh")
def refresh_content_strategy(channel_id: int, db: Session = Depends(get_db)):
    channel = db.get(Channel, channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Channel not found")

    ContentStrategyService(db, get_ai_provider()).refresh_strategy(channel)
    return RedirectResponse(url=f"/channels/{channel_id}/strategy", status_code=303)
