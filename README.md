# YouTube Playlist Automation

AI-assisted pipeline for a vocal-less mood-music YouTube channel: experiment
with many playlist concepts, evaluate and select only the strong ones,
generate music prompts, and (in later phases) build playlists, upload to
YouTube, and feed performance data back into the next round of concepts.

Human approval is required before anything is considered "ready" — this
system never auto-publishes.

## Status: Phase 7 complete — all 7 planned phases implemented

Phase 1: project scaffolding, DB models for the full pipeline (including
a `Channel`-scoped admin UI and a many-to-many `PlaylistTrack` join for
song reuse across playlists), `AiProvider` interface with a working
`MockAiProvider` (no API key) and a `ClaudeAiProvider` structure (unused
until you opt in), concept generation + evaluation, top-3 selection,
manual approval, music prompt generation, and a minimal FastAPI + Jinja2
admin UI.

Phase 2: `MusicGenerationProvider` interface (`SunoProvider` —
no official API yet, always raises; `ManualUploadProvider` — the MVP
path; `FutureProvider` — placeholder seam), an admin file-upload endpoint
per track, and a librosa-based `AudioAnalysisService` /
`TrackQualityService` that moves a `Track` from `GENERATED` through
`ANALYZING` to `SELECTED`/`REJECTED` with a concrete reason (length vs.
prompt target, intro silence, abrupt volume jumps, near-silence, and
short-loop repetition).

Phase 3: `PlaylistService` orders a concept's `SELECTED` tracks by
BPM/energy (nearest-neighbor adjacency) and cycles them to fill a
30/60/90/120-minute target; `AudioAssemblyService` crossfades them into
one file with ffmpeg's `acrossfade`; `VideoService` renders a 16:9 mp4 —
procedural gradient background (placeholder art pending Phase 4),
Ken Burns zoom via `zoompan`, a looping rain/snow/dust particle layer
composited with `screen` blend, and the playlist title burned in with
Korean-capable text via `drawtext`.

Phase 4: `AiProvider` gained `generate_youtube_titles` (5 situation-centric
candidates, not spammy "AI Generated Jazz #15" filler),
`generate_description` (description + hashtags + keywords + category +
thumbnail text), and `generate_thumbnail_prompt` (keyed to a per-channel
`ThumbnailTheme` for brand consistency); `ThumbnailService` renders a
placeholder thumbnail image from that prompt; `YoutubeMetadataService`
wires all three into a playlist and moves it to `REVIEW_REQUIRED`. The
admin UI lets you pick a title from the 5 candidates, regenerate titles or
the thumbnail, and finally **Approve** or **Reject** — the human gate
spec section 14 requires before anything could go to YouTube.

Phase 5: `YoutubeUploadProvider` interface — same pattern as `AiProvider`/
`MusicGenerationProvider` — with `MockYoutubeUploadProvider` (default, no
credentials, deterministic fake video IDs, fully testable) and
`RealYoutubeUploadProvider` (real YouTube Data API v3 upload via OAuth,
used once you provide credentials). `YoutubeUploadService` enforces the
human-approval gate (`ValueError` if the playlist isn't `APPROVED`),
uploads the video + thumbnail, optionally adds it to a per-channel
target YouTube playlist, records a `YoutubeVideo` row, and moves the
playlist to `UPLOADED`. `scripts/youtube_oauth_setup.py` is a one-time
script you run locally to obtain a refresh token.

Phase 6: `YoutubeAnalyticsProvider` interface (same pattern again) with
`MockYoutubeAnalyticsProvider` (default, deterministic synthetic daily
stats) and `RealYoutubeAnalyticsProvider` (YouTube Analytics API v2,
reusing the Phase 5 OAuth refresh token with an added read-only scope).
`AnalyticsCollectionService` fetches views/watch time/average view
duration/percentage viewed/impressions/CTR/likes/comments/subscribers
gained for a video+date and upserts into `YoutubeStats` (idempotent via
its existing unique constraint) — per video, per channel, or across every
channel. The admin UI has a **Collect Today's Stats** button per uploaded
playlist showing the daily history table, and
`scripts/collect_analytics.py` is a standalone script meant for a daily
cron job so collection doesn't depend on someone opening the admin UI.

Phase 7: `AiProvider.analyze_performance` (implemented in both Mock and
Claude — this was the last stub method declared back in Phase 1's
interface) takes the channel's uploaded videos ranked by a composite
score (`PerformanceAnalysisService`: views, CTR, retention, watch time,
subscriber conversion, and comment rate weighted together, never views
alone) and extracts transferable patterns — recommended situations,
genres, moods, BPM range, title structure notes, thumbnail style notes,
video length — into a per-channel `ContentStrategy`
(`ContentStrategyService.refresh_strategy`). `ConceptService` then feeds
the saved strategy into the next `generate_concepts` call, and
`MockAiProvider` biases roughly 30-40% of the new batch toward what
worked while the rest stays fresh exploration — verified end-to-end
(score ranking → strategy → biased-but-varied next batch, zero verbatim
repeats) in `scripts/phase7_e2e_test.py`. The admin UI has a
`/channels/{id}/strategy` page with a **Refresh Strategy** button, and
the concepts page shows whether a strategy is currently being applied.

All 7 phases from the original spec are now built end-to-end, from
concept generation through upload and performance-driven iteration.

## Project layout

```
app/
  config.py            settings from environment/.env
  database.py          SQLAlchemy engine/session
  models.py            Channel, ThumbnailTheme, Concept, Track, Playlist,
                        PlaylistTrack, YoutubeVideo, YoutubeStats,
                        ContentStrategy, AiCostLog
  providers/
    base.py             AiProvider interface (text/JSON generation)
    types.py            ConceptCandidate, ConceptEvaluation, MusicPromptSpec,
                         YoutubeDescriptionSpec, VideoPerformanceRecord,
                         PerformanceInsights, AiUsage dataclasses
    mock_provider.py     MockAiProvider - deterministic, $0, no API key
    claude_provider.py   ClaudeAiProvider - real Anthropic calls, lazy
    factory.py           picks provider from AI_PROVIDER env var
    music/
      base.py             MusicGenerationProvider interface (audio generation)
      suno_provider.py     SunoProvider - no official API, always raises
      manual_provider.py   ManualUploadProvider - Phase 2 MVP path
      future_provider.py   FutureProvider - placeholder for a future API
      factory.py            picks provider from a name string
    youtube/
      base.py               YoutubeUploadProvider interface (upload)
      mock_provider.py       MockYoutubeUploadProvider - default, no credentials
      real_provider.py       RealYoutubeUploadProvider - real OAuth upload, lazy
      factory.py              picks provider from YOUTUBE_UPLOAD_PROVIDER env var
      analytics_base.py       YoutubeAnalyticsProvider interface (daily stats)
      mock_analytics_provider.py  MockYoutubeAnalyticsProvider - deterministic synthetic stats
      real_analytics_provider.py  RealYoutubeAnalyticsProvider - YouTube Analytics API v2, lazy
      analytics_factory.py     picks provider from YOUTUBE_ANALYTICS_PROVIDER env var
      scopes.py                shared OAuth scopes for upload + analytics
  services/
    concept_service.py       generate/evaluate/select/approve concepts
    music_prompt_service.py  turn an approved concept into Track prompts
    audio_analysis_service.py  librosa-based per-track quality metrics
    track_quality_service.py   GENERATED -> ANALYZING -> SELECTED/REJECTED
    playlist_service.py        BPM/energy ordering + repeat-fill + approve/reject
    audio_assembly_service.py  ffmpeg acrossfade concatenation
    video_service.py           background art + particles + zoompan + drawtext
    playlist_pipeline.py       orchestrates the three playlist/video steps above
    thumbnail_service.py       placeholder thumbnail image (Pillow)
    youtube_metadata_service.py  titles + description + thumbnail -> REVIEW_REQUIRED
    youtube_upload_service.py    APPROVED-only upload -> YoutubeVideo row -> UPLOADED
    analytics_collection_service.py  fetch + upsert daily YoutubeStats per video/channel/all
    performance_analysis_service.py  joins YoutubeStats + Concept/Track/Playlist -> scored records
    content_strategy_service.py      analyze_performance -> persisted per-channel ContentStrategy
  templates/, static/         admin UI
  main.py                     FastAPI app + routes
  seed.py                     default channel seed
scripts/phase1_e2e_test.py    scripted proof of the Phase 1 flow
scripts/phase2_e2e_test.py    scripted proof of the Phase 2 flow
scripts/phase3_e2e_test.py    scripted proof of the Phase 3 flow
scripts/phase4_e2e_test.py    scripted proof of the Phase 4 flow
scripts/phase5_e2e_test.py    scripted proof of the Phase 5 flow
scripts/phase6_e2e_test.py    scripted proof of the Phase 6 flow
scripts/phase7_e2e_test.py    scripted proof of the Phase 7 flow
scripts/youtube_oauth_setup.py  run locally (needs a browser) to get a refresh token
scripts/collect_analytics.py    cron-friendly daily stats collection across all channels
tests/test_phase1.py          pytest version of the Phase 1 flow
tests/test_phase2.py          pytest version of the Phase 2 flow
tests/test_phase3.py          pytest version of the Phase 3 flow
tests/test_phase4.py          pytest version of the Phase 4 flow
tests/test_phase5.py          pytest version of the Phase 5 flow
tests/test_phase6.py          pytest version of the Phase 6 flow
tests/test_phase7.py          pytest version of the Phase 7 flow
```

## Setup

Requires **Python 3.9+**. Tested primarily on 3.11; every module uses
`from __future__ import annotations` specifically so the `X | None`-style
type hints throughout don't crash on 3.9 (that syntax needs 3.10+ natively).

macOS/Linux:
```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Windows (`cmd.exe`):
```cmd
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```
(swap `python` for `py` if that's what's on your PATH; run
`.venv\Scripts\uvicorn ...` instead of `./.venv/bin/uvicorn ...` in the
sections below.)

`.env` defaults to `AI_PROVIDER=mock` — no API key needed. To use real
Claude generation later, set `AI_PROVIDER=claude` and fill in
`ANTHROPIC_API_KEY`.

## Run the admin app

```bash
./.venv/bin/uvicorn app.main:app --reload --port 8000
```

Open http://127.0.0.1:8000 — it redirects to `/channels` (or straight to
that channel's concepts if exactly one channel exists). Tables are
created automatically on startup and a default channel ("Late Night
Coding Beats") is seeded if none exists.

Every channel is fully isolated: concepts, tracks, and (later) playlists
all key off `channel_id` / `concept_id`, and the admin routes are nested
under `/channels/{channel_id}/...` rather than assuming a single channel.

Flow in the UI:
1. On `/channels`, open a channel (or create a new one for a different
   niche — spec section 1's "one niche per channel" rule).
2. **Generate 10 New Concepts** — creates and scores 10 candidates, marks
   the top 3 `SELECTED` and the rest `REJECTED`.
3. Click into a `SELECTED` concept to see its full evaluation breakdown
   and reasoning.
4. **Approve & Generate Music Prompts** — marks it `APPROVED` and
   generates 5 music-generation prompt candidates (`Track` rows).
5. For each track, either copy its prompt into Suno (or generate audio any
   other way) and use **Upload Audio** to attach the resulting file, or
   wait for a future automatic `MusicGenerationProvider`. Uploading
   immediately runs the librosa quality analysis and flips the track to
   `SELECTED` or `REJECTED` with a concrete reason and the raw metrics
   shown underneath.
6. Once at least one track is `SELECTED`, a **Build Playlist** form
   appears on the concept page — pick 30/60/90/120 minutes and submit.
   This orders the selected tracks, crossfades them into one audio file,
   and renders a 16:9 video, landing on the playlist's detail page with
   the final track order, audio path, and video path. Rendering a real
   30+ minute video is CPU-bound and takes real time (see the note in
   scope decisions below) — it isn't instant like the earlier steps.
7. On the playlist page, **Generate Titles, Description & Thumbnail**
   moves it to `REVIEW_REQUIRED`: pick one of 5 title candidates (or
   **Regenerate Title Candidates**), review the description/hashtags/
   keywords, and preview the thumbnail (or **Regenerate Thumbnail**).
8. **Approve** or **Reject**.
9. Once `APPROVED`, an **Upload to YouTube** section appears — pick a
   visibility (Private/Unlisted/Public, defaulting to Private per spec
   section 15) and submit. With the default `YOUTUBE_UPLOAD_PROVIDER=mock`
   this instantly "uploads" (no network calls) and shows a fake video
   ID/link so you can test the whole flow with zero setup; switching to
   `YOUTUBE_UPLOAD_PROVIDER=youtube` (after the one-time OAuth setup below)
   makes it a real upload.
10. `/channels/{id}/thumbnail-theme` edits the channel's brand kit
    (visual style, environment, lighting, camera angle, text style) and
    the optional target YouTube playlist ID that every upload for this
    channel gets added to.
11. Once `UPLOADED`, a **Performance Analytics** section appears with a
    **Collect Today's Stats** button and a history table (views, watch
    time, average view duration/percentage viewed, impressions, CTR,
    likes, comments, subscribers gained). With the default
    `YOUTUBE_ANALYTICS_PROVIDER=mock` this returns deterministic synthetic
    numbers instantly; re-clicking updates the same day's row instead of
    adding a duplicate. For real periodic collection, use
    `scripts/collect_analytics.py` on a cron schedule rather than relying
    on someone clicking the button daily.
12. `/channels/{id}/strategy` shows the channel's current
    performance-derived strategy (which situations/genres/moods/BPM range/
    video length correlated with the best CTR/retention/subscriber
    conversion) with a **Refresh Strategy from Latest Analytics** button.
    Once refreshed, the concepts page shows "Using performance-based
    strategy from N video(s)" and the next **Generate 10 New Concepts**
    biases roughly 30-40% of the batch toward what worked — the rest stays
    fresh exploration, and nothing ever literally repeats a past concept
    name or title.

## Run the automated proofs

```bash
./.venv/bin/python scripts/phase1_e2e_test.py   # concepts -> approval -> music prompts
./.venv/bin/python scripts/phase2_e2e_test.py   # + synthetic-audio upload -> quality analysis
./.venv/bin/python scripts/phase3_e2e_test.py   # + playlist ordering/repeat-fill -> audio+video render
./.venv/bin/python scripts/phase4_e2e_test.py   # + titles/description/thumbnail -> approve/reject
./.venv/bin/python scripts/phase5_e2e_test.py   # + upload (mock) -> UPLOADED, approval-gate + idempotency checks
./.venv/bin/python scripts/phase6_e2e_test.py   # + analytics collection (mock) -> upsert + multi-day accumulation
./.venv/bin/python scripts/phase7_e2e_test.py   # + performance ranking -> strategy -> biased-but-varied next batch
./.venv/bin/python -m pytest tests/ -v          # same flows as assertion-based tests
```

All of these use an isolated sqlite file/in-memory DB and never touch
`data/app.db`. `phase2_e2e_test.py` synthesizes 4 short WAV files with
ffmpeg (one clean, three that each trip a different quality rule) since
real Suno output isn't available in this environment. `phase3_e2e_test.py`
through `phase7_e2e_test.py` mark short synthetic tracks `SELECTED`
directly (Phase 2's gate is already proven separately) and use a small
`target_duration_sec` instead of a real 30-120 minute target so the
render finishes in seconds while still exercising the exact same code
path as the admin UI. `phase5_e2e_test.py` and `phase6_e2e_test.py`
always use `MockYoutubeUploadProvider`/`MockYoutubeAnalyticsProvider`
regardless of your `.env` — neither ever makes a real network call.
`phase7_e2e_test.py` writes two videos' `YoutubeStats` directly with
deliberately different performance levels (rather than relying on
`MockYoutubeAnalyticsProvider`'s semi-random numbers) so the ranking and
bias can be asserted deterministically. Requires `ffmpeg` on PATH
(`apt-get install ffmpeg`) and, for Korean text in the rendered
video/thumbnails, a Korean-capable font — see the `VIDEO_FONT_PATH` note
in scope decisions below if none is auto-detected on your OS.

## Phase 5/6 setup: getting real YouTube credentials

Everything works with zero setup via `YOUTUBE_UPLOAD_PROVIDER=mock` and
`YOUTUBE_ANALYTICS_PROVIDER=mock` (both defaults). To actually upload to
a real channel and collect its real Analytics data:

1. In [Google Cloud Console](https://console.cloud.google.com/), create or
   pick a project, then enable **both** the **YouTube Data API v3** and
   the **YouTube Analytics API** for it (APIs & Services → Library).
2. Configure the **OAuth consent screen** (APIs & Services → OAuth
   consent screen). For personal/testing use, "External" + adding your
   own Google account under "Test users" is enough — no Google review
   needed for that.
3. Create an **OAuth Client ID** (APIs & Services → Credentials → Create
   Credentials → OAuth client ID), type **Desktop app**. Copy the
   Client ID and Client Secret it gives you.
4. Put those in `.env` as `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET`.
5. Run `./.venv/bin/python scripts/youtube_oauth_setup.py` **locally, on a
   machine with a browser** (this step can't run in a headless
   sandbox/CI) — it opens a Google sign-in/consent page (requesting both
   the upload and analytics-readonly scopes together) and prints a
   `YOUTUBE_REFRESH_TOKEN` line to add to `.env`.
6. Set `YOUTUBE_UPLOAD_PROVIDER=youtube` and/or
   `YOUTUBE_ANALYTICS_PROVIDER=youtube`. Leave
   `YOUTUBE_DEFAULT_VISIBILITY=private` while testing uploads.
7. For periodic collection, add a cron entry running
   `scripts/collect_analytics.py` daily (an example crontab line is in
   that script's docstring).

If you generated a refresh token before Phase 6 existed (upload-only
scope), re-run `scripts/youtube_oauth_setup.py` to get a new one covering
analytics too — the old token keeps working for uploads but fails with
an insufficient-scope error on analytics calls.

## Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | no | `sqlite:///./data/app.db` | swap for a `postgres://` URL later with no code changes |
| `AI_PROVIDER` | no | `mock` | `mock` or `claude` |
| `ANTHROPIC_API_KEY` | only if `AI_PROVIDER=claude` | — | never commit this; `.env` is gitignored |
| `ANTHROPIC_MODEL` | no | `claude-sonnet-5` | |
| `YOUTUBE_UPLOAD_PROVIDER` | no | `mock` | `mock` or `youtube` |
| `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` | only if `YOUTUBE_UPLOAD_PROVIDER=youtube` | — | from Google Cloud Console; never commit these |
| `YOUTUBE_REFRESH_TOKEN` | only if `YOUTUBE_UPLOAD_PROVIDER=youtube` | — | from `scripts/youtube_oauth_setup.py`; never commit this |
| `YOUTUBE_DEFAULT_VISIBILITY` | no | `private` | `private` / `unlisted` / `public` |
| `YOUTUBE_CATEGORY_ID` | no | `10` (Music) | YouTube video category ID |
| `YOUTUBE_ANALYTICS_PROVIDER` | no | `mock` | `mock` or `youtube`; reuses `YOUTUBE_CLIENT_ID`/`SECRET`/`REFRESH_TOKEN` |

## Design notes / deliberate scope decisions

- **Concept status enum** extends the spec's `DRAFT, EVALUATED, SELECTED,
  REJECTED` with `APPROVED`, since the Phase 1 test scenario requires a
  distinct "user approved this one" state.
- **Track = prompt, not audio, in Phase 1.** A `Track` row is created the
  moment its music-generation prompt exists (`quality_status=GENERATED`);
  `audio_path` stays null until Phase 2 wires up manual upload +
  librosa/FFmpeg analysis.
- **Duplicate-content detection (spec section 23)** is intentionally not
  built yet — it needs a history of real generated concepts to be
  meaningful, and Phase 1's own selection step already discards
  near-duplicate `concept_name`s within a batch via the
  `differentiation` scoring criterion. Full cross-run similarity checking
  is a natural fit for Phase 2+.
- **librosa/FFmpeg** are now installed (`requirements.txt` + system
  `ffmpeg`), used by `AudioAnalysisService`.
- **Track quality checks are per-track only.** `AudioAnalysisService`
  covers length-vs-target, intro silence, abrupt volume jumps,
  near-silence, and short-loop repetition — everything from spec section
  8 that a single track can be judged on in isolation. "플레이리스트
  분위기 적합성" and "곡간 스타일 일관성" are inherently comparative
  (they need multiple tracks side by side) and are deferred to Phase 3's
  playlist-assembly step, where that comparison naturally happens.
  `analyze_performance`-style AI critique of a track isn't in `AiProvider`
  either, for the same reason the spec doesn't list it there (section
  21's interface only covers concepts/prompts/YouTube text/analytics).
- **`SunoProvider.generate()` always raises `NotImplementedError`.** Suno
  publishes no official generation API as of this writing; automating
  against its consumer web app would violate spec section 7's "no
  unofficial workarounds" rule and risk account suspension. The provider
  class exists as a documented seam for when an official API ships —
  `ManualUploadProvider` is the real Phase 2 path.
- **Volume-jump threshold (1.5x median RMS) was empirically calibrated**
  against the synthetic fixtures in `scripts/phase2_e2e_test.py`, not
  derived analytically — librosa's frame windowing smooths a hard
  transition over several hops, so the effective jump is well below the
  raw amplitude ratio. Real Suno output should be spot-checked against
  this threshold once available and adjusted if it proves too strict/loose.

### Phase 3 scope decisions

- **Filling a real playlist means repeating tracks, by design.** A
  concept typically yields only a handful of `SELECTED` tracks (Phase 1
  generates 5 candidates per concept), nowhere near enough distinct songs
  to fill 60-120 minutes. `playlist_service.build_sequence()` cycles
  through the BPM/energy-ordered tracks and repeats them as needed — this
  is exactly the scenario the `PlaylistTrack` many-to-many join was built
  for, and increasing the number of music-prompt candidates generated per
  concept (a Phase 1/2 config change, not a Phase 3 one) is the real lever
  for less repetition in production.
- **Track ordering is a greedy nearest-neighbor walk on (energy rank,
  BPM)**, not a global optimum (e.g. TSP-style) — simple, deterministic,
  and good enough for "songs feel adjacent," which is what spec section 9
  asks for. `Track.quality_status` moves to `PLAYLIST_READY` for every
  distinct track used, even though a single row can appear at several
  `PlaylistTrack` positions.
- **Background art is procedural gradient art (Pillow), not AI-generated
  imagery.** Real thumbnail/art generation is explicitly Phase 4 scope;
  Phase 3 only needed *something* consistent per mood to prove the
  zoom/particle/text video pipeline end to end.
- **The particle overlay blends with `screen` mode on a plain RGB/yuv420p
  clip, not a real alpha-channel video.** The first implementation used
  Pillow's RGBA frames encoded to VP9 `yuva420p` and composited with
  `overlay` — but this ffmpeg build's `libvpx-vp9` silently drops the
  alpha channel on encode (probed output was `yuv420p`), so the overlay
  rendered as solid black, hiding the background entirely. Rendering
  particles on a solid black canvas and blending with `screen` (black
  contributes nothing, bright pixels add light) sidesteps the alpha
  question completely and was verified by extracting and viewing actual
  frames from the rendered output, not just checking exit codes.
- **Korean text in the video needs a Hangul-capable font** — `drawtext`
  with a typical Latin-only default (e.g. DejaVu Sans) renders Korean
  playlist titles as tofu boxes. `video_service._resolve_font_path()`
  checks common install locations across platforms (Noto Sans CJK on
  Linux via `apt-get install fonts-noto-cjk`, Malgun Gothic on Windows —
  bundled since Vista, no install needed — Apple SD Gothic Neo on macOS)
  and falls back to no explicit font (Linux/macOS ffmpeg often still
  finds one via fontconfig) or Pillow's bitmap default for thumbnails
  (Latin-only, so Korean text becomes boxes) rather than crashing if none
  match. Set `VIDEO_FONT_PATH` to override with a specific `.ttf`/`.ttc`.
- **Rendering a real 30-120 minute video is genuinely slow** (tens of
  thousands of frames through `zoompan` + `blend` + `libx264`), unlike
  every prior Phase 1/2 step which completes in seconds. This is expected
  compute cost, not a bug — `scripts/phase3_e2e_test.py` and
  `tests/test_phase3.py` use a small `target_duration_sec` override to
  keep the automated proofs fast while exercising the identical code path
  the admin UI uses at full length.

### Phase 4 scope decisions

- **`PlaylistStatus.REJECTED` is added**, same reasoning as `Concept`'s
  extra `APPROVED` state back in Phase 1: spec section 14 explicitly asks
  for a Reject button, and the original 5-value enum had no rejected
  state to land in.
- **Thumbnail images are placeholder Pillow art** (the same procedural
  gradient background as the video, with the chosen title's text
  overlaid), not a real generated image — there's no image-generation API
  wired up. What Phase 4 actually needed was the **prompt** text
  (`AiProvider.generate_thumbnail_prompt`, stored on
  `Playlist.thumbnail_prompt`) and something reviewable in the admin UI;
  swapping in a real image-gen provider later only touches
  `thumbnail_service.render_thumbnail_image`.
- **`ThumbnailTheme` is one row per channel**, auto-created with sensible
  defaults on first use (`ensure_thumbnail_theme`, mirroring
  `ensure_default_channel` from Phase 1) and editable via
  `/channels/{id}/thumbnail-theme`. Every thumbnail prompt for that
  channel is generated against the same theme so a channel's thumbnails
  stay visually consistent (spec section 11), rather than each playlist
  inventing its own look.
- **"Replace Song" and "Reorder Playlist" (spec section 14) are not built
  as dedicated controls.** The existing **Rebuild Playlist** button
  (Phase 3) already re-runs the BPM/energy ordering from whichever tracks
  are currently `SELECTED`, which covers the reordering case; there's no
  manual drag-and-drop reorder or per-track swap UI. Excluding a specific
  track currently requires a code/DB-level status change back to
  `REJECTED` — a small admin control worth adding when this is actually
  needed in practice, rather than building a fine-grained reorder UI
  speculatively now.
- **Title/description generation only ever reads the currently
  `chosen_title`** for description generation — regenerating titles after
  a description was already written does not regenerate the description
  or thumbnail text to match; re-running **Generate Titles, Description &
  Thumbnail** (not just the "Regenerate Title" partial action) keeps
  everything in sync if the admin picks a very different title.

### Phase 5 scope decisions

- **`YoutubeUploadProvider` mirrors the `AiProvider`/
  `MusicGenerationProvider` pattern deliberately** — a plain API key can't
  upload on a channel's behalf (YouTube upload requires OAuth), so the
  same "mock by default, real once you opt in with credentials" shape
  used for Claude and Suno applies here too. `MockYoutubeUploadProvider`
  makes zero network calls and returns a deterministic fake video ID
  (a SHA1 of the video path + title), so the same upload request always
  produces the same ID — useful for the idempotency test
  (`test_reupload_does_not_duplicate_youtube_video_row`).
- **`YoutubeUploadService.upload()` refuses anything not `APPROVED`**,
  raising `ValueError` rather than silently uploading — this is the
  actual enforcement of spec section 27's "no fully automatic upload,
  always a human approval gate" principle, not just a UI convention that
  a direct API/script call could bypass.
- **Re-uploading updates the existing `YoutubeVideo` row instead of
  creating a second one** (matched by `playlist_id`, which is unique on
  that table). This isn't a real re-upload of the same YouTube video —
  it's what happens if an admin later re-approves and re-triggers upload
  on a playlist that already has one; it keeps the mapping from Playlist
  to YouTube video 1:1 instead of accumulating stale rows.
- **The optional per-channel `youtube_playlist_id`** (edited on the same
  page as the thumbnail theme, since both are channel-wide branding/
  distribution settings) opts a channel into having every upload added to
  one real YouTube playlist — spec section 15's "playlist" upload
  setting. Leaving it blank just uploads the video standalone.
- **`scripts/youtube_oauth_setup.py` cannot run in this sandbox** — it
  opens a real browser window for Google's OAuth consent screen, which
  requires a human with a display, on their own machine, so it wasn't
  possible to obtain and test against real credentials here. Everything
  up to and including the real API call site (`RealYoutubeUploadProvider`
  in `real_provider.py`) is written and lazy-loads the `google-*`
  libraries only when actually invoked, but has not been exercised against
  the live YouTube Data API — only against `MockYoutubeUploadProvider`.
  This is the one part of Phase 5 that genuinely needs you to run the
  setup script yourself and try a real upload to fully confirm.

### Phase 6 scope decisions

- **Impressions/CTR require a separate API query from the other
  engagement metrics.** The YouTube Analytics API rejects a single query
  that mixes `impressions`/`impressionsClickThroughRate` with
  `views`/`estimatedMinutesWatched`/etc. — `RealYoutubeAnalyticsProvider`
  issues two `reports().query()` calls per video/date and merges them,
  treating either being empty (e.g. video too new, or impressions data
  not yet available for that date) as zero/`None` rather than an error.
- **No background scheduler is built** (no Celery/APScheduler/etc.) —
  `scripts/collect_analytics.py` is a plain script meant to be invoked by
  the operating system's own cron, which is the right amount of
  infrastructure for an MVP that runs on one machine, versus adding a job
  queue dependency. The admin UI's **Collect Today's Stats** button
  exists for manual/on-demand collection and testing, not as the primary
  collection mechanism.
- **`MockYoutubeAnalyticsProvider` is deterministic per (video_id, date)**
  (seeded via a hash of both), not per call — re-collecting the same day
  returns the same synthetic numbers, which is what let
  `test_recollecting_same_date_upserts_not_duplicates` assert on upsert
  behavior without needing real API idempotency to test against.
- **The OAuth scope change is backward-compatible but not automatic.**
  Adding `yt-analytics.readonly` to `ALL_SCOPES` means any refresh token
  generated before Phase 6 still works for uploads (Phase 5) but will
  fail analytics calls with an insufficient-scope error until
  `scripts/youtube_oauth_setup.py` is re-run — there's no way to silently
  upgrade an existing token's scope after the fact, only re-consent.
- **Like Phase 5's real upload provider, `RealYoutubeAnalyticsProvider`
  has not been exercised against the live YouTube Analytics API** — the
  OAuth setup script needs a human with a browser, which this sandbox
  doesn't have. Only `MockYoutubeAnalyticsProvider` has been tested here.

### Phase 7 scope decisions

- **The performance score is a simple weighted heuristic, not a
  normalized/statistical model.** `PerformanceAnalysisService._score()`
  combines capped view count, CTR, retention, subscriber conversion rate,
  and comment rate with fixed weights (0.25/0.25/0.30/0.10/0.10) —
  reasonable for ranking one channel's own handful of videos against each
  other, which is all Phase 7 needs, but it isn't z-scored against a
  larger population and the weights aren't tuned against real outcome
  data. Revisit this once there's enough real upload history to validate
  or tune it against.
- **`ContentStrategy` is replaced on every refresh, not accumulated as
  history.** Each channel has at most one current strategy row; there's
  no log of how the strategy evolved over time. This matches spec section
  17's framing ("다음 생성에 반영" — inform the *next* generation), and
  keeps the model simple; a history table would be a natural Phase 7.1
  addition if trend-over-time analysis becomes valuable.
- **The bias is intentionally capped well under 100%** (`generate_concepts`
  bias picks up to `round(count * 0.4)` slots from patterns that matched
  the winning genre/mood, minimum 1) — spec section 17 explicitly warns
  against cloning past successes, so roughly 60%+ of every batch is
  guaranteed fresh exploration regardless of how strong the signal is.
- **`MIN_VIDEOS_FOR_STRATEGY = 1`** is a deliberately low bar so the
  feature is demonstrable and testable with a single uploaded+measured
  video, not a claim that one video's data is statistically meaningful. A
  real deployment should raise this once enough uploads exist — it's a
  single constant in `content_strategy_service.py`.
- **`analyze_performance` only reasons over content attributes already in
  the database** (situation, genre, mood, BPM, video length, title,
  thumbnail text) — it doesn't have access to the actual video/audio/
  thumbnail *files* or literal past title text beyond what's included as
  reference-only context, by design, so the model has less surface area
  to accidentally reproduce past output verbatim.

## Structural review pass (post-Phase-1, pre-Phase-2)

Two real gaps were found and fixed before starting Phase 2:

1. **Multi-channel routing was hardcoded to a single channel.** `main.py`
   used `db.query(Channel).first()` everywhere, so a second channel's
   concepts/tracks would have been invisible in the admin UI even though
   the DB schema already supported multiple channels. Routes are now
   nested under `/channels/{channel_id}/...`, and `/channels` lists and
   creates channels. Verified live with two channels generating 10
   concepts each with zero cross-contamination (see report).
2. **`Playlist` and `Track` had no relationship at all.** There was no
   way to represent "these N tracks, in this order, make up this
   playlist," and no way for a track to appear in more than one
   playlist. Added `PlaylistTrack`, an ordered many-to-many join table
   (`playlist_id`, `track_id`, `position`) — Phase 3 populates it when
   building playlists. Its unique constraint is on `(playlist_id,
   position)`, **not** `(playlist_id, track_id)` — an earlier version of
   this constraint used the latter and broke the very first Phase 3 test
   run, because filling a 60+ minute playlist from a handful of
   `SELECTED` tracks requires the *same* track to legitimately occupy
   multiple positions in *one* playlist (see "Phase 3 scope decisions"
   below).

Also added (cheap, no behavior change): a unique constraint on
`(youtube_video_id, date)` in `YoutubeStats` so re-running a daily stats
pull upserts instead of duplicating rows, an index on `date` for
date-range rollups, and indexes on `AiCostLog.provider/model/request_type/
created_at` for the cost-by-dimension queries spec section 22 asks for.
