"""Punarnirman ("पुनर्निर्माण" / rebuilding) — universal restoration-reel engine.

Deterministic image -> video -> reel pipeline that runs against ANY location,
not just one hardcoded place:

  1. Pick the day's location from the rotation list (different Indian
     slum/dirty/polluted location per calendar day for now; international
     entries exist in the rotation file but stay off until traction builds,
     per the phased rollout plan).
  2. Generate 5 keyframes via OpenAI (``image_generate``, dall-e-3, 9:16) using
     prompts built on the fly for that location's type (water vs land/slum) —
     see ``punarnirman_prompts.py``.
  3. Generate 5 continuity clips via fal.ai (``video_generate``, true
     start/end-frame interpolation) -- clips A-D are the locked-camera
     restoration progression (frame 1->2->3->4->5), and clip E is a
     dedicated post-restoration finale (frame 5->5) where the drone does
     a slow descent/push-in reveal, the one deliberate camera-movement
     exception in the whole sequence.
  4. Concatenate into one reel + burn in a location/hook text overlay
     (``video_merge``, ffmpeg).

No LLM tool-selection loop is needed — frame/clip prompts are generated
deterministically per location, same pattern ``MorningDigestAgent`` uses
for its deterministic data-collection step. Posting to social platforms is
intentionally NOT part of this agent yet (sequenced "pipeline first,
posting later").
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, ToolUsingAgent
from openjarvis.agents.punarnirman_dashboard import DashboardRun
from openjarvis.agents.punarnirman_prompts import (
    build_clip_prompts,
    build_dialogue_line,
    build_frame_prompts,
    build_hook_lines,
    build_intro_frame_prompt,
    build_seo_metadata,
)
from openjarvis.agents.punarnirman_scout import record_run_result, scout_location
from openjarvis.core.paths import get_config_dir
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import ToolCall


def _summarize_tool_calls(tool_results: List[Any]) -> List[Dict[str, Any]]:
    """Shape ToolResult objects into the dict form the dashboard's message
    log expects (mirrors what ToolExecutor would record for a chat turn)."""
    return [
        {
            "tool": r.tool_name,
            "arguments": "",
            "result": r.content,
            "success": r.success,
            "latency": r.latency_seconds * 1000,
        }
        for r in tool_results
    ]


@AgentRegistry.register("punarnirman")
class PunarnirmanAgent(ToolUsingAgent):
    """Universal, location-agnostic urban-restoration reel pipeline."""

    agent_id = "punarnirman"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._region = kwargs.pop("region", "india")
        self._output_dir = kwargs.pop("output_dir", "")
        self._resolution = kwargs.pop("resolution", "720p")
        # "browser" (default): drives Leonardo's web app via Playwright so
        # clips are billed against the subscription's bundled "AI Creation"
        # credits (confirmed live 2026-06-23: 504 credits/clip, sunk cost)
        # instead of the pay-as-you-go REST API balance. "api" falls back to
        # the original leonardo_video_generate REST tool if the browser
        # profile isn't set up yet (see scripts/leonardo_browser_login.py).
        self._video_backend = kwargs.pop("video_backend", "browser")
        # Storytelling intro clip (JE/politician addressing workers at the
        # site, full TTS + lip-sync via fal.ai -- ElevenLabs eleven-v3 for
        # voice, VEED Fabric 1.0 for lip-sync). Optional and non-fatal: if
        # any of its 3 sub-steps (image/TTS/lip-sync) fails, the run still
        # falls back to the silent A-E drone reel rather than failing the
        # whole pipeline over a brand-new, not-yet-battle-tested feature.
        self._enable_intro_clip = kwargs.pop("enable_intro_clip", True)
        super().__init__(*args, **kwargs)

    def _build_intro_clip(
        self,
        location: Dict[str, Any],
        run_dir: Path,
        dash: DashboardRun,
        tool_results: List[Any],
        errors: List[str],
    ) -> Optional[str]:
        """Generate the storytelling intro clip: ground-level reference
        image -> ElevenLabs TTS (via fal) -> VEED Fabric 1.0 lip-sync (via
        fal). Returns the local clip path on success, or None on any
        failure -- callers treat None as "skip the intro, use the silent
        reel as before" rather than failing the whole run."""
        dialogue = build_dialogue_line(location)
        intro_image_path = str(run_dir / "intro_frame.png")
        intro_clip_path = str(run_dir / "intro_clip.mp4")

        # 1. Ground-level reference image of the JE/politician at the site.
        image_call = ToolCall(
            id="intro-image-1",
            name="image_generate",
            arguments=json.dumps(
                {
                    "prompt": build_intro_frame_prompt(location),
                    "size": "1024x1792",
                    "output_path": intro_image_path,
                }
            ),
        )
        image_result = self._executor.execute(image_call)
        tool_results.append(image_result)
        if not image_result.success:
            errors.append(f"Intro clip image: {image_result.content}")
            dash.log("tool_retry", "Intro clip skipped (image generation failed)", {"error": image_result.content})
            return None

        # 2. TTS for the dialogue line via fal-hosted ElevenLabs (eleven-v3).
        # text_to_speech takes output_dir (not output_path) and writes a
        # fixed "digest.{ext}" filename inside it -- read the real path back
        # from the ToolResult instead of assuming intro_audio_path exists.
        tts_call = ToolCall(
            id="intro-tts-1",
            name="text_to_speech",
            arguments=json.dumps(
                {
                    "text": dialogue["text"],
                    "backend": "fal_elevenlabs",
                    "output_dir": str(run_dir),
                }
            ),
        )
        tts_result = self._executor.execute(tts_call)
        tool_results.append(tts_result)
        if not tts_result.success:
            errors.append(f"Intro clip TTS: {tts_result.content}")
            dash.log("tool_retry", "Intro clip skipped (TTS failed)", {"error": tts_result.content})
            return None
        intro_audio_path = (tts_result.metadata or {}).get("audio_path") or tts_result.content

        # 3. Lip-sync the image + audio into a talking-head clip.
        lipsync_call = ToolCall(
            id="intro-lipsync-1",
            name="lipsync_video_generate",
            arguments=json.dumps(
                {
                    "image_path": intro_image_path,
                    "audio_path": intro_audio_path,
                    "resolution": "720p" if "1080" not in str(self._resolution) else "1080p",
                    "output_path": intro_clip_path,
                }
            ),
        )
        lipsync_result = self._executor.execute(lipsync_call)
        tool_results.append(lipsync_result)
        if not lipsync_result.success:
            errors.append(f"Intro clip lip-sync: {lipsync_result.content}")
            dash.log("tool_retry", "Intro clip skipped (lip-sync failed)", {"error": lipsync_result.content})
            return None

        dash.log(
            "tool_result",
            f"Intro clip ready ({dialogue['speaker']}): {dialogue['text']}",
            {"intro_clip_path": intro_clip_path, "dialogue": dialogue},
        )
        return intro_clip_path

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        self._emit_turn_start(input)

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Step 0: Location Scout. An explicit override always wins; otherwise
        # check the Excel tracker for every location already used, then use
        # web search + an LLM call to pick a brand-new, never-repeated
        # location (river/drain/slum/landfill/polluted lake) and log it to
        # the tracker immediately (status "started"). Falls back to the
        # static rotation file (still skipping anything already tracked) if
        # the scout step has no network/API key available.
        explicit_location = kwargs.get("location")
        region = kwargs.get("region", self._region)
        tracked = False
        if explicit_location:
            location = explicit_location
        else:
            location = scout_location(region=region, run_id=run_id)
            tracked = True

        frames = build_frame_prompts(location)
        clips = build_clip_prompts(location)

        base_dir = Path(self._output_dir or str(get_config_dir() / "restoration_reels"))
        run_dir = base_dir / f"{location['id']}_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Mirror progress into the dashboard's managed-agent record so the
        # run shows up as a card with live status + activity log, even
        # though execution itself stays deterministic (no LLM tool loop).
        dash = DashboardRun()
        dash.log(
            "run_start",
            f"Starting reel for {location.get('area_name', '')}, {location.get('city', '')}",
            {"location": location, "run_dir": str(run_dir)},
        )

        tool_results = []
        errors: List[str] = []

        # Step 1: generate 5 keyframes. Frame 1 is a fresh text-to-image
        # generation; frames 2-5 are generated via image-edit using frame 1
        # as the reference image, so the camera framing/composition stays
        # locked across the whole sequence instead of drifting frame to
        # frame (which independent generations were doing).
        frame_paths: Dict[int, str] = {}
        master_frame_path: Optional[str] = None
        for frame in frames:
            frame_id = frame["id"]
            out_path = str(run_dir / f"frame_{frame_id}.png")
            args: Dict[str, Any] = {
                "size": frame.get("size", "1024x1792"),
                "output_path": out_path,
            }
            if master_frame_path:
                args["prompt"] = frame.get("edit_prompt", frame["prompt"])
                args["reference_image_path"] = master_frame_path
            else:
                args["prompt"] = frame["prompt"]
            # gpt-image-2 at quality="high" occasionally exceeds even the
            # 240s tool timeout on a single attempt (observed on Frame 5 in
            # production). Raising the timeout further is a losing game --
            # the API is just slow sometimes, not always -- so retry once
            # on failure before giving up on the whole run. A retry costs
            # one extra image call (a few cents); failing the whole
            # pipeline over one slow attempt costs the entire $0.40-0.50
            # run.
            max_attempts = 2
            result = None
            for attempt in range(1, max_attempts + 1):
                call = ToolCall(
                    id=f"image-{frame_id}-attempt{attempt}",
                    name="image_generate",
                    arguments=json.dumps(args),
                )
                result = self._executor.execute(call)
                if result.success:
                    break
                if attempt < max_attempts:
                    dash.log(
                        "tool_retry",
                        f"Frame {frame_id} ({frame.get('label', '')}) attempt {attempt}"
                        f" failed ({result.content}); retrying.",
                        {"frame_id": frame_id, "attempt": attempt},
                    )
                    time.sleep(3)
            tool_results.append(result)
            if not result.success:
                errors.append(f"Frame {frame_id} ({frame.get('label', '')}): {result.content}")
                continue
            frame_paths[frame_id] = out_path
            if master_frame_path is None:
                master_frame_path = out_path

        if len(frame_paths) < len(frames):
            self._emit_turn_end(turns=1, failed=True)
            error_msg = "Pipeline stopped: not all keyframes were generated. " + " | ".join(errors)
            dash.log("run_error", "Keyframe generation failed", {"errors": errors})
            dash.finish(success=False, content=error_msg, tool_calls=_summarize_tool_calls(tool_results))
            if tracked:
                record_run_result(run_id, status="failed")
            return AgentResult(
                content=error_msg,
                tool_results=tool_results,
                turns=1,
                metadata={"run_dir": str(run_dir), "location": location, "errors": errors},
            )
        dash.log("tool_result", f"Generated {len(frame_paths)} keyframes", {"frame_paths": frame_paths})

        # Step 2: generate the 5 continuity clips (A-D locked restoration
        # progression + E the post-restoration descent finale) via fal.ai.
        use_browser = self._video_backend == "browser"
        clip_paths: List[str] = []
        for clip in clips:
            clip_id = clip["id"]
            start_frame = clip["from_frame"]
            end_frame = clip["to_frame"]
            out_path = str(run_dir / f"clip_{clip_id}.mp4")
            resolution = clip.get("resolution", self._resolution)
            if use_browser:
                tool_name = "leonardo_browser_video_generate"
                args: Dict[str, Any] = {
                    "start_image_path": frame_paths[start_frame],
                    "end_image_path": frame_paths[end_frame],
                    "prompt": clip["prompt"],
                    "resolution": "RESOLUTION_1080" if "1080" in str(resolution) else "RESOLUTION_720",
                    "orientation": "portrait",
                    "output_path": out_path,
                }
            elif self._video_backend == "fal":
                tool_name = "video_generate"
                if start_frame == end_frame:
                    # Pure camera-move clip (e.g. clip E, the post-restoration
                    # descent finale) -- start and end are the SAME frame
                    # because nothing in the scene itself changes, only the
                    # camera moves. Feeding wan-flf2v two identical keyframes
                    # backfires: its whole job is to interpolate a DIFFERENCE
                    # between start and end, so given none it just holds the
                    # frame static for the full clip and ignores the motion
                    # text entirely (confirmed live -- the descent prompt
                    # produced a frozen, unchanged clip). Single-image mode
                    # (no end_image_path) routes to wan-25-preview/image-to-
                    # video instead, which animates purely from the text
                    # prompt around one frame -- the right tool for a
                    # camera-only move with no target end-state to bridge to.
                    args = {
                        "image_path": frame_paths[start_frame],
                        "prompt": clip["prompt"],
                        "resolution": "1080p" if "1080" in str(resolution) else "720p",
                        "output_path": out_path,
                    }
                else:
                    # Real start/end-frame interpolation via wan-flf2v for the
                    # restoration-progression clips (A-D).
                    args = {
                        "image_path": frame_paths[start_frame],
                        "end_image_path": frame_paths[end_frame],
                        "prompt": clip["prompt"],
                        "resolution": "1080p" if "1080" in str(resolution) else "720p",
                        "output_path": out_path,
                    }
            else:
                tool_name = "leonardo_video_generate"
                args = {
                    "start_image_path": frame_paths[start_frame],
                    "end_image_path": frame_paths[end_frame],
                    "prompt": clip["prompt"],
                    "resolution": resolution,
                    "output_path": out_path,
                }
            call = ToolCall(
                id=f"leonardo-{clip_id}",
                name=tool_name,
                arguments=json.dumps(args),
            )
            result = self._executor.execute(call)
            tool_results.append(result)
            if not result.success:
                errors.append(f"Clip {clip_id} ({clip.get('label', '')}): {result.content}")
                continue
            clip_paths.append(out_path)

        if len(clip_paths) < len(clips):
            self._emit_turn_end(turns=1, failed=True)
            error_msg = (
                "Pipeline stopped: not all transition clips were generated. "
                + " | ".join(errors)
            )
            dash.log("run_error", "Transition clip generation failed", {"errors": errors})
            dash.finish(success=False, content=error_msg, tool_calls=_summarize_tool_calls(tool_results))
            if tracked:
                record_run_result(run_id, status="failed")
            return AgentResult(
                content=error_msg,
                tool_results=tool_results,
                turns=1,
                metadata={"run_dir": str(run_dir), "location": location, "errors": errors},
            )
        dash.log("tool_result", f"Generated {len(clip_paths)} transition clips", {"clip_paths": clip_paths})

        # Step 2.5: storytelling intro clip -- a JE/politician addressing
        # workers at the (still-polluted) site, with a fresh, location-
        # grounded Hindi/Hinglish line, full TTS, and lip-synced video. This
        # is the one clip in the whole reel with a human voice and a
        # ground-level camera; it is prepended to clip_paths so it plays
        # first, ahead of the silent locked-aerial A-E sequence. Optional
        # and non-fatal -- a failure here just falls back to the reel
        # without the intro, it never fails the whole run.
        if self._enable_intro_clip:
            intro_clip_path = self._build_intro_clip(location, run_dir, dash, tool_results, errors)
            if intro_clip_path:
                clip_paths = [intro_clip_path] + clip_paths

        # Step 3: merge clips into one reel with a hook/location overlay.
        final_path = str(run_dir / "final_reel.mp4")
        overlay_text = f"{location.get('area_name', '')}, {location.get('city', '')}"
        # Scene-generic 2-second attention hook -- these reels are silent
        # (music only, no voiceover), so the opening hook text is the only
        # thing doing the "stop scrolling" job. "||" is just the delimiter
        # video_merge_tool splits on to get individual on-screen lines.
        hook_text = "||".join(build_hook_lines(location))
        merge_call = ToolCall(
            id="merge-1",
            name="video_merge",
            arguments=json.dumps(
                {
                    "clip_paths": clip_paths,
                    "output_path": final_path,
                    "overlay_text": overlay_text,
                    "overlay_seconds": 3,
                    "hook_text": hook_text,
                    "hook_seconds": 2,
                }
            ),
        )
        merge_result = self._executor.execute(merge_call)
        tool_results.append(merge_result)

        self._emit_turn_end(turns=1, failed=not merge_result.success)

        if not merge_result.success:
            error_msg = f"Pipeline stopped at merge step: {merge_result.content}"
            dash.log("run_error", "Final reel merge failed", {"clip_paths": clip_paths})
            dash.finish(success=False, content=error_msg, tool_calls=_summarize_tool_calls(tool_results))
            if tracked:
                record_run_result(run_id, status="failed")
            return AgentResult(
                content=error_msg,
                tool_results=tool_results,
                turns=1,
                metadata={"run_dir": str(run_dir), "location": location, "clip_paths": clip_paths},
            )

        dash.log("query_complete", "Reel finished", {"final_path": final_path})
        dash.finish(
            success=True,
            content=f"Reel ready: {final_path} ({location.get('area_name', '')}, {location.get('city', '')})",
            tool_calls=_summarize_tool_calls(tool_results),
        )
        if tracked:
            # Generate per-platform SEO metadata (Instagram/Facebook/YouTube/
            # TikTok hashtags + YouTube title/keywords) from this run's own
            # location fields and write it into the tracker's trailing
            # columns, so a future publish step can pull it directly instead
            # of regenerating it.
            seo_metadata = build_seo_metadata(location)
            record_run_result(run_id, status="completed", video_link=final_path, seo=seo_metadata)

        return AgentResult(
            content=final_path,
            tool_results=tool_results,
            turns=1,
            metadata={
                "run_dir": str(run_dir),
                "frame_paths": frame_paths,
                "clip_paths": clip_paths,
                "final_path": final_path,
                "location": location,
            },
        )


__all__ = ["PunarnirmanAgent"]
