"""Set a Short thumbnail in Sonia's persistent YouTube Studio session.

The Shorts master must start with its actual hook.  This stage runs only after
the Data API has created the private video and uses Sonia's dedicated Chrome
profile to attach the separate thumbnail in Studio.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CHANNEL_ID = "UCyqSprXlCEpBXMQRdkstLqA"
CHANNEL_NAME = "Sonia Travel Vlogs"
CHANNEL_LINK_SELECTOR = f'a[href*="/channel/{CHANNEL_ID}"]'
THUMBNAIL_LOADER_SELECTOR = "input#file-loader[type='file'][accept*='image']"
UPLOADED_THUMBNAIL_SELECTOR = "[aria-label='Uploaded thumbnail']"
THUMBNAIL_SECTION_TEXT = "Thumbnail"
UPLOAD_FILE_TEXT = "Upload file"
SONIA_BROWSER_DIR = Path(os.environ.get("SONIA_BROWSER_DIR") or r"C:\Users\pc\Documents\LAO\sonia-community")
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sonia_chrome():
    path = SONIA_BROWSER_DIR / "sonia_chrome.py"
    if not path.is_file():
        raise RuntimeError(f"Sonia persistent-browser launcher is missing: {path}")
    spec = importlib.util.spec_from_file_location("sonia_youtube_chrome", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _selected_uploaded_thumbnail(page) -> dict[str, Any]:
    return page.locator(UPLOADED_THUMBNAIL_SELECTOR).first.evaluate(
        """node => {
          if (!node) return {present:false, selected:false};
          const attrs = Object.fromEntries([...node.attributes].map(a => [a.name, a.value]));
          const image = node.querySelector('img');
          const selected = attrs['aria-pressed'] === 'true' || attrs['aria-selected'] === 'true' ||
            /selected|checked|active/.test(`${node.className} ${node.parentElement?.className}`.toLowerCase());
          return {present:true, selected, attrs, image_src:image?.currentSrc || image?.src || null};
        }"""
    )


def set_short_thumbnail(video_id: str, thumbnail: Path, *, receipt_path: Path | None = None) -> dict[str, Any]:
    """Upload, save and verify one custom thumbnail on the exact private Short."""
    video_id = str(video_id or "").strip()
    thumbnail = Path(thumbnail).resolve()
    if not VIDEO_ID.fullmatch(video_id):
        raise ValueError("YouTube Studio thumbnail stage received an invalid video id")
    if not thumbnail.is_file() or thumbnail.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ValueError("YouTube Studio thumbnail stage requires an existing JPG or PNG")
    if thumbnail.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("YouTube Studio thumbnail exceeds the 50 MB Studio limit")
    digest = _sha256(thumbnail)
    receipt_path = Path(receipt_path) if receipt_path else thumbnail.with_name("studio-thumbnail-receipt.json")
    try:
        prior = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prior = {}
    if prior.get("ok") and prior.get("video_id") == video_id and prior.get("thumbnail_sha256") == digest:
        return {**prior, "resumed": True, "receipt": str(receipt_path)}

    launcher = _sonia_chrome()
    state = launcher.ensure()
    if str(state).startswith("failed"):
        raise RuntimeError(f"Sonia persistent Chrome is unavailable: {state}")

    from playwright.sync_api import sync_playwright
    studio_url = f"https://studio.youtube.com/video/{video_id}/edit"
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{launcher.PORT}", timeout=20_000)
        if not browser.contexts:
            raise RuntimeError("Sonia persistent Chrome has no browser context")
        page = browser.contexts[0].new_page()
        page.set_default_timeout(30_000)
        try:
            page.goto(studio_url, wait_until="domcontentloaded", timeout=90_000)
            # Studio's current video-details shell no longer renders the
            # channel name as visible text.  The persistent Sonia session does
            # expose exact channel navigation links, which are a stronger
            # identity check than a translated/hidden display label.
            page.locator(CHANNEL_LINK_SELECTOR).first.wait_for(state="attached", timeout=45_000)
            loader = page.locator(THUMBNAIL_LOADER_SELECTOR).first
            loader.wait_for(state="attached", timeout=45_000)
            # Studio renders the thumbnail editor well below the initial fold.
            # Its file input is intentionally hidden, so scroll the visible
            # section/tile just as a human does and use the input only to
            # attach the file.
            section = page.get_by_text(THUMBNAIL_SECTION_TEXT, exact=True).first
            section.wait_for(state="visible", timeout=45_000)
            section.scroll_into_view_if_needed(timeout=30_000)
            upload_tile = page.get_by_text(UPLOAD_FILE_TEXT, exact=True).first
            upload_tile.wait_for(state="visible", timeout=30_000)
            upload_tile.scroll_into_view_if_needed(timeout=30_000)
            loader.set_input_files(str(thumbnail))
            uploaded = page.locator(UPLOADED_THUMBNAIL_SELECTOR).first
            uploaded.wait_for(state="visible", timeout=60_000)
            uploaded.scroll_into_view_if_needed(timeout=30_000)
            # Uploading creates the candidate; selecting it is a separate
            # Studio action.  Always select the uploaded candidate explicitly.
            uploaded.click(timeout=30_000)
            save = page.get_by_role("button", name="Save", exact=True).first
            save.wait_for(state="visible", timeout=30_000)
            page.wait_for_function("() => !document.querySelector('button[aria-label=\"Save\"]')?.disabled", timeout=30_000)
            save.click()
            # The enabled/disabled transition is transient in current Studio
            # and can be missed even though the save succeeds.  A reload plus
            # exact-video uploaded-control verification is the durable gate.
            try:
                page.wait_for_function(
                    "() => document.querySelector('button[aria-label=\"Save\"]')?.disabled === true",
                    timeout=20_000,
                )
            except Exception:
                pass
            page.reload(wait_until="domcontentloaded", timeout=90_000)
            page.locator(CHANNEL_LINK_SELECTOR).first.wait_for(state="attached", timeout=45_000)
            if f"/video/{video_id}/edit" not in page.url:
                raise RuntimeError("Studio thumbnail verification left the exact video details page")
            uploaded = page.locator(UPLOADED_THUMBNAIL_SELECTOR).first
            uploaded.wait_for(state="visible", timeout=45_000)
            uploaded.scroll_into_view_if_needed(timeout=30_000)
            evidence = _selected_uploaded_thumbnail(page)
            if not evidence.get("present"):
                raise RuntimeError(
                    "Studio save returned but the exact video's uploaded thumbnail was not visible after reload"
                )
            proof = receipt_path.with_suffix(".png")
            uploaded.screenshot(path=str(proof))
        finally:
            page.close()

    result = {
        "schema": "sonia-studio-short-thumbnail/1",
        "ok": True,
        "video_id": video_id,
        "studio_url": studio_url,
        "thumbnail": str(thumbnail),
        "thumbnail_sha256": digest,
        "persistent_browser_owner": "sonia-youtube",
        "control": "Uploaded thumbnail",
        "verified_after_reload": True,
        "studio_evidence": evidence,
        "proof": str(proof),
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt_path.with_suffix(receipt_path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, receipt_path)
    return {**result, "receipt": str(receipt_path)}
