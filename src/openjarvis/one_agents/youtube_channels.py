"""Explicit channel identity for shared production; no credentials or process globals.

The legacy Sonia profile preserves the existing packaging defaults. Other channels
must supply their own identity and cannot inherit her portrait or playlist.
Profiles do not grant publishing authority or register an agent/schedule.
"""
from __future__ import annotations

import re
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChannelProfile:
    brand: str
    display_name: str
    topic: str
    audience: str
    subscribe_url: str = ""
    playlist_id: str = ""
    playlist_heading: str = "WATCH MORE"
    category_id: str = "27"
    metadata_language: str = "en-US"
    default_audio_language: str = "en"
    locales: tuple[str, ...] = ()
    thumbnail_mode: str = "original"
    narration_backend: str = "windows_sapi"
    voice_name: str = "Microsoft David Desktop"
    source_note: str = "Verify time-sensitive claims against the primary sources above."
    share_note: str = "Share this video with someone curious about the topic."
    comment: str = "Which part would you like us to explain next?"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", self.brand):
            raise ValueError("Invalid channel brand")
        if not all(v.strip() for v in (self.display_name, self.topic, self.audience)):
            raise ValueError("Channel name, topic and audience are required")
        if self.thumbnail_mode not in {"original", "portrait"}:
            raise ValueError("Unknown thumbnail mode")
        if self.narration_backend not in {"windows_sapi", "windows_onecore", "elevenlabs"}:
            raise ValueError("Unknown narration backend")
        if self.narration_backend.startswith("windows_") and not self.voice_name.strip():
            raise ValueError("Local narration requires an explicit installed voice")
        if self.subscribe_url and not re.fullmatch(
            r"https://www\.youtube\.com/(?:@[A-Za-z0-9_.-]+|channel/UC[A-Za-z0-9_-]+)\?sub_confirmation=1",
            self.subscribe_url,
        ):
            raise ValueError("Use an explicit YouTube subscribe URL")
        if self.playlist_id and not re.fullmatch(r"[A-Za-z0-9_-]+", self.playlist_id):
            raise ValueError("Invalid playlist ID")
        if self.brand == "planexium" and (
            self.thumbnail_mode != "original" or not self.narration_backend.startswith("windows_")
        ):
            raise ValueError("PLANEXIUM requires original thumbnails and local Windows narration")

    @property
    def playlist_url(self) -> str:
        return f"https://www.youtube.com/playlist?list={self.playlist_id}" if self.playlist_id else ""

    def validate_record(self, record: dict) -> None:
        # An explicitly supplied profile may brand an unbranded production plan.
        # A conflicting explicit identity must never silently be overwritten.
        if record.get("brand") not in (None, "", self.brand):
            raise ValueError("Production record and channel profile disagree")


SONIA = ChannelProfile(
    brand="sonia_travel_vlogs", display_name="Sonia Travel Vlogs", topic="travel",
    audience="Indian viewers", subscribe_url="https://www.youtube.com/@sonicsonia?sub_confirmation=1",
    playlist_id="PLPm-TxXg4ePwIUz51mRpLd-L53ht54fBC", playlist_heading="WATCH MORE TRAVEL STORIES",
    category_id="19", default_audio_language="hi",
    locales=("hi", "bn", "ta", "te", "mr", "gu", "pa", "ur", "es", "pt-BR", "id", "th", "vi", "ar"),
    thumbnail_mode="portrait", narration_backend="elevenlabs", voice_name="",
    source_note="Travel rules, prices, schedules and breaking-news details can change.",
    share_note="Save this video and share it with the person travelling with you.",
)

# Public channel ID supplied by the operator; the uploader still verifies the
# authenticated account before sending any video.
PLANEXIUM = ChannelProfile(
    brand="planexium", display_name="The Planexium", topic="space and astronomy",
    audience="viewers interested in planets, astronauts, space missions and cosmic discoveries",
    subscribe_url="https://www.youtube.com/channel/UCuPYr5_YFDy7f_nt-iT6vDQ?sub_confirmation=1",
    source_note=("Mission schedules and scientific interpretations can change. Distinguish observations, "
                 "simulations and artist concepts; check the linked primary sources."),
)


def load_profile(path: Path, brand: str) -> ChannelProfile:
    """Load an explicitly selected profile; missing channels never default to Sonia.

    This file holds production identity/settings only, not credentials, browser
    state, authority grants or agent registrations.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "one.youtube-channels/v1":
        raise ValueError("Unsupported channel profile schema")
    try:
        values = dict(data["channels"][brand])
    except KeyError as exc:
        raise ValueError("Channel has no explicit production profile") from exc
    if values.pop("brand", brand) != brand:
        raise ValueError("Channel profile identity disagrees with its registry key")
    if "locales" in values:
        if not isinstance(values["locales"], list) or not all(isinstance(v, str) for v in values["locales"]):
            raise ValueError("Metadata locales must be a list of language codes")
        values["locales"] = tuple(values["locales"])
    return ChannelProfile(brand=brand, **values)


@dataclass(frozen=True)
class ProductionContext:
    """An explicit per-run namespace, independent of provider/browser ownership."""
    channel: ChannelProfile
    media_root: Path
    mission_id: str

    def __post_init__(self) -> None:
        if not self.media_root.is_absolute():
            raise ValueError("An absolute media root is required")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", self.mission_id):
            raise ValueError("Invalid mission ID")

    @property
    def root(self) -> Path:
        return self.media_root / self.channel.brand / self.mission_id

    def artifact(self, relative: str) -> Path:
        target = (self.root / relative).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ValueError("Artifact path escapes the channel mission")
        return target

    def dedupe_key(self, stage: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", stage):
            raise ValueError("Invalid production stage")
        return f"youtube:{self.channel.brand}:{self.mission_id}:{stage}"
