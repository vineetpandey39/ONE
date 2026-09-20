"""Governed Amazon KDP browser publishing adapter.

The adapter owns no content decisions.  It consumes the immutable submission
packet produced by LAO, creates or resumes a KDP draft in a dedicated browser
profile, and records enough local state to survive a restart.  The final store
submission is deliberately a separate operation requiring an approval id.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


KDP_CREATE_URL = "https://kdp.amazon.com/en_US/create"
ASIN_RE = re.compile(r"\bB0[A-Z0-9]{8}\b", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_existing(base: Path, names: tuple[str, ...]) -> Path | None:
    roots = (base, base / "visual_assets")
    return next((root / name for root in roots for name in names if (root / name).is_file()), None)


@dataclass(frozen=True)
class SubmissionPacket:
    run_dir: str
    metadata_path: str
    manuscript_path: str
    cover_path: str
    title: str
    subtitle: str
    author: str
    language: str
    description: str
    keywords: list[str]
    categories: list[str]
    ai_generated_text: bool
    ai_generated_images: bool
    price_usd: str
    checksums: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_packet(run_dir: str | Path) -> SubmissionPacket:
    """Validate a LAO KDP packet and freeze the upload inputs by checksum."""
    base = Path(run_dir).expanduser().resolve()
    if not base.is_dir():
        raise ValueError(f"KDP run directory does not exist: {base}")

    metadata_path = base / "kdp_metadata.json"
    manuscript = _first_existing(base, ("KDP_Book_Professional.docx", "manuscript.docx"))
    cover = _first_existing(base, ("cover.jpg", "cover.jpeg", "cover.png"))
    missing = [
        label for label, path in (
            ("kdp_metadata.json", metadata_path if metadata_path.is_file() else None),
            ("manuscript DOCX", manuscript),
            ("ebook cover", cover),
        ) if path is None
    ]
    if missing:
        raise ValueError("Incomplete KDP packet: missing " + ", ".join(missing))

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid KDP metadata: {exc}") from exc

    def value(*keys: str, default: Any = "") -> Any:
        for key in keys:
            if metadata.get(key) not in (None, ""):
                return metadata[key]
        return default

    title = str(value("title", "Title")).strip()
    author = str(value("author", "Author", "author_name")).strip()
    description = str(value("description", "Description")).strip()
    if not title or not author or len(description) < 50:
        raise ValueError("KDP metadata requires title, author, and a 50+ character description")

    keywords = value("keywords", "Keywords", default=[])
    categories = value("categories", "Categories", "categories_bisac", default=[])
    if isinstance(keywords, str):
        keywords = [part.strip() for part in keywords.split(",") if part.strip()]
    if isinstance(categories, str):
        categories = [part.strip() for part in categories.split(",") if part.strip()]

    disclosure = value("ai_disclosure", "aiDisclosure", default={})
    if not isinstance(disclosure, dict):
        disclosure = {}
    # LAO currently creates the manuscript and visual assets with generative
    # tools. Fail honest: absent disclosure is treated as generated, never as
    # a silent "No" in Amazon's declaration.
    ai_text = bool(disclosure.get("text", True))
    ai_images = bool(disclosure.get("images", True))

    assert manuscript is not None and cover is not None
    return SubmissionPacket(
        run_dir=str(base), metadata_path=str(metadata_path),
        manuscript_path=str(manuscript), cover_path=str(cover),
        title=title, subtitle=str(value("subtitle", "Subtitle")).strip(),
        author=author, language=str(value("language", "Language", default="English")),
        description=description, keywords=list(keywords)[:7], categories=list(categories)[:3],
        ai_generated_text=ai_text, ai_generated_images=ai_images,
        price_usd=str(value("price_usd", "ebook_price_usd",
                            default=os.environ.get("KDP_DEFAULT_EBOOK_PRICE_USD", "4.99"))),
        checksums={
            "metadata": _sha256(metadata_path),
            "manuscript": _sha256(manuscript),
            "cover": _sha256(cover),
        },
    )


def profile_dir() -> Path:
    path = Path(os.environ.get(
        "LAO_KDP_BROWSER_PROFILE",
        str(Path.home() / "Documents" / "LAO" / "browser-profiles" / "kdp-publisher"),
    )).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_path(packet: SubmissionPacket) -> Path:
    return Path(packet.run_dir) / "kdp_publish_state.json"


def write_state(packet: SubmissionPacket, stage: str, **extra: Any) -> dict[str, Any]:
    state = {
        "schema_version": 1, "stage": stage, "updated_at": _now(),
        "title": packet.title, "checksums": packet.checksums,
        **extra,
    }
    target = state_path(packet)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(target)
    return state


def _click(page: Any, labels: tuple[str, ...], *, required: bool = True) -> bool:
    for label in labels:
        locator = page.get_by_role("button", name=re.compile(label, re.I)).first
        try:
            if locator.is_visible(timeout=1200):
                locator.click()
                return True
        except Exception:
            continue
    if required:
        raise RuntimeError("KDP control not found: " + " / ".join(labels))
    return False


def _fill_label(page: Any, labels: tuple[str, ...], value: str, *, required: bool = True) -> bool:
    if not value:
        return False
    for label in labels:
        try:
            field = page.get_by_label(re.compile(label, re.I)).first
            if field.is_visible(timeout=1000):
                field.fill(value)
                return True
        except Exception:
            continue
    if required:
        raise RuntimeError("KDP field not found: " + " / ".join(labels))
    return False


def _choose(page: Any, labels: tuple[str, ...], *, required: bool = False) -> bool:
    for label in labels:
        try:
            control = page.get_by_label(re.compile(label, re.I)).first
            if control.is_visible(timeout=900):
                control.check(force=True)
                return True
        except Exception:
            continue
    if required:
        raise RuntimeError("KDP choice not found: " + " / ".join(labels))
    return False


def open_session(*, headless: bool = False) -> Any:
    """Open the dedicated profile. First use intentionally allows login."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        str(profile_dir()), channel="chrome", headless=headless,
        viewport={"width": 1440, "height": 1000}, accept_downloads=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context._lao_playwright = pw  # type: ignore[attr-defined]
    return context


def prepare_draft(packet: SubmissionPacket, *, headless: bool = False) -> dict[str, Any]:
    """Create the eBook draft and stop before the final rights/price submit."""
    write_state(packet, "PREPARING_DRAFT")
    context = open_session(headless=headless)
    page = context.pages[0] if context.pages else context.new_page()
    try:
        page.goto(KDP_CREATE_URL, wait_until="domcontentloaded", timeout=90_000)
        if "signin" in page.url.lower() or page.get_by_text("Sign in", exact=True).count():
            write_state(packet, "LOGIN_REQUIRED", url=page.url)
            raise RuntimeError(
                "KDP persistent profile needs its one-time login. Complete login in the opened window, "
                "then run the publisher again. Credentials are never stored by ONE."
            )
        _click(page, (r"Create eBook", r"Kindle eBook"))
        page.wait_for_load_state("domcontentloaded")
        _fill_label(page, (r"Book title", r"Title"), packet.title)
        _fill_label(page, (r"Subtitle",), packet.subtitle, required=False)
        _fill_label(page, (r"Primary author", r"Author"), packet.author)
        _fill_label(page, (r"Description",), packet.description)
        _choose(page, (r"I own the copyright", r"necessary publishing rights"))
        for index, keyword in enumerate(packet.keywords, start=1):
            _fill_label(page, (rf"Keyword.*{index}",), keyword, required=False)
        # Amazon requires honest disclosure. Generated content is the safe
        # default in validate_packet when the LAO packet omitted this field.
        if packet.ai_generated_text or packet.ai_generated_images:
            _choose(page, (r"Yes.*AI-generated", r"AI-generated content.*Yes"))
        else:
            _choose(page, (r"No.*AI-generated", r"AI-generated content.*No"))
        _choose(page, (r"No.*sexually explicit", r"not.*sexually explicit"))

        # Save details before upload. KDP wording differs across locales, so
        # role/name fallbacks are preferred over brittle generated classes.
        _click(page, (r"Save and Continue", r"Save as Draft"))
        page.wait_for_timeout(2500)
        file_inputs = page.locator("input[type=file]")
        if file_inputs.count() < 1:
            raise RuntimeError("KDP manuscript upload input was not found")
        file_inputs.nth(0).set_input_files(packet.manuscript_path)
        page.wait_for_timeout(1500)
        if file_inputs.count() > 1:
            file_inputs.nth(1).set_input_files(packet.cover_path)
        else:
            _click(page, (r"Upload.*cover",), required=False)
            page.locator("input[type=file]").last.set_input_files(packet.cover_path)

        # Upload/conversion can take several minutes. Poll the page instead of
        # sleeping for a guessed duration.
        deadline = datetime.now(timezone.utc).timestamp() + 20 * 60
        while datetime.now(timezone.utc).timestamp() < deadline:
            text = page.locator("body").inner_text(timeout=10_000)
            if re.search(r"uploaded successfully|upload complete|processing complete", text, re.I):
                break
            if re.search(r"upload failed|error processing|fix.*error", text, re.I):
                raise RuntimeError("KDP reported an upload or conversion error")
            page.wait_for_timeout(5000)
        else:
            raise TimeoutError("KDP manuscript/cover processing did not complete within 20 minutes")

        _click(page, (r"Save and Continue", r"Save as Draft"))
        page.wait_for_timeout(2000)
        _choose(page, (r"All territories", r"worldwide rights"))
        _fill_label(page, (r"Amazon.com.*price", r"List Price"), packet.price_usd,
                    required=False)
        _click(page, (r"Save as Draft",), required=False)
        screenshot = str(Path(packet.run_dir) / "kdp_draft_ready.png")
        page.screenshot(path=screenshot, full_page=True)
        return write_state(packet, "READY_FOR_APPROVAL", draft_url=page.url,
                           evidence_screenshot=screenshot)
    except Exception as exc:
        write_state(packet, "BLOCKED", error=f"{type(exc).__name__}: {exc}", url=page.url)
        raise
    finally:
        context.close()
        getattr(context, "_lao_playwright", None) and context._lao_playwright.stop()  # type: ignore[attr-defined]


def submit_approved(packet: SubmissionPacket, approval_id: str, *, headless: bool = False) -> dict[str, Any]:
    """Submit an already prepared draft after a per-title A3 approval."""
    if not approval_id.strip():
        raise ValueError("A per-title Olympus approval id is required")
    prior = json.loads(state_path(packet).read_text(encoding="utf-8"))
    if prior.get("stage") != "READY_FOR_APPROVAL":
        raise ValueError("KDP draft is not ready for approval")
    if prior.get("checksums") != packet.checksums:
        raise ValueError("Submission files changed after review; prepare a new draft")

    context = open_session(headless=headless)
    page = context.pages[0] if context.pages else context.new_page()
    try:
        page.goto(str(prior["draft_url"]), wait_until="domcontentloaded", timeout=90_000)
        # The exact label varies by format and marketplace. Never fall back to
        # coordinates: a missing semantic control is a safe failure.
        _click(page, (r"Publish Your Kindle eBook", r"Publish.*eBook"))
        page.wait_for_timeout(2500)
        screenshot = str(Path(packet.run_dir) / "kdp_submitted.png")
        page.screenshot(path=screenshot, full_page=True)
        return write_state(packet, "SUBMITTED", approval_id=approval_id,
                           submitted_at=_now(), evidence_screenshot=screenshot)
    finally:
        context.close()
        getattr(context, "_lao_playwright", None) and context._lao_playwright.stop()  # type: ignore[attr-defined]


def poll_asin(packet: SubmissionPacket, *, headless: bool = True) -> dict[str, Any]:
    """Check KDP Bookshelf once; caller schedules retries until ASIN appears."""
    context = open_session(headless=headless)
    page = context.pages[0] if context.pages else context.new_page()
    try:
        page.goto("https://kdp.amazon.com/en_US/bookshelf", wait_until="domcontentloaded", timeout=90_000)
        body = page.locator("body").inner_text(timeout=20_000)
        title_at = body.lower().find(packet.title.lower()[:80])
        nearby = body[max(0, title_at - 500):title_at + 2000] if title_at >= 0 else body
        match = ASIN_RE.search(nearby)
        status_match = re.search(r"\b(Draft|In Review|Publishing|Live|Blocked)\b", nearby, re.I)
        if match:
            return write_state(packet, "ASIN_ASSIGNED", asin=match.group(0).upper(),
                               kdp_status=status_match.group(0) if status_match else "unknown")
        return write_state(packet, "AWAITING_ASIN",
                           kdp_status=status_match.group(0) if status_match else "unknown")
    finally:
        context.close()
        getattr(context, "_lao_playwright", None) and context._lao_playwright.stop()  # type: ignore[attr-defined]
