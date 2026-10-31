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
import sys
import re
from dataclasses import dataclass, asdict, field
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
    # How much of each kind KDP asks about once AI use is declared, in KDP's own option values
    # (see _AI_VALUES). A kind the house declares unused is "NONE"; a used kind is only filled
    # when someone has stated its degree. ai_declaration() reads this.
    ai_levels: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_packet(run_dir: str | Path) -> SubmissionPacket:
    """Validate a LAO KDP packet and freeze the upload inputs by checksum."""
    base = Path(run_dir).expanduser().resolve()
    if not base.is_dir():
        raise ValueError(f"KDP run directory does not exist: {base}")

    metadata_path = base / "kdp_metadata.json"
    # Prefer the Kindle-ready EPUB when the production pipeline emitted one.
    # It carries the navigation document KDP needs for device-level TOC support.
    manuscript = _first_existing(
        base,
        ("KDP_Book_Professional.epub", "manuscript.epub",
         "KDP_Book_Professional.docx", "manuscript.docx"),
    )
    cover = _first_existing(base, ("cover.jpg", "cover.jpeg", "cover.png"))
    missing = [
        label for label, path in (
            ("kdp_metadata.json", metadata_path if metadata_path.is_file() else None),
            ("manuscript EPUB/DOCX", manuscript),
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

    stated = value("ai_disclosure", "aiDisclosure", default={})
    # The house declaration, with this book's own metadata layered over it so
    # a book made differently can say so.
    disclosure = {**AI_DISCLOSURE, **stated} if isinstance(stated, dict) else dict(AI_DISCLOSURE)
    # LAO currently creates the manuscript and visual assets with generative
    # tools. Fail honest: absent disclosure is treated as generated, never as
    # a silent "No" in Amazon's declaration.
    ai_text = bool(disclosure.get("text", True))
    ai_images = bool(disclosure.get("images", True))
    used = {"text": ai_text, "images": ai_images, "translations": bool(disclosure.get("translations", False))}
    ai_levels = {kind: ("NONE" if not used[kind] else str(disclosure.get(f"{kind}_level") or "").strip().upper())
                 for kind in used}

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
        ai_levels={kind: level for kind, level in ai_levels.items() if level},
    )


def profile_dir() -> Path:
    """The one Chrome profile this publisher signs in as.

    It used to default to Documents\\LAO\\browser-profiles\\kdp-publisher while
    open_session's other route attached to whatever Chrome was listening on
    9321 - and that Chrome is started by LAO from the kdp-factory binding, a
    different profile entirely. So the publisher had two identities and picked
    between them on whether a browser happened to be running: sign in, publish
    once, and the next run takes the other route and asks again. Measured on
    2026-10-31, both profiles held a full set of Amazon sign-in cookies
    (at-main, sess-at-main, session-id, ubid-main, x-main) - the operator had
    signed in twice, once per identity, which is what this bug feels like from
    the outside.

    Now the default is the profile the 9321 binding already names, so both
    routes reach the same browser. The launch route only runs when nothing is
    listening on 9321, so it cannot collide with LAO's own Chrome over the
    single-instance lock on a user-data-dir.
    """
    path = Path(os.environ.get(
        "LAO_KDP_BROWSER_PROFILE",
        str(Path.home() / ".lao" / "browser-sessions" / "kdp-factory"),
    )).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


# The markers an Amazon session is made of. Presence plus a future expiry is
# what "a sign-in is stored here" looks like on disk; nothing here reads a
# cookie's value, which is encrypted by Chrome anyway.
_AMAZON_SESSION_COOKIES = ("at-main", "sess-at-main", "session-id", "ubid-main", "x-main")


def stored_login(profile: Path | None = None) -> bool:
    """Does this profile hold an unexpired Amazon sign-in, without launching it?

    login_ready() can only see a Chrome that is already serving CDP, so when
    the operator signs in and then closes the browser there is nothing left to
    answer "yes" and a held job waits forever. Reading the profile's own cookie
    store answers the same question with no browser at all.

    A stale cookie that Amazon has since invalidated reads as a sign-in here.
    That costs one resumed attempt, which hits the challenge and holds again -
    the behaviour that already exists. The alternative, today, is a hold that
    never clears.
    """
    import shutil
    import sqlite3
    import tempfile

    store = (profile or profile_dir()) / "Default" / "Network" / "Cookies"
    if not store.is_file():
        return False
    # Chrome keeps the file locked while it runs, so this works on a copy.
    try:
        scratch = Path(tempfile.mkdtemp()) / "cookies.db"
        shutil.copy2(store, scratch)
    except OSError:
        return False
    try:
        db = sqlite3.connect(scratch)
        try:
            # Chrome stores expiry in microseconds since 1601-01-01; a session
            # cookie is 0 and is not durable evidence of anything.
            epoch_1601 = 11644473600_000_000
            now = int(datetime.now(timezone.utc).timestamp() * 1_000_000) + epoch_1601
            placeholders = ",".join("?" for _ in _AMAZON_SESSION_COOKIES)
            found = db.execute(
                f"SELECT DISTINCT name FROM cookies WHERE name IN ({placeholders}) "
                "AND host_key LIKE '%amazon%' AND expires_utc > ?",
                (*_AMAZON_SESSION_COOKIES, now),
            ).fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return False
    finally:
        scratch.unlink(missing_ok=True)
    # at-main is the one that actually carries the authenticated identity;
    # session-id alone is handed to anyone who loads the page.
    names = {row[0] for row in found}
    return "at-main" in names and len(names) >= 3


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
    _refuse_if_challenged(page)
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
    # 9321, the port this profile is registered under. It defaulted to 9333,
    # which belongs to the YATRA browser-capture profile, so whichever of the
    # two opened Chrome first owned the port and the other attached to it: a
    # capture could have filmed the Amazon-signed-in window, and a KDP publish
    # could have driven the throwaway capture profile. They never met only
    # because they have not yet run at the same time.
    cdp_url = os.environ.get("LAO_KDP_CDP_URL", "http://127.0.0.1:9321")
    try:
        browser = pw.chromium.connect_over_cdp(cdp_url, timeout=2500)
        if browser.contexts:
            context = browser.contexts[0]
            context._lao_playwright = pw  # type: ignore[attr-defined]
            context._lao_cdp_browser = browser  # type: ignore[attr-defined]
            return context
    except Exception:
        pass
    context = pw.chromium.launch_persistent_context(
        str(profile_dir()), channel="chrome", headless=headless,
        viewport={"width": 1440, "height": 1000}, accept_downloads=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context._lao_playwright = pw  # type: ignore[attr-defined]
    return context


def close_session(context: Any) -> None:
    """Disconnect from a shared CDP browser or close an owned context."""
    pw = getattr(context, "_lao_playwright", None)
    shared = getattr(context, "_lao_cdp_browser", None)
    if shared is None:
        context.close()
    if pw is not None:
        pw.stop()


def _capture_failure(page: Any, packet: "SubmissionPacket", label: str) -> dict[str, Any]:
    """Write a screenshot and whatever the page is complaining about.

    Both land beside the book, in the run_dir the owner already opens by hand,
    and the filenames match the kdp_*.png scope IMPRIMATUR declares. Best
    effort throughout: a failed capture must not replace the real error.
    """
    notes: dict[str, Any] = {"label": label, "url": ""}
    try:
        notes["url"] = page.url
    except Exception:  # noqa: BLE001
        pass
    try:
        shot = Path(packet.run_dir) / f"kdp_{label}.png"
        page.screenshot(path=str(shot), full_page=True)
        notes["screenshot"] = str(shot)
    except Exception as exc:  # noqa: BLE001
        notes["screenshot_error"] = str(exc)[:200]
    messages: list[str] = []
    for selector in ("[role=alert]", ".a-alert-content", "[class*=error-message]"):
        try:
            found = page.locator(selector)
            for index in range(min(found.count(), 8)):
                text = " ".join((found.nth(index).inner_text() or "").split())
                if text and text not in messages:
                    messages.append(text[:300])
        except Exception:  # noqa: BLE001
            continue
    notes["page_messages"] = messages
    try:
        (Path(packet.run_dir) / f"kdp_{label}.json").write_text(
            json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return notes


# BISAC is what the book packet speaks; KDP's picker speaks its own browse
# tree and will not take a BISAC string. Mapped 2026-09-24 by walking the live
# modal: each entry is the cascade of dropdown labels down to the level that
# reveals leaf checkboxes. Unmapped subjects fall back to the first entry so a
# book is never blocked on a missing row - KDP lets the owner re-categorise a
# published title, and no category at all stops the run dead.
_BISAC_TO_KDP_PATH: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("BUS", "BUSINESS", "ECONOMICS", "MANAGEMENT", "LEADERSHIP"),
     ("Business & Money", "Management & Leadership", "Management")),
    (("COM", "COMPUTERS", "TECHNOLOGY"),
     ("Computers & Technology", "Computer Science", "AI & Machine Learning")),
    (("SEL", "SELF-HELP", "PERSONAL GROWTH"),
     ("Self-Help", "Success", "General")),
    (("HEA", "HEALTH", "FITNESS"),
     ("Health, Fitness & Dieting", "Mental Health", "General")),
)


def _kdp_category_path(categories: list[str]) -> tuple[str, ...]:
    """Pick the browse-tree cascade that best fits the packet's BISAC subjects."""
    joined = " ".join(categories).upper()
    best, score = _BISAC_TO_KDP_PATH[0][1], 0
    for markers, path in _BISAC_TO_KDP_PATH:
        hits = sum(1 for marker in markers if marker in joined)
        if hits > score:
            best, score = path, hits
    return best


def _set_description(page: Any, text: str) -> int:
    """Put the blurb where KDP actually reads it.

    Typing into the CKEditor body is not enough, proven on the live form
    2026-09-24: the iframe showed all 732 characters and CKEDITOR.getData()
    agreed, yet KDP still refused with "Enter a description." Its own state is
    fed by the editor's change event, which synthetic keystrokes do not raise.
    Drive the editor's API and raise it explicitly.
    """
    # The editor is built after the rest of the form, so a fill that arrives
    # first finds no instance and silently writes nothing - which is what the
    # dispatched run hit on a page that otherwise looked correct. Wait for it.
    page.wait_for_function(
        "() => !!(window.CKEDITOR && CKEDITOR.instances && CKEDITOR.instances['editor1']"
        " && CKEDITOR.instances['editor1'].status === 'ready')", timeout=60000)
    page.evaluate(
        "(text) => {"
        " const ed = window.CKEDITOR && CKEDITOR.instances && CKEDITOR.instances['editor1'];"
        " if (!ed) { return 0; }"
        " ed.setData(text); ed.updateElement(); ed.fire('change'); ed.fire('blur');"
        " return (ed.getData() || '').length; }",
        text,
    )
    page.wait_for_timeout(1500)
    return int(page.evaluate(
        "() => { const ed = window.CKEDITOR && CKEDITOR.instances &&"
        " CKEDITOR.instances['editor1']; return ed ? (ed.getData()||'').length : 0; }"))


# How this company's books are actually made, stated once by the Chairman on
# 2026-10-04 and applied to every title unless a book's own metadata overrides
# it. Amazon holds the publisher to this declaration, so it is recorded as a
# fact about the house rather than re-asked per book - and the per-book
# override exists because a book made differently must be able to say so.
#
# The factory provenance also makes KDP's degree answer deterministic: it
# drafts the complete manuscript and generates many interior/cover images,
# while its automated assembly/polish is minimal editing rather than a human
# rewrite.  A differently produced book can still override these per title.
AI_DISCLOSURE: dict[str, Any] = {
    "text": True,          # drafted with Claude and NVIDIA models
    "images": True,        # generated with ChatGPT
    "translations": False,  # none; the books are written in English only
    "text_level": "ENTIRE_AND_MINIMAL",
    "images_level": "MANY_AND_MINIMAL",
    "text_tools": ["Claude", "NVIDIA"],
    "image_tools": ["ChatGPT"],
}


class AmazonChallenge(RuntimeError):
    """Amazon stopped to verify a person, and ONE will not pretend to be one.

    Its own type because it is not a broken form and no retry will clear it:
    a two-step code goes to the owner's phone and only the owner can enter it.
    Confirmed live 2026-10-02, when a paperback draft stopped on /ap/mfa and
    the run reported missing upload fields on a page that was not the form.
    """


def login_ready() -> bool:
    """Read-only probe of the owner's browser; never launch a competing profile."""
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(
                os.environ.get("LAO_KDP_CDP_URL", "http://127.0.0.1:9321"), timeout=3000)
            if not browser.contexts:
                return False
            page = browser.contexts[0].new_page()
            try:
                page.goto(KDP_CREATE_URL,
                          wait_until="domcontentloaded", timeout=15000)
                _refuse_if_challenged(page)
                return ("kdp.amazon.com/en_US/create" in page.url
                        and page.get_by_text("Create eBook", exact=True).count() > 0)
            finally:
                page.close()
    except Exception:
        return False


def _refuse_if_challenged(page: Any) -> None:
    """Raise if the browser is sitting on a sign-in or verification wall."""
    url = str(getattr(page, "url", "") or "").lower()
    if "/ap/mfa" in url:
        raise AmazonChallenge(
            "Amazon is asking for a two-step verification code, sent to the "
            "phone on the KDP account. ONE cannot enter it. Run kdp-login.ps1, "
            "complete the verification, and tick 'Don't require code on this "
            "browser' so this profile stops being challenged.")
    if any(part in url for part in ("/ap/signin", "/ap/cvf", "/ap/challenge")):
        raise AmazonChallenge(
            "Amazon returned this profile to the sign-in form. ONE never types "
            "a password - run kdp-login.ps1 and sign in there.")


# Two checkboxes sit among the leaves on the print form and are not
# categories: they declare the book's physical nature. Ticking "Low-content
# book" on a 90-page leadership title would file it with the notebooks and
# planners, and "Large-print" asserts a 16-point interior that this one does
# not have. Both are decisions about the edition, not about its subject, and
# neither belongs to a routine that is choosing subjects.
_BOOK_ATTRIBUTE_MARKERS = (
    "low-content book",
    "large-print book",
    "what's a ",
)


def _is_book_attribute(label: str) -> bool:
    lowered = label.lower()
    return any(marker in lowered for marker in _BOOK_ATTRIBUTE_MARKERS)


def _words(text: str) -> set[str]:
    """Words worth matching on, stemmed crudely at six characters.

    Crude on purpose: it is what makes "Strategic Planning" reach "Strategy &
    Competition", which an exact match never would.
    """
    return {w[:6] for w in re.findall(r"[a-z]{4,}", text.lower())
            if w not in {"book", "books", "general", "business", "economics"}}


def _rank_leaves(leaves: list[tuple[int, str]],
                 packet: "SubmissionPacket") -> list[tuple[int, str]]:
    """Order the leaves by how well each answers one of the book's categories.

    Walked in the packet's own order rather than by a single global score, so
    each of the author's categories gets its best available leaf before any of
    them gets a second. For a book filed as Management, Strategic Planning and
    Leadership that yields Management, Planning & Forecasting and Leadership &
    Motivation, where document order yielded Business Ethics, Consolidation &
    Merger and Corporate Governance.
    """
    remaining = list(leaves)
    chosen: list[tuple[int, str]] = []
    for wanted in list(packet.categories) + [packet.title]:
        target = _words(wanted)
        if not target or not remaining:
            continue
        def score(leaf: tuple[int, str]) -> tuple[int, int]:
            words = _words(leaf[1])
            # More of the category's words, then fewer words of its own.
            # Without the second term "Distribution & Warehouse Management"
            # beat plain "Management" for a Management title, on the strength
            # of one shared word buried in two unrelated ones.
            return len(target & words), -len(words)

        best = max(remaining, key=score)
        if not (target & _words(best[1])):
            continue            # nothing on this branch speaks to that category
        remaining.remove(best)
        chosen.append(best)
    # Anything still unfilled falls back to document order, so a book whose
    # categories match nothing on the branch still lands somewhere real rather
    # than nowhere.
    return chosen + remaining


def _choose_categories(page: Any, packet: "SubmissionPacket") -> list[str]:
    """Walk the category modal and tick up to three leaves, matched to the book.

    The picker is a cascade of react-aui selects, not a checkbox tree: level 0
    is the store, each choice reveals the next level, and the last one replaces
    the dropdowns with leaf checkboxes. It is also disabled until the
    AI-content question has been answered, which is why this runs after the
    disclosures rather than beside the other text fields.
    """
    button = page.locator("#categories-modal-button")
    # KDP enables this a beat after the AI-content answer registers, not on
    # the same tick, so a single check reads the old state and refuses a form
    # that was about to be fine.
    try:
        page.wait_for_function(
            "() => { const b = document.querySelector('#categories-modal-button');"
            " return !!b && !b.disabled; }", timeout=30000)
    except Exception:
        _capture_failure(page, packet, "category_picker_stayed_disabled")
        raise RuntimeError(
            "KDP's category picker never enabled. It unlocks once the"
            " marketplace, audience and AI-content questions are answered.")
    button.click()
    page.wait_for_timeout(4000)

    for label in _kdp_category_path(packet.categories):
        handle = page.evaluate(
            "() => { const s = Array.from(document.querySelectorAll('select'))"
            " .find(x => Array.from(x.options).some(o => o.text.trim() === 'Select one')"
            r"            && /\{\"level\":\d+\}/.test(x.value));"
            " return s ? s.name : ''; }")
        if not handle:
            break
        # The print tree is not the eBook tree, and in places it is shallower.
        # On paperback, Business & Money > Management & Leadership offers only
        # "Project Management" and "Quality Control & Management" below it,
        # where the eBook has a plain "Management". Walking the eBook's third
        # label blindly timed out on a dropdown that could never satisfy it,
        # and the paperback of a live book failed at its last step.
        #
        # Stopping here is not giving up. Two levels in, the modal has already
        # replaced the dropdowns with this branch's real leaf checkboxes, and
        # those are what KDP stores. The path is a route to the right branch,
        # not a value in itself.
        options = page.evaluate(
            "name => Array.from(document.querySelector(`select[name='${name}']`)"
            ".options).map(o => o.text.trim())", handle)
        if label not in options:
            break
        page.locator(f"select[name='{handle}']").select_option(label=label)
        page.wait_for_timeout(2500)

    # Collect the leaves first, then choose. Ticking the first three in
    # document order was wrong twice over on the print form: the first two
    # checkboxes there are not categories at all but the low-content and
    # large-print attributes, so a 90-page leadership book was about to be
    # filed as a notebook; and the three that followed were whatever came
    # first alphabetically, which for this book was Business Ethics and
    # Consolidation & Merger. Categories are half of how a book is found, so
    # they are matched to what the book is about.
    leaves: list[tuple[int, str]] = []
    boxes = page.locator("input[type=checkbox]")
    for index in range(boxes.count()):
        box = boxes.nth(index)
        if not box.is_visible() or box.is_checked():
            continue
        name = " ".join((box.evaluate(
            "e => (e.closest('label')||{}).innerText || ''") or "").split())
        if not name or _is_book_attribute(name):
            continue
        leaves.append((index, name))

    picked: list[str] = []
    for index, name in _rank_leaves(leaves, packet):
        if len(picked) >= 3:
            break
        boxes.nth(index).check(force=True)
        picked.append(name)
        page.wait_for_timeout(500)
    if not picked:
        raise RuntimeError("KDP category modal offered no selectable leaf categories")
    _click(page, (r"Save categories",))
    page.wait_for_timeout(4000)
    return picked


KDP_TITLE_LIMIT_MARKER = "Title creation limit reached"


class TitleCreationLimitReached(RuntimeError):
    """Amazon allows 2 new titles per format per week, reset Sunday 00:00 UTC.

    Raised as its own type so a caller can queue the book and try again after
    the reset rather than treating it as a broken run. Confirmed against KDP's
    own help page 2026-09-24: "we limit the number of titles you can create at
    the same time to 2 per book format each week."
    """


# KDP's generative-AI questionnaire on the eBook content step, read off the live form 2026-10-07.
_AI_SELECTS = {"text": "#generative-ai-questionnaire-text",
               "images": "#generative-ai-questionnaire-images",
               "translations": "#generative-ai-questionnaire-translations"}
_AI_VALUES = {
    "text": ("NONE", "PARTIAL_AND_MINIMAL", "PARTIAL_AND_EXTENSIVE", "ENTIRE_AND_MINIMAL", "ENTIRE_AND_EXTENSIVE"),
    "images": ("NONE", "FEW_AND_MINIMAL", "FEW_AND_EXTENSIVE", "MANY_AND_MINIMAL", "MANY_AND_EXTENSIVE"),
    "translations": ("NONE", "PARTIAL_AND_MINIMAL", "PARTIAL_AND_EXTENSIVE", "ENTIRE_AND_MINIMAL",
                     "ENTIRE_AND_EXTENSIVE"),
}


def ai_declaration(packet: "SubmissionPacket") -> dict[str, str]:
    """KDP's three AI answers for this book, or {} while any of them is still unstated.

    Each is a declaration Amazon holds the publisher to, so nothing here is inferred. A kind the
    house declares unused is NONE; a used kind needs its degree stated, either per book
    (ai_disclosure.text_level / images_level in kdp_metadata.json) or once for the house in
    one.env as ONE_KDP_AI_LEVELS="text=ENTIRE_AND_MINIMAL,images=MANY_AND_MINIMAL".
    """
    levels = dict(packet.ai_levels)
    for part in os.environ.get("ONE_KDP_AI_LEVELS", "").split(","):
        kind, _, level = part.partition("=")
        kind, level = kind.strip().lower(), level.strip().upper()
        if kind in _AI_VALUES and level and kind not in levels:
            levels[kind] = level
    if any(levels.get(kind) not in values for kind, values in _AI_VALUES.items()):
        return {}
    return {kind: levels[kind] for kind in _AI_VALUES}


def _page_errors(page: Any) -> list[str]:
    messages: list[str] = []
    for selector in ("[role=alert]", ".a-alert-content", "[class*=error-message]"):
        try:
            found = page.locator(selector)
            for index in range(min(found.count(), 8)):
                text = " ".join((found.nth(index).inner_text() or "").split())
                if text and text not in messages:
                    messages.append(text[:240])
        except Exception:  # noqa: BLE001
            continue
    return messages


AI_QUESTION = "Did you use AI tools"


def _ai_question_section(page: Any) -> Any:
    """The block KDP renders the AI question in, found by the question itself.

    Attribute names are Amazon's and they move. The question's wording is the
    contract with the author and does not.
    """
    return page.locator(
        f"//*[contains(normalize-space(.), {AI_QUESTION!r})]"
        "[not(.//*[contains(normalize-space(.), 'Did you use AI tools')])]"
        "/ancestor-or-self::*[.//*[normalize-space(text())='Yes']"
        " and .//*[normalize-space(text())='No']][1]"
    ).first


def _check_ai_answer(page: Any, disclosed: bool) -> bool:
    """Answer Yes or No to 'Did you use AI tools in creating texts, images, and/or translations?'.

    Anchored on the question text, because the markup around it has now moved
    twice. It was an Amazon accordion on 2026-10-07 - two rows carrying
    data-a-accordion-row-name, each with a role=radio header whose aria-checked
    held the answer - and by 2026-10-14 the eBook content step rendered neither
    that accordion nor the print forms' older has-ai-content inputs. The
    screenshot of that failure shows the section plainly on the page, Yes and
    No both unanswered, while both selectors found nothing: an honest error
    about a question that was right there.

    Both older shapes are still tried first, since nothing says KDP serves one
    rendering to every account.
    """
    want = "yes" if disclosed else "no"
    accordion = page.locator("[aria-labelledby='generative-ai-questionnaire-question'], "
                             "[data-a-accordion-name='generative-ai-questionnaire-accordion']").first
    if accordion.count():
        row = accordion.locator(f"[data-a-accordion-row-name='{want}']").first
        header = row.locator("[role=radio]").first
        if header.count():
            if header.get_attribute("aria-checked") != "true":
                row.locator("a.a-accordion-row").first.click()
                page.wait_for_timeout(1200)
            return header.get_attribute("aria-checked") == "true"
    exact = page.locator('input[name="has-ai-content"]')
    if exact.count() >= 2:
        exact.nth(0 if disclosed else 1).check(force=True)
        return True

    section = _ai_question_section(page)
    if not section.count():
        return False
    label = "Yes" if disclosed else "No"
    # A native radio if there is one, so the answer can be read back rather
    # than assumed; otherwise whatever KDP made clickable around the word.
    native = section.locator("input[type=radio]")
    if native.count() >= 2:
        target = native.nth(0 if disclosed else 1)
        try:
            _check_custom_radio(page, target, field_name="AI-generated content")
            return True
        except Exception:  # noqa: BLE001 - fall through to the row click
            pass
    row = section.locator(
        f"//*[normalize-space(text())={label!r}]"
        "/ancestor-or-self::*[self::a or self::button or self::label"
        " or @role='radio' or @role='button'][1]").first
    if not row.count():
        row = section.get_by_text(label, exact=True).first
    if not row.count():
        return False
    row.click()
    page.wait_for_timeout(1200)
    marker = section.locator("[role=radio][aria-checked=true], input[type=radio]:checked")
    if marker.count():
        return True
    # No state to read back: report what was clicked rather than claim success.
    return bool(section.locator(f"[aria-checked=true]:has-text({label!r})").count())


def _check_custom_radio(page: Any, control: Any, *, field_name: str) -> None:
    """Select a KDP radio even when Amazon hides the native input.

    KDP increasingly renders an invisible native input behind a styled label.
    Playwright's ``check(force=True)`` clicks that input, but Amazon's wrapper
    can immediately restore the old state.  Prefer user-like interactions and
    verify the native form value after every attempt; the event-backed setter
    is a final compatibility fallback for saved drafts using older markup.
    """
    radio = control.first
    if radio.is_checked():
        return

    attempts: list[tuple[str, Any]] = []
    control_id = radio.get_attribute("id") or ""
    if control_id:
        label = page.locator(f"label[for='{control_id}']").first
        if label.count():
            attempts.append(("associated label", lambda: label.click()))

    wrapping_label = radio.locator("xpath=ancestor::label[1]").first
    if wrapping_label.count():
        attempts.append(("wrapping label", lambda: wrapping_label.click()))

    attempts.extend([
        ("native click", lambda: radio.click(force=True)),
        ("keyboard", lambda: (radio.focus(), radio.press("Space"))),
        ("DOM click", lambda: radio.evaluate("el => el.click()")),
        ("event-backed setter", lambda: radio.evaluate("""
            el => {
              const setter = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype, 'checked'
              )?.set;
              if (setter) setter.call(el, true); else el.checked = true;
              el.dispatchEvent(new Event('input', { bubbles: true }));
              el.dispatchEvent(new Event('change', { bubbles: true }));
              el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
            }
        """)),
    ])

    failures: list[str] = []
    for method, action in attempts:
        try:
            action()
            page.wait_for_timeout(350)
            if radio.is_checked():
                return
        except Exception as exc:  # noqa: BLE001 - try the next KDP rendering
            failures.append(f"{method}: {type(exc).__name__}")

    raise RuntimeError(
        f"KDP did not accept the {field_name} selection"
        + (f" ({'; '.join(failures)})" if failures else "")
    )


def _complete_ebook_content(page: Any, packet: "SubmissionPacket") -> dict[str, Any]:
    """Answer every question on the eBook content step, then reach pricing or say exactly why not.

    Until 2026-10-07 the run uploaded the files, pressed Save and Continue and went hunting for the
    royalty radio. KDP had refused to move on - "Enter a selection for Digital Rights Management",
    "Specify if you used AI tools", "Confirm your answers are accurate" - so the page was still the
    content step, and the failure read as a missing 70% royalty option.
    """
    done: dict[str, Any] = {}
    drm = os.environ.get("ONE_KDP_DRM", "yes").strip().lower() not in {"0", "no", "false"}
    drm_radio = page.locator(f"input[name='data[is_drm]-radio'][value='{'true' if drm else 'false'}']")
    if drm_radio.count():
        _check_custom_radio(page, drm_radio, field_name="Digital Rights Management")
        done["drm"] = drm
    else:
        _capture_failure(page, packet, "drm_control_not_found")
        raise RuntimeError("Could not find KDP's Digital Rights Management choice on the content step.")

    disclosed = bool(packet.ai_generated_text or packet.ai_generated_images)
    done["ai_disclosed"] = disclosed
    done["ai_answered"] = _check_ai_answer(page, disclosed)
    if not done["ai_answered"]:
        notes = _capture_failure(page, packet, "ai_question_not_found")
        # The screenshot of the 2026-10-14 failure showed the section plainly
        # on the page while both selectors found nothing, and the draft had
        # moved on by the time anyone could look at it live. Keep the markup
        # with the screenshot so the next one is diagnosable from the file.
        try:
            section = _ai_question_section(page)
            notes["ai_section_html"] = (section.first.inner_html()[:4000]
                                        if section.count() else "section not found by question text")
            (Path(packet.run_dir) / "kdp_ai_question_not_found.json").write_text(
                json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001 - a failed capture must not replace the error
            pass
        raise RuntimeError("Could not answer KDP's 'Did you use AI tools' question on the content step.")
    page.wait_for_timeout(1500)
    if disclosed:
        declaration = ai_declaration(packet)
        if not declaration:
            _capture_failure(page, packet, "ai_levels_unstated")
            missing = [kind for kind in _AI_VALUES if kind not in packet.ai_levels]
            raise AmazonChallenge(
                "KDP asks how much of the " + " and ".join(missing) + " was AI-generated, and nobody has "
                "stated it. It is a declaration to Amazon, so it is not guessed: set ONE_KDP_AI_LEVELS in "
                "one.env (or ai_disclosure.<kind>_level in the book's metadata) and run again.")
        for kind, selector in _AI_SELECTS.items():
            control = page.locator(selector)
            if control.count():
                # The native select sits behind Amazon's styled button (tabindex -1), so it is
                # never "visible"; selecting it still fires the change event the form reads.
                control.first.select_option(declaration[kind], force=True)
                if declaration[kind] != "NONE":
                    tools = list(AI_DISCLOSURE.get(f"{kind[:-1] if kind.endswith('s') else kind}_tools", []))
                    if kind == "images":
                        tools = list(AI_DISCLOSURE.get("image_tools", []))
                    elif kind == "text":
                        tools = list(AI_DISCLOSURE.get("text_tools", []))
                    tool_inputs = page.locator(
                        f'input[aria-labelledby="generative-ai-questionnaire-{kind}-tools-prompt"]'
                    )
                    for index, tool in enumerate(tools[:tool_inputs.count()]):
                        tool_inputs.nth(index).fill(str(tool))
        done["ai_levels"] = declaration

    # Accessibility: answered only when nothing is chosen yet. 'unknown' is KDP's own
    # "I don't know" and the only honest answer an unattended build can give.
    reading = "input[name='data[accessibility][image_reading]']"
    if page.locator(reading).count() and not page.locator(reading + ":checked").count():
        page.locator(reading + "[value='unknown']").first.check(force=True)
        done["image_reading"] = "unknown"

    # After a new upload KDP asks to confirm the AI and accessibility answers.
    confirms = page.locator("xpath=//input[@type='checkbox'][ancestor::*[contains(normalize-space(.), "
                            "'answers are accurate')][1]]")
    for index in range(confirms.count()):
        box = confirms.nth(index)
        try:
            if not box.is_checked():
                box.check(force=True)
        except Exception:  # noqa: BLE001 - the pricing wait below decides
            continue
    custom_confirms = page.locator("[role='checkbox']").filter(
        has_text=re.compile(r"answers are accurate", re.I)
    )
    for index in range(custom_confirms.count()):
        box = custom_confirms.nth(index)
        if box.get_attribute("aria-checked") != "true":
            box.click()
            page.wait_for_timeout(350)
        if box.get_attribute("aria-checked") != "true":
            raise RuntimeError("KDP did not accept the content-answer confirmation checkbox.")
    done["confirmations"] = confirms.count() + custom_confirms.count()

    _click(page, (r"Save and Continue",))
    try:
        page.wait_for_url(re.compile(r"/title-setup/kindle/[^/]+/pricing"), timeout=90_000)
    except Exception:
        _capture_failure(page, packet, "content_did_not_advance")
        raise RuntimeError("KDP kept the eBook on the content step: "
                           + ("; ".join(_page_errors(page)) or "no message on the page"))
    page.wait_for_timeout(2500)
    return done


def _set_pricing(page: Any, packet: "SubmissionPacket") -> dict[str, Any]:
    """Choose the royalty plan and list price, the way the page will accept.

    page.fill() writes the DOM value without raising the events KDP's own state
    listens for, so the form looked priced and still refused to publish with
    "Set a list price for Amazon.com" - the same class of failure as the
    description. Real keystrokes register; every other marketplace then derives
    from this one ("All marketplaces are based on this price").
    """
    if "/pricing" not in page.url:
        _capture_failure(page, packet, "not_on_pricing")
        raise RuntimeError(f"Expected KDP's pricing step but the page is {page.url}: "
                           + ("; ".join(_page_errors(page)) or "no message on the page"))
    plan = "70_PERCENT" if float(packet.price_usd or 0) >= 2.99 else "35_PERCENT"
    exact = page.locator(
        f"input[name='data[digital][royalty_rate]-radio'][value='{plan}']"
    )
    if exact.count():
        exact.first.check(force=True)
    else:
        # KDP periodically changes generated radio names/values. Discover
        # the visible royalty control from its stable semantic text instead
        # of treating one historical DOM shape as the contract.
        wanted = "70" if plan == "70_PERCENT" else "35"
        matched = page.locator(
            "input[type='radio'], label, [role='radio'], button"
        ).evaluate_all(
            "(els, wanted) => els.map((el, i) => {"
            " const text = ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '') + ' ' + "
            "(el.value || '') + ' ' + (el.id || '')).replace(/\\s+/g, ' ').trim();"
            " return {i, tag: el.tagName, text, id: el.id, name: el.getAttribute('name'), value: el.value};"
            "}).filter(x => new RegExp('\\\\b' + wanted + '(?:%|\\\\s*percent)?\\\\b', 'i').test(x.text))",
            wanted,
        )
        if not matched:
            _capture_failure(page, packet, "royalty_control_not_found")
            raise RuntimeError(
                f"KDP pricing page did not expose a selectable {wanted}% royalty option")
        # i indexes the combined locator above, so act through that same locator.
        candidate = page.locator("input[type='radio'], label, [role='radio'], button").nth(int(matched[0]["i"]))
        if matched[0].get("tag") == "INPUT":
            candidate.check(force=True)
        else:
            candidate.click(force=True)
    page.wait_for_timeout(2500)

    field = page.locator(
        "input[name='data[digital][channels][amazon][US][price_vat_inclusive]']").first
    field.click()
    field.press("Control+a")
    page.keyboard.type(str(packet.price_usd), delay=120)
    field.press("Tab")
    page.wait_for_timeout(8000)

    counts = page.evaluate(
        "() => { const all = Array.from(document.querySelectorAll("
        "'input[name*=\"price_vat_inclusive\"]')).filter(i => i.offsetParent !== null);"
        " return {total: all.length, filled: all.filter(i => i.value.trim()).length}; }")
    if not counts["filled"] or counts["filled"] < counts["total"]:
        _capture_failure(page, packet, "pricing_incomplete")
        raise RuntimeError(
            f"Only {counts['filled']} of {counts['total']} marketplace prices "
            f"were set, so KDP would refuse to publish.")
    return {"royalty_plan": plan, "list_price_usd": packet.price_usd, **counts}


# Which step of a saved draft to reopen, furthest first. Resuming must never
# reopen the details form over a saved draft, and a link to it is what the
# row happened to list first on 2026-10-15.
DRAFT_STEP_PREFERENCE = ("/content", "/pricing", "/details")


def _existing_draft_url(page: Any, title: str) -> str:
    """The details URL of a draft already on the Bookshelf for this title.

    Amazon allows two new titles per format per week. Re-creating a title that
    is already half-set-up spends one of those for nothing, and on 2026-09-24
    that is exactly how the limit was reached with a perfectly good draft
    sitting on the shelf. Resuming costs no slot at all.

    The row carries one link per step - details, content and pricing - and
    this used to return whichever came first in the DOM. When that was the
    details link, prepare_draft's resume branch did not recognise the URL as a
    resumable step and fell through to filling in a new title on a page that
    was not the form, which is how the 2026-10-15 re-run of Agentic Automation
    timed out waiting for #data-title while sitting on the bookshelf. Returns
    the furthest step KDP offers instead: resuming must never reopen the
    details form over a saved draft, which is what the caller says too.
    """
    try:
        page.goto("https://kdp.amazon.com/en_US/bookshelf",
                  wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(8000)
        return str(page.evaluate(
            "(wanted) => {"
            r" const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();"
            " const rows = Array.from(document.querySelectorAll('div,li'));"
            " for (const row of rows) {"
            "   const text = norm(row.innerText);"
            "   if (!text.includes(norm(wanted))) continue;"
            "   if (!text.includes('draft')) continue;"
            "   const links = Array.from(row.querySelectorAll('a'))"
            "     .map(a => a.href).filter(h => /title-setup/.test(h));"
            f"   for (const step of {json.dumps(list(DRAFT_STEP_PREFERENCE))}) {{"
            "     const hit = links.find(h => h.includes(step));"
            "     if (hit) return hit;"
            "   }"
            "   if (links.length) return links[0];"
            " } return ''; }", title) or "")
    except Exception:  # noqa: BLE001 - a failed lookup just means "create new"
        return ""


def _refuse_if_title_limit(page: Any, packet: "SubmissionPacket") -> None:
    """Stop with a recognisable error when Amazon's weekly quota is spent."""
    try:
        body = page.locator("body").inner_text(timeout=10_000)
    except Exception:  # noqa: BLE001
        return
    if KDP_TITLE_LIMIT_MARKER.lower() in (body or "").lower():
        _capture_failure(page, packet, "title_creation_limit")
        write_state(packet, "WAITING_FOR_TITLE_SLOT", url=page.url)
        raise TitleCreationLimitReached(
            "Amazon's weekly new-title limit for this format is spent (2 per "
            "format, reset Sunday 00:00 UTC). The book is finished and keeps "
            "its place; nothing needs rebuilding.")


# The print formats are the eBook form with an infix on every data-* id, plus
# an ISBN choice. Mapped off the live paperback form 2026-09-24 rather than
# guessed: #data-title does not exist there, it is #data-print-book-title.
# Shared between them: the CKEditor description (editor1), the category modal
# button, and #non-public-domain.
PRINT_FORMATS: dict[str, dict[str, str]] = {
    "paperback": {
        "label": "Paperback",
        "setup_path": "/en_US/title-setup/paperback/new/details",
        "bookshelf_control": "add-print-format",
        "create_button": r"Create paperback",
        "publish_button": r"Publish Your Paperback Book",
    },
    "hardcover": {
        "label": "Hardcover",
        "setup_path": "/en_US/title-setup/hardcover/new/details",
        "bookshelf_control": "add-hardcover-format",
        "create_button": r"Create hardcover",
        "publish_button": r"Publish Your Hardcover Book",
    },
}
PRINT_FIELD_PREFIX = "data-print-book"


def _print_field(name: str) -> str:
    """#data-title -> #data-print-book-title, and so on for the print forms."""
    return f"#{PRINT_FIELD_PREFIX}-{name}"


class EBookNotOnBookshelf(RuntimeError):
    """The eBook a print format was to be attached to is not findable."""


def print_setup_url(fmt: str, ebook_id: str, item_id: str) -> str:
    """Where KDP opens the print setup for an eBook that already exists.

    Going through the existing title is what links the formats on the product
    page, and it draws on that format's own weekly quota rather than the
    eBook's - confirmed live while the eBook quota was already spent.

    Both ids are KDP's own internal ones and neither is the ASIN. Read live
    from the bookshelf on 2026-10-14, the control KDP renders for an eBook that
    has no paperback yet points at

        .../paperback/new/details?existing=A3DDT1SA2SOXIS&item=RAQJVYXKBBX

    where "existing" is the eBook's setup id and "item" is its bookshelf row.
    This function used to take one argument and was given the ASIN, which KDP
    does not recognise: it then opened a blank print setup instead of the
    eBook's, so every print draft the floor saved became a standalone title.
    Three of them were sitting on the bookshelf - one for The Somatic Reset and
    two duplicates for Future-Proof Leadership - each holding a weekly
    paperback slot and none of them attached to the book it was the print
    edition of. Prefer open_print_setup, which clicks KDP's own control and so
    cannot drift from whatever it points at next.
    """
    spec = PRINT_FORMATS.get(fmt)
    if spec is None:
        raise ValueError(f"Unknown print format {fmt!r}; known: {', '.join(PRINT_FORMATS)}")
    return (f"https://kdp.amazon.com{spec['setup_path']}"
            f"?existing={ebook_id}&item={item_id}")


def open_print_setup(page: Any, fmt: str, asin: str) -> str:
    """Open a live eBook's print setup through KDP's own bookshelf control.

    The bookshelf search accepts an ASIN and filters to that one title, so the
    format button that is left is the one belonging to this book. Clicking it
    is what attaches the print edition to the eBook, and it keeps the internal
    ids out of our hands entirely.
    """
    spec = PRINT_FORMATS.get(fmt)
    if spec is None:
        raise ValueError(f"Unknown print format {fmt!r}; known: {', '.join(PRINT_FORMATS)}")
    # Imported here, not at module scope: the reader imports this module the
    # same way round, and only inside its functions.
    from openjarvis.tools.kdp_reports_reader import SignInRequired

    if not asin:
        raise EBookNotOnBookshelf(
            f"No eBook identifier for the {spec['label']} to attach to.")
    page.goto("https://kdp.amazon.com/en_US/bookshelf",
              wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(6000)
    if "signin" in page.url.lower():
        raise SignInRequired("KDP asked for sign-in before the bookshelf.")
    page.fill("#refreshedbookshelftable-search-input", asin)
    page.click("#refreshedbookshelftable-search-button-submit")
    page.wait_for_timeout(7000)
    control = page.locator(
        f'[id*="{spec["bookshelf_control"]}"][id$="action-button"]')
    found = control.count()
    if found != 1:
        raise EBookNotOnBookshelf(
            f"Searching the bookshelf for {asin} left {found} "
            f"{spec['label']} controls; expected exactly one.")
    control.first.click()
    page.wait_for_function(
        "fmt => location.pathname.includes(`/title-setup/${fmt}/new/`)",
        arg=fmt, timeout=90_000)
    return page.url


def fill_print_details(page: Any, packet: "SubmissionPacket", fmt: str) -> dict[str, Any]:
    """Fill a paperback or hardcover details form and stop before the upload.

    Deliberately reuses the eBook's helpers for everything KDP shares, so a fix
    to the description or the category picker lands on all three formats at
    once rather than drifting into three copies.
    """
    spec = PRINT_FORMATS[fmt]
    page.wait_for_selector(_print_field("title"), timeout=60_000)
    page.locator(_print_field("title")).fill(packet.title)
    if packet.subtitle:
        page.locator(_print_field("subtitle")).fill(packet.subtitle)
    parts = packet.author.rsplit(" ", 1)
    page.locator(_print_field("primary-author-first-name")).fill(parts[0] if len(parts) > 1 else "")
    page.locator(_print_field("primary-author-last-name")).fill(parts[-1])

    written = _set_description(page, packet.description)
    if written < 50:
        _capture_failure(page, packet, f"{fmt}_description_did_not_take")
        raise RuntimeError(f"The {spec['label']} description did not reach KDP's editor.")

    page.locator("#non-public-domain").check(force=True)
    for index, keyword in enumerate(packet.keywords):
        field = page.locator(f"{_print_field('keywords')}-{index}")
        if field.count():
            field.fill(keyword)

    if packet.ai_generated_text or packet.ai_generated_images:
        _choose(page, (r"Yes.*AI-generated", r"AI-generated content.*Yes"))
    else:
        _choose(page, (r"No.*AI-generated", r"AI-generated content.*No"))
    adult = page.locator(
        "input[name='data[print_book][is_adult_content]-radio'][value='false']")
    if adult.count():
        adult.check(force=True)

    categories = _choose_categories(page, packet)
    # KDP's own free ISBN. Buying one is a real-world purchase and a decision
    # about the imprint, so it is never made here.
    free_isbn = page.locator(_print_field("csp-isbn"))
    if free_isbn.count() and free_isbn.first.is_visible():
        free_isbn.first.check(force=True)
    return {"format": fmt, "categories": categories, "description_chars": written}


def _finish_print_content(page: Any, packet: "SubmissionPacket",
                          fmt: str) -> dict[str, Any]:
    """Answer the two questions KDP asks on the print content step.

    The AI-content answer is a legal disclosure and comes from the packet, not
    from a default. The ISBN is KDP's own free one: a purchased ISBN is a
    real-world transaction and a decision about the imprint, so only the free
    one is ever taken here, and only when it is the option already selected.

    Assigning it is deliberate rather than incidental. KDP binds a free ISBN
    to this title and format permanently - it cannot be moved or reused - so
    it is reported back in the state file rather than done quietly.
    """
    disclosed = bool(packet.ai_generated_text or packet.ai_generated_images)
    answered, pending = _answer_ai_disclosure(page, disclosed)

    # An owned ISBN is always preferred when the company holds a free one.
    # It carries the Chairman's own imprint and, unlike Amazon's, the same
    # printed edition can go to IngramSpark, Kobo or a library afterwards.
    # Taking a KDP ISBN closes that door for that edition permanently, so it
    # is only ever the fallback, and only when it has been turned on.
    owned = _owned_isbn(packet, fmt)
    if owned:
        return {"ai_content_answered": answered, "ai_content_disclosed": disclosed,
                **_use_own_isbn(page, owned)}

    assigned = ""
    if os.environ.get("ONE_KDP_ASSIGN_FREE_ISBN", "").strip().lower() in {"1", "true", "yes"}:
        assigned = _take_free_isbn(page)

    return {"ai_content_answered": answered, "ai_content_disclosed": disclosed,
            "ai_detail_pending": pending,
            "isbn": assigned, "isbn_source": "kdp_free" if assigned else "",
            "free_isbn_assigned": bool(assigned)}


# The three follow-ups KDP shows once AI use is declared. Each wants the
# degree of involvement, which is a statement of fact about how the book was
# made - not something to infer from a boolean.
_AI_DETAIL_FIELDS = ("Texts", "Images", "Translations")


def _answer_ai_disclosure(page: Any, disclosed: bool) -> tuple[bool, list[str]]:
    """Declare whether AI was used, and stop where only a person can answer.

    Saying No is complete on its own. Saying Yes opens three dropdowns asking
    how much of each kind was AI-generated, and the packet records only that
    AI was involved, never to what degree. Picking one would be inventing the
    answer to a declaration Amazon holds the publisher to, so the fields are
    reported back unanswered instead, and the draft stops short of a claim
    nobody in this company has actually made.
    """
    try:
        if not _check_ai_answer(page, disclosed):
            return False, []
        page.wait_for_timeout(4000)
    except Exception:  # noqa: BLE001 - reported, never guessed at
        return False, []

    if not disclosed:
        return True, []

    pending = [name for name in _AI_DETAIL_FIELDS if _ai_detail_unanswered(page, name)]
    return True, pending


def _ai_detail_unanswered(page: Any, label: str) -> bool:
    try:
        return bool(page.evaluate(
            "label => { const rows = Array.from(document.querySelectorAll('*'))"
            "  .filter(e => e.children.length === 0 && (e.innerText||'').trim() === label);"
            "  if (!rows.length) return false;"
            "  const row = rows[0].closest('div');"
            "  const text = row ? (row.innerText || '') : '';"
            "  return /Select/.test(text); }", label))
    except Exception:  # noqa: BLE001
        return False


def _take_free_isbn(page: Any) -> str:
    """Press Amazon's button, then confirm in the dialog it opens.

    There are two controls reading "Assign ISBN": the one on the page and the
    one inside the warning that follows it, which spells out that a free KDP
    ISBN can only be used on KDP and never with another publisher. Pressing
    only the first opened the dialog and left it open, so a draft reported an
    ISBN step that had not happened.
    """
    try:
        _click(page, (r"Assign ISBN",))
        confirm = page.get_by_role("button", name="Assign ISBN")
        # Waited for, not counted once. A single check three seconds after the
        # first click found one button whenever the dialog had not rendered
        # yet, skipped the confirm behind `if count > 1`, and left the dialog
        # open while the run reported an ISBN step that had not happened.
        page.wait_for_function(
            "() => Array.from(document.querySelectorAll('button'))"
            " .filter(b => b.offsetParent && /Assign ISBN/i.test(b.innerText||''))"
            " .length > 1", timeout=20_000)
        confirm.nth(1).click()
        page.wait_for_timeout(10_000)
        return _read_assigned_isbn(page)
    except Exception:  # noqa: BLE001
        return ""


# An ISBN-13 as KDP prints it back, hyphenated or not.
_ISBN_13 = re.compile(r"\b97[89][\d-]{10,14}\d\b")


def _read_assigned_isbn(page: Any) -> str:
    """The number Amazon just bound to this edition, read off the page.

    Read rather than assumed, because it is the only record the company gets:
    a free KDP ISBN exists nowhere else it can be looked up later, and an
    edition whose ISBN nobody wrote down is an edition nobody can cite.
    """
    try:
        text = page.locator("body").inner_text(timeout=15_000)
    except Exception:  # noqa: BLE001
        return ""
    found = _ISBN_13.search(" ".join(str(text or "").split()))
    return "".join(ch for ch in found.group(0) if ch.isdigit()) if found else ""


def _owned_isbn(packet: "SubmissionPacket", fmt: str) -> str:
    """One of the Chairman's own ISBNs for this edition, if the company has one.

    Asks the register for an ISBN already bound to this exact edition first,
    so a retried draft reuses its number instead of burning another.
    """
    register = _isbn_register()
    if register is None:
        return ""
    try:
        existing = register.for_edition(packet.title, fmt)
        if existing and existing.get("source") == register.OWNED:
            return str(existing["isbn"])
        return register.next_available()
    except Exception:  # noqa: BLE001 - a missing register must not stop a draft
        return ""


def _isbn_register() -> Any | None:
    """The company's ISBN register, or None outside the suite."""
    directory = Path(os.environ.get(
        "ONE_COMPANY_REVENUE",
        r"E:\ONE-Suite\one-company\floors\_services\revenue"))
    if not (directory / "isbns.py").is_file():
        return None
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    try:
        import importlib

        return importlib.import_module("isbns")
    except Exception:  # noqa: BLE001
        return None


def _use_own_isbn(page: Any, isbn: str) -> dict[str, Any]:
    """Type one of our own ISBNs in rather than taking Amazon's."""
    try:
        _choose(page, (r"Add your own ISBN", r"use your own ISBN"))
        page.wait_for_timeout(2000)
        field = page.locator("input[name*='isbn' i], input[id*='isbn' i]").first
        field.fill(isbn)
        page.wait_for_timeout(2000)
        return {"isbn": isbn, "isbn_source": "owned", "free_isbn_assigned": False}
    except Exception:  # noqa: BLE001 - reported, so the draft is not published blind
        return {"isbn": "", "isbn_source": "", "free_isbn_assigned": False,
                "isbn_error": f"could not enter the owned ISBN {isbn}"}


class BookNotEditable(RuntimeError):
    """KDP is not offering this book's edit controls right now."""


def _book_card(page: Any, asin: str) -> dict[str, Any]:
    """The bookshelf card for one ASIN, and the links KDP puts on it.

    Found by walking up from the title to the element that holds exactly one
    book, because the bookshelf's search box does not reliably filter and the
    internal ids in these links are not stable - the same eBook answered to
    three different ones over an afternoon. Whatever KDP renders now is what
    gets used.
    """
    return page.evaluate(
        """(wanted) => {
          const titles = document.querySelectorAll(
            '[id^="zme-indie-bookshelf-dual-itemset-itemset-metadata-title-"]');
          for (const t of titles) {
            let n = t;
            for (let i = 0; i < 16 && n.parentElement; i++) {
              const tx = n.innerText || '';
              if ((tx.match(/by /g) || []).length === 1 && tx.includes('Kindle eBook')) break;
              n = n.parentElement;
            }
            const text = n.innerText || '';
            if (!text.includes(wanted)) continue;
            const content = n.querySelector('a[href*="editkindlecontent"]');
            return {found: true, title: (t.innerText || '').trim(),
                    status: (text.match(/In review|Live|Draft|Publishing|Unpublished/) || [''])[0],
                    content: content ? content.getAttribute('href') : ''};
          }
          return {found: false};
        }""", asin)


def replace_cover(asin: str, cover_path: str | Path, *, publish: bool,
                  headless: bool = False) -> dict[str, Any]:
    """Put a new cover on a book that already exists on the bookshelf.

    Only the cover. The manuscript input sits next to it on the same step and
    is never touched: re-uploading a book's interior to change its artwork
    would put the whole thing back through conversion for nothing.

    ``publish`` is the live step and the caller must mean it - without it the
    new cover is saved as a draft against the title and nothing reaches
    readers until someone finishes it by hand.
    """
    cover = Path(cover_path)
    if not cover.is_file():
        raise FileNotFoundError(f"No cover to upload at {cover}")
    if cover.suffix.lower() not in {".jpg", ".jpeg", ".tif", ".tiff"}:
        raise ValueError(f"KDP takes JPG or TIFF covers; got {cover.suffix}")

    context = open_session(headless=headless)
    page = context.pages[0] if context.pages else context.new_page()
    try:
        page.goto("https://kdp.amazon.com/en_US/bookshelf",
                  wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(9000)
        _refuse_if_challenged(page)
        card = _book_card(page, asin)
        if not card.get("found"):
            raise BookNotEditable(f"No book on the bookshelf carries ASIN {asin}.")
        if not card.get("content"):
            # Seen live on 2026-10-15: while a title is "Publishing", KDP
            # offers no edit links at all and its only menu item is Archive.
            raise BookNotEditable(
                f"KDP is not offering edit controls for {card.get('title', asin)!r} "
                f"while it is {card.get('status') or 'in this state'}. "
                "The cover can be replaced once it is Live.")

        page.goto("https://kdp.amazon.com" + card["content"],
                  wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(12_000)
        _refuse_if_challenged(page)
        # Read live from the content step: the manuscript input accepts
        # .doc/.epub and the cover one accepts .tiff/.jpg, and they are
        # siblings. Picking by index would be picking by luck.
        field = page.locator('input[type=file][id*="data-assets-cover-file-upload"]').first
        if not field.count():
            raise BookNotEditable(
                "The cover upload field is not on this book's content step.")
        field.set_input_files(str(cover))

        deadline = datetime.now(timezone.utc).timestamp() + 15 * 60
        uploaded = False
        while datetime.now(timezone.utc).timestamp() < deadline:
            page.wait_for_timeout(5000)
            text = page.locator("body").inner_text(timeout=10_000)
            if re.search(r"[Cc]over uploaded successfully", text):
                uploaded = True
                break
        if not uploaded:
            raise RuntimeError(
                "KDP never confirmed the cover upload; nothing was saved.")

        _click(page, (r"Save and Continue",))
        page.wait_for_timeout(8000)
        result: dict[str, Any] = {"asin": asin, "title": card.get("title", ""),
                                  "cover": str(cover), "published": False,
                                  "url": page.url}
        if not publish:
            _click(page, (r"Save as Draft",), required=False)
            return result
        # The pricing step is where KDP puts the button that makes it real.
        _click(page, (r"Publish Your Kindle eBook", r"Publish Your Book",
                      r"Save and Publish"))
        page.wait_for_timeout(12_000)
        result["published"] = True
        result["url"] = page.url
        return result
    finally:
        close_session(context)


def prepare_draft(packet: SubmissionPacket, *, headless: bool = False) -> dict[str, Any]:
    """Create the eBook draft and stop before the final rights/price submit."""
    write_state(packet, "PREPARING_DRAFT")
    context = open_session(headless=headless)
    page = next((candidate for candidate in context.pages
                 if "/title-setup/kindle/new/details" in candidate.url),
                context.pages[0] if context.pages else context.new_page())
    try:
        # Always start from the create page, even when the tab already shows
        # a details form. Re-using it inherits whatever the last run left -
        # on 2026-09-24 a category modal stayed open and its scroller ate
        # every click, while the button underneath read "Edit categories"
        # because the previous attempt had already set them.
        page.goto(KDP_CREATE_URL, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(2500)
        if "signin" in page.url.lower() or page.get_by_text("Sign in", exact=True).count():
            write_state(packet, "LOGIN_REQUIRED", url=page.url)
            raise RuntimeError(
                "KDP login expired. Sign in to the dedicated KDP browser; this job will resume automatically."
            )
        # Resume before creating. A half-finished draft on the shelf is worth
        # more than a fresh one: finishing it costs no title slot, and Amazon
        # only grants two per format per week.
        resumed = _existing_draft_url(page, packet.title)
        if resumed:
            page.goto(resumed, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(4000)
            if "/title-setup/" not in page.url:
                # KDP bounced us, usually back to the bookshelf. Falling
                # through from here fills a new title into whatever page this
                # is and then times out on a control that was never there, so
                # the error named #data-title instead of the redirect.
                _capture_failure(page, packet, "draft_would_not_reopen")
                raise RuntimeError(
                    f"KDP would not reopen the saved draft at {resumed} - it "
                    f"sent us to {page.url} instead. The draft is still on the "
                    f"bookshelf; nothing was created or overwritten.")
            if re.search(r"/title-setup/kindle/[^/]+/(content|pricing)", page.url):
                # The manuscript and cover were already accepted before a
                # later failure. Resume from KDP's current stage; never
                # reopen the details form and overwrite a saved draft.
                content = {}
                if "/content" in page.url:
                    content = _complete_ebook_content(page, packet)
                _choose(page, (r"All territories", r"worldwide rights"), required=False)
                pricing = _set_pricing(page, packet)
                _click(page, (r"Save as Draft",), required=False)
                screenshot = str(Path(packet.run_dir) / "kdp_draft_ready.png")
                page.screenshot(path=screenshot, full_page=True)
                return write_state(packet, "READY_FOR_APPROVAL", draft_url=page.url,
                                   evidence_screenshot=screenshot, pricing=pricing, content=content)
        else:
            page.goto(KDP_CREATE_URL, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(2500)
            if "/title-setup/kindle/new/details" not in page.url:
                _click(page, (r"Create eBook", r"Kindle eBook"))
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(3000)
            # Only a NEW title can hit the weekly quota, so this is the one
            # place worth checking for it.
            _refuse_if_title_limit(page, packet)
        # On a new title #data-title is the text box. On a saved draft the same
        # id is a read-only div over a hidden input, and filling it times out,
        # so only the editable box is ever filled.
        page.wait_for_selector("#data-title", state="attached", timeout=60_000)
        title_box = page.locator("input#data-title[type='text']")
        if title_box.count() and title_box.first.is_editable():
            title_box.first.fill(packet.title)
        if packet.subtitle:
            page.locator("#data-subtitle").fill(packet.subtitle)
        author_parts = packet.author.rsplit(" ", 1)
        first_name = author_parts[0] if len(author_parts) > 1 else ""
        last_name = author_parts[-1]
        page.locator("#data-primary-author-first-name").fill(first_name)
        page.locator("#data-primary-author-last-name").fill(last_name)
        written = _set_description(page, packet.description)
        if written < 50:
            _capture_failure(page, packet, "description_did_not_take")
            raise RuntimeError(
                "The description did not reach KDP's editor, so the form would"
                " be refused with 'Enter a description'.")
        page.locator("#non-public-domain").check(force=True)
        for index, keyword in enumerate(packet.keywords, start=1):
            page.locator(f"#data-keywords-{index - 1}").fill(keyword)
        # The AI disclosure is no longer on this page: KDP asks it on the
        # content step, where _complete_ebook_content answers it.
        page.locator("input[name='data[is_adult_content]-radio'][value='false']").check(force=True)
        chosen_categories = _choose_categories(page, packet)

        # Save details before upload. KDP wording differs across locales, so
        # role/name fallbacks are preferred over brittle generated classes.
        _click(page, (r"Save and Continue", r"Save as Draft"))
        # KDP saves the details and then routes to the content step, which
        # takes several seconds. A fixed 2.5s wait read the page mid-save and
        # reported that it had not advanced while it was still advancing -
        # with no error on the page to explain it. Wait for the destination.
        try:
            page.wait_for_function(
                "() => location.pathname.includes('/content')"
                " || document.querySelectorAll('input[type=file]').length > 0",
                timeout=90000)
        except Exception:
            pass          # the capture below says what the page actually shows
        # KDP's upload inputs sit behind styled buttons, so they are attached
        # but never visible; waiting for visibility times out on a page that is
        # perfectly ready.
        try:
            page.wait_for_selector("input[type=file]", state="attached", timeout=60_000)
        except Exception:  # noqa: BLE001 - the count check below reports it
            pass
        file_inputs = page.locator("input[type=file]")
        if file_inputs.count() < 1:
            # Failing here used to leave nothing to look at: the run stopped on
            # the details step with no screenshot and no page text, so the only
            # evidence was a one-line message that named the wrong cause. KDP is
            # a live third-party form and its wording moves, so capture what the
            # page actually said before giving up.
            _capture_failure(page, packet, "details_did_not_advance")
            raise RuntimeError(
                "KDP did not advance past the details step, so the manuscript"
                " upload field never appeared. See the screenshot and page"
                " notes written beside the book.")
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

        content = _complete_ebook_content(page, packet)
        _choose(page, (r"All territories", r"worldwide rights"))
        pricing = _set_pricing(page, packet)
        _click(page, (r"Save as Draft",), required=False)
        screenshot = str(Path(packet.run_dir) / "kdp_draft_ready.png")
        page.screenshot(path=screenshot, full_page=True)
        return write_state(packet, "READY_FOR_APPROVAL", draft_url=page.url,
                           evidence_screenshot=screenshot, pricing=pricing,
                           categories=chosen_categories, content=content)
    except Exception as exc:
        _refuse_if_challenged(page)
        if isinstance(exc, AmazonChallenge):
            raise
        write_state(packet, "BLOCKED", error=f"{type(exc).__name__}: {exc}", url=page.url)
        raise
    finally:
        close_session(context)


def existing_print_draft(packet: SubmissionPacket, fmt: str) -> str:
    """The draft URL this format already reached, if there is one.

    Amazon grants two new titles per format per week. Starting a fresh draft
    to finish a step a saved one is already waiting at spends one of those two
    and leaves a duplicate behind - and the things that interrupt a print
    draft are ordinary: a verification code, a slow upload, a control that
    moved. So a draft is resumed when there is one to resume.
    """
    try:
        prior = json.loads(state_path(packet).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if prior.get("stage") == "AWAITING_LOGIN":
        prior = prior.get("resume_state", prior)
    if prior.get("checksums") != packet.checksums:
        return ""               # the book changed; its old draft is not this one
    url = str(prior.get("draft_url") or "")
    return url if f"/{fmt}/" in url else ""


def finish_print_draft(packet: SubmissionPacket, fmt: str, draft_url: str, *,
                       headless: bool = False) -> dict[str, Any]:
    """Reopen a saved print draft and answer what it is still waiting on."""
    context = open_session(headless=headless)
    page = context.pages[0] if context.pages else context.new_page()
    try:
        page.goto(draft_url, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(8000)
        _refuse_if_challenged(page)
        content = _finish_print_content(page, packet, fmt)
        screenshot = str(Path(packet.run_dir) / f"kdp_{fmt}_ready.png")
        page.screenshot(path=screenshot, full_page=True)
        return write_state(packet, f"{fmt.upper()}_READY", draft_url=page.url,
                           evidence_screenshot=screenshot, resumed=True, **content)
    except Exception as exc:
        _refuse_if_challenged(page)
        if isinstance(exc, AmazonChallenge):
            raise
        write_state(packet, "BLOCKED", error=f"{type(exc).__name__}: {exc}", url=page.url)
        raise
    finally:
        close_session(context)


def prepare_print_draft(packet: SubmissionPacket, fmt: str, ebook_asin: str, *,
                        interior_path: str | Path, cover_path: str | Path,
                        headless: bool = False) -> dict[str, Any]:
    """Set up the paperback or hardcover of a book whose eBook already exists.

    Opened through the existing eBook so KDP links the formats on one product
    page. The interior is the print-formatted manuscript, not the eBook's - the
    factory emits A4, which is not a KDP trim; see kdp_print_interior. The
    cover is the print wrap, not the flat eBook cover.

    A draft this book already reached is resumed rather than replaced, because
    a second one costs a weekly title slot and leaves a duplicate.
    """
    resume = existing_print_draft(packet, fmt)
    if resume:
        return finish_print_draft(packet, fmt, resume, headless=headless)

    spec = PRINT_FORMATS.get(fmt)
    if spec is None:
        raise ValueError(f"Unknown print format {fmt!r}")
    interior, cover = Path(interior_path), Path(cover_path)
    for label, path in (("interior", interior), ("cover", cover)):
        if not path.is_file():
            raise FileNotFoundError(f"{spec['label']} {label} missing at {path}")

    write_state(packet, f"PREPARING_{fmt.upper()}")
    context = open_session(headless=headless)
    page = context.pages[0] if context.pages else context.new_page()
    try:
        # Clicked on the bookshelf rather than navigated to, because the link
        # between the eBook and its print edition is made by KDP's own control
        # and by nothing we can assemble from an ASIN.
        from openjarvis.tools.kdp_reports_reader import SignInRequired
        try:
            open_print_setup(page, fmt, ebook_asin)
        except SignInRequired:
            write_state(packet, "LOGIN_REQUIRED", url=page.url)
            raise AmazonChallenge("KDP login required; sign in to resume this job.") from None
        page.wait_for_timeout(4000)
        # Each format carries its own weekly allowance, so this is checked per
        # format rather than once for the book.
        _refuse_if_title_limit(page, packet)

        details = fill_print_details(page, packet, fmt)
        _click(page, (r"Save and Continue", r"Save as Draft"))
        try:
            page.wait_for_function(
                "() => location.pathname.includes('/content')"
                " || document.querySelectorAll('input[type=file]').length > 0",
                timeout=90000)
        except Exception:  # noqa: BLE001 - the capture below explains it
            pass
        try:
            page.wait_for_selector("input[type=file]", state="attached", timeout=60_000)
        except Exception:  # noqa: BLE001
            pass
        uploads = page.locator("input[type=file]")
        if uploads.count() < 2:
            _capture_failure(page, packet, f"{fmt}_content_step_missing_uploads")
            # Say what actually happened. The first time this fired, the page
            # was Amazon's two-step verification asking for a code sent to the
            # owner's phone, and the message blamed missing upload fields -
            # which sent the reader looking at the form instead of at the
            # challenge. A page that is not the form cannot be missing part of
            # it.
            _refuse_if_challenged(page)
            raise RuntimeError(
                f"KDP did not offer both {spec['label']} upload fields; see the "
                f"screenshot and page notes beside the book.")
        uploads.nth(0).set_input_files(str(interior))
        page.wait_for_timeout(20000)
        uploads.nth(1).set_input_files(str(cover))
        page.wait_for_timeout(20000)

        # Both of these live on the print content step, not on details where
        # the eBook keeps them. Measured on the live paperback form
        # 2026-10-02: the draft reached PAPERBACK_READY with both files
        # uploaded and could go no further, because KDP was still asking for
        # an ISBN and for the AI-content answer. The details-page attempt at
        # the ISBN found no such control and skipped in silence, which is how
        # a step that never ran looked like a step that had.
        content = _finish_print_content(page, packet, fmt)

        screenshot = str(Path(packet.run_dir) / f"kdp_{fmt}_ready.png")
        page.screenshot(path=screenshot, full_page=True)
        return write_state(packet, f"{fmt.upper()}_READY", draft_url=page.url,
                           evidence_screenshot=screenshot, interior=str(interior),
                           cover=str(cover), **details, **content)
    except Exception as exc:
        _refuse_if_challenged(page)
        if isinstance(exc, AmazonChallenge):
            raise
        write_state(packet, "BLOCKED", error=f"{type(exc).__name__}: {exc}", url=page.url)
        raise
    finally:
        close_session(context)


def submit_approved(packet: SubmissionPacket, approval_id: str, *, headless: bool = False) -> dict[str, Any]:
    """Submit an already prepared draft after a per-title A3 approval."""
    if not approval_id.strip():
        raise ValueError("A per-title Olympus approval id is required")
    prior = json.loads(state_path(packet).read_text(encoding="utf-8"))
    if prior.get("stage") == "AWAITING_LOGIN":
        prior = prior.get("resume_state", prior)
    if prior.get("stage") != "READY_FOR_APPROVAL":
        raise ValueError("KDP draft is not ready for approval")
    if prior.get("checksums") != packet.checksums:
        raise ValueError("Submission files changed after review; prepare a new draft")

    context = open_session(headless=headless)
    page = context.pages[0] if context.pages else context.new_page()
    try:
        page.goto(str(prior["draft_url"]), wait_until="domcontentloaded", timeout=90_000)
        _refuse_if_challenged(page)
        # The exact label varies by format and marketplace. Never fall back to
        # coordinates: a missing semantic control is a safe failure.
        _click(page, (r"Publish Your Kindle eBook", r"Publish.*eBook"))
        page.wait_for_timeout(2500)
        _refuse_if_challenged(page)
        screenshot = str(Path(packet.run_dir) / "kdp_submitted.png")
        page.screenshot(path=screenshot, full_page=True)
        return write_state(packet, "SUBMITTED", approval_id=approval_id,
                           submitted_at=_now(), evidence_screenshot=screenshot)
    except Exception:
        _refuse_if_challenged(page)
        raise
    finally:
        close_session(context)


def poll_asin(packet: SubmissionPacket, *, headless: bool = True) -> dict[str, Any]:
    """Check KDP Bookshelf once; caller schedules retries until ASIN appears."""
    context = open_session(headless=headless)
    page = context.pages[0] if context.pages else context.new_page()
    try:
        page.goto("https://kdp.amazon.com/en_US/bookshelf", wait_until="domcontentloaded", timeout=90_000)
        _refuse_if_challenged(page)
        title = page.get_by_text(packet.title, exact=False).first
        if not title.count():
            return write_state(packet, "AWAITING_ASIN", kdp_status="title_not_visible")

        # Bookshelf rows are nested tables. Scope evidence to the outer title
        # row so an adjacent live book's ASIN can never be attributed here.
        title_row = title.locator(
            "xpath=ancestor::tr[contains(@class,'mt-row')][last()]"
        )
        nearby = title_row.inner_text(timeout=20_000)
        match = ASIN_RE.search(nearby)
        status_match = re.search(r"\b(Draft|In Review|Publishing|Live|Blocked)\b", nearby, re.I)
        if match:
            return write_state(packet, "ASIN_ASSIGNED", asin=match.group(0).upper(),
                               kdp_status=status_match.group(0) if status_match else "unknown")
        return write_state(packet, "AWAITING_ASIN",
                           kdp_status=status_match.group(0) if status_match else "unknown")
    except Exception:
        _refuse_if_challenged(page)
        raise
    finally:
        close_session(context)
