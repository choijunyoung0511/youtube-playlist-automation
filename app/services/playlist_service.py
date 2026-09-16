from sqlalchemy.orm import Session

from ..models import Concept, Playlist, PlaylistStatus, PlaylistTrack, Track, TrackStatus

ENERGY_RANK = {"low": 0, "low-medium": 1, "medium": 2, "medium-high": 3, "high": 4}


def _energy_rank(track: Track) -> int:
    level = (track.prompt or {}).get("energy_level", "medium")
    return ENERGY_RANK.get(level, 2)


def order_tracks(tracks: list[Track]) -> list[Track]:
    """Greedy nearest-neighbor ordering on (energy, bpm) so adjacent tracks
    in the playlist feel like a natural progression rather than a random
    shuffle (spec section 9: order by BPM/energy/mood adjacency)."""
    remaining = list(tracks)
    remaining.sort(key=lambda t: (_energy_rank(t), t.bpm or 0))
    ordered = [remaining.pop(0)]

    while remaining:
        cur_energy, cur_bpm = _energy_rank(ordered[-1]), ordered[-1].bpm or 0

        def distance(t: Track) -> float:
            return abs(_energy_rank(t) - cur_energy) * 100 + abs((t.bpm or 0) - cur_bpm)

        remaining.sort(key=distance)
        ordered.append(remaining.pop(0))

    return ordered


def build_sequence(ordered_tracks: list[Track], target_duration_sec: int) -> list[Track]:
    """Cycle through the ordered tracks, repeating as needed, until the
    cumulative duration reaches the target. A concept typically yields only
    a handful of SELECTED tracks, so filling a 30-120 minute playlist means
    rotating through them - the same reuse the PlaylistTrack join table was
    built to support."""
    if not ordered_tracks:
        raise ValueError("No tracks to build a sequence from")

    sequence: list[Track] = []
    total = 0
    i = 0
    while total < target_duration_sec:
        track = ordered_tracks[i % len(ordered_tracks)]
        sequence.append(track)
        total += track.duration_sec or 0
        i += 1
        if not track.duration_sec:
            break  # avoid an infinite loop if a track has no known duration
    return sequence


class PlaylistService:
    def __init__(self, db: Session):
        self.db = db

    def build_playlist(
        self,
        concept: Concept,
        target_length_min: int = 60,
        target_duration_sec: int | None = None,
    ) -> Playlist:
        selected_tracks = (
            self.db.query(Track)
            .filter(Track.concept_id == concept.id, Track.quality_status == TrackStatus.SELECTED)
            .all()
        )
        if not selected_tracks:
            raise ValueError(f"Concept {concept.id} has no SELECTED tracks to build a playlist from")

        ordered = order_tracks(selected_tracks)
        target_sec = target_duration_sec if target_duration_sec is not None else target_length_min * 60
        sequence = build_sequence(ordered, target_sec)

        playlist = self.db.query(Playlist).filter(Playlist.concept_id == concept.id).first()
        if playlist is None:
            playlist = Playlist(concept_id=concept.id)
            self.db.add(playlist)

        playlist.title = f"{concept.concept_name} Mix"
        playlist.target_length_min = target_length_min
        playlist.status = PlaylistStatus.BUILDING
        self.db.commit()
        self.db.refresh(playlist)

        self.db.query(PlaylistTrack).filter(PlaylistTrack.playlist_id == playlist.id).delete()
        for position, track in enumerate(sequence):
            self.db.add(PlaylistTrack(playlist_id=playlist.id, track_id=track.id, position=position))

        for track in ordered:
            track.quality_status = TrackStatus.PLAYLIST_READY

        self.db.commit()
        self.db.refresh(playlist)
        return playlist

    def approve(self, playlist: Playlist) -> Playlist:
        playlist.status = PlaylistStatus.APPROVED
        self.db.commit()
        self.db.refresh(playlist)
        return playlist

    def reject(self, playlist: Playlist) -> Playlist:
        playlist.status = PlaylistStatus.REJECTED
        self.db.commit()
        self.db.refresh(playlist)
        return playlist
