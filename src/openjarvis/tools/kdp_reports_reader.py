"""Read KDP's own payments report from the owner's signed-in browser.

Why a browser and not an API
----------------------------
There is no KDP payments API. Amazon publishes Ads and Attribution APIs, and
SP-API explicitly excludes KDP data, so the report page is the integration -
not a workaround for one. Nothing is sent anywhere: this opens the page the
owner already sees, in the owner's own profile, and reads it. The numbers stay
on this machine.

Status is not the same as settled
---------------------------------
KDP marks a payment "Paid" as soon as it is scheduled, with the payment date
in the future. On 2026-09-24 the report showed two rows as Paid, dated
2026-09-29: INR 478.97 and INR 223.44. Banking those on status alone would put
INR 702.41 on the books five days before it exists. The date is what decides,
so this splits the report rather than filtering it:

* settled   - payment date has arrived; this is money the company has.
* scheduled - promised, dated ahead; reported, never banked.

On the 29th the same rows read as settled with no special case and no manual
step, because nothing about them changed except the calendar.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

PAYMENTS_URL = "https://kdpreports.amazon.com/payments"

# Payment Number | Marketplace | Status | Date | Method | Net | FX | Payout
_ROW = re.compile(
    r"(?P<number>\d{6,})\s+"
    r"(?P<marketplace>Amazon\.[a-z.]+)\s+"
    r"(?P<status>[A-Za-z ]+?)\s+"
    r"(?P<paid_on>\d{4}-\d{2}-\d{2})\s+"
    r"(?P<method>[A-Z]{2,4})\s+"
    r"(?P<net_currency>[A-Z]{3})\s+(?P<net>[\d.,]+)\s+"
    r"(?P<fx>N/A|[\d.,]+)\s+"
    r"(?P<payout_currency>[A-Z]{3})\s+(?P<payout>[\d.,]+)"
)


@dataclass(frozen=True)
class Payment:
    number: str
    marketplace: str
    status: str
    paid_on: str
    method: str
    net_currency: str
    net_amount: float
    fx_rate: float | None
    payout_currency: str
    payout_amount: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _number(text: str) -> float:
    return float(str(text).replace(",", ""))


def parse_payments(page_text: str) -> list[Payment]:
    """Every payment row in the report page's text.

    Parsed from the rendered text rather than the DOM on purpose: Amazon's
    table markup is generated and changes, while the row's shape - a long
    payment number, a marketplace, a status, an ISO date, then two currency
    amounts around an FX rate - has not.
    """
    payments: list[Payment] = []
    for match in _ROW.finditer(" ".join(str(page_text or "").split())):
        fx = match.group("fx")
        payments.append(Payment(
            number=match.group("number"),
            marketplace=match.group("marketplace"),
            status=match.group("status").strip(),
            paid_on=match.group("paid_on"),
            method=match.group("method"),
            net_currency=match.group("net_currency"),
            net_amount=_number(match.group("net")),
            fx_rate=None if fx == "N/A" else _number(fx),
            payout_currency=match.group("payout_currency"),
            payout_amount=_number(match.group("payout")),
        ))
    return payments


def split_by_settlement(payments: list[Payment], today: date | None = None) -> dict[str, Any]:
    """Split the report into money the company has and money it is owed."""
    when = today or date.today()
    settled, scheduled, rejected = [], [], []
    for payment in payments:
        if payment.status.strip().lower() not in {"paid", "payment sent"}:
            # Cancelled, on hold, returned: reported so it is visible, never
            # counted either way.
            rejected.append(payment)
            continue
        try:
            due = datetime.strptime(payment.paid_on, "%Y-%m-%d").date()
        except ValueError:
            rejected.append(payment)
            continue
        (settled if due <= when else scheduled).append(payment)
    return {
        "as_of": when.isoformat(),
        "settled": [p.to_dict() for p in settled],
        "scheduled": [p.to_dict() for p in scheduled],
        "rejected": [p.to_dict() for p in rejected],
        "settled_total": round(sum(p.payout_amount for p in settled), 2),
        "scheduled_total": round(sum(p.payout_amount for p in scheduled), 2),
        "currency": (settled or scheduled or [None])[0].payout_currency if (settled or scheduled) else "",
    }


BOOKSHELF_URL = "https://kdp.amazon.com/en_US/bookshelf"

# "Manage title" is the one marker that appears exactly once per book, right
# after its name, so it is the seam the shelf is cut on. Two earlier attempts
# used a single regex spanning title to ASIN: the first paired them by position
# and produced titles like "fied Filter by: Filter by: All Draft", because the
# shelf's own filter controls sit between rows; the second tied them together
# and matched only the first two books, because the gap to the ASIN is not a
# fixed length once a book has paperback and hardcover sections. Splitting is
# shorter and does not care how much furniture Amazon puts between rows.
_SHELF_SEAM = "Manage title"
_AUTHOR_TAIL = re.compile(r"\s+by\s+[A-Z][\w .'-]{2,40}")
_KINDLE_ROW = re.compile(
    r"Kindle eBook\s+(?P<status>Live|In review|Draft|Blocked|Publishing)\b",
    re.IGNORECASE,
)
_ASIN = re.compile(r"ASIN:\s*(?P<asin>B0[A-Z0-9]{8})")
_USD = re.compile(r"\$?([\d.]+)\s+USD")
# Whether a title is enrolled in KDP Select decides whether it may legally be
# sold anywhere but Kindle, so it is read rather than assumed. The shelf prints
# it right after the author and before the seam: "... by Vineet Pandey KDP
# Select: eBook enrolled Manage title". A title with no such phrase is not
# recorded as unenrolled, only as unknown - see parse_bookshelf.
_KDP_SELECT = re.compile(r"KDP Select:?\s*eBook\s+(?P<state>enrolled|not enrolled)",
                         re.IGNORECASE)
# The real publication date, which the listings table never had. Needed to know
# when a 90-day exclusivity term began.
_SUBMITTED = re.compile(r"Submitted on ([A-Z][a-z]+ \d{1,2}, \d{4})")
# Ordered last-wins: whichever of these appears latest is where the shelf's
# controls stop and the next book's name begins.
_SHELF_FURNITURE = (
    "Search by title: Search",
    "Why offer multiple formats?",
    "Link existing hardcover",
    "Link existing paperback",
    "+ Create hardcover",
    "+ Create paperback",
)


def _submitted_iso(body: str) -> str:
    """The shelf's "Submitted on September 13, 2026" as a date, or ""."""
    found = _SUBMITTED.search(body)
    if not found:
        return ""
    try:
        return datetime.strptime(found.group(1), "%B %d, %Y").date().isoformat()
    except ValueError:
        return ""


def parse_bookshelf(page_text: str) -> list[dict[str, Any]]:
    """Every Kindle title on the shelf that has an ASIN, with its status.

    A draft has no ASIN and is deliberately not returned: it is not a listing
    anyone can buy, and the board counts what is purchasable.

    Also reads each title's KDP Select enrolment and publication date, because
    those two facts together are what decide whether a book may be sold
    anywhere but Kindle. ``kdp_select`` is None rather than False when the
    shelf does not say: a title assumed unenrolled and then published wide
    would breach the exclusivity term, so silence has to stay silence.
    """
    chunks = " ".join(str(page_text or "").split()).split(_SHELF_SEAM)
    titles: list[dict[str, Any]] = []
    for index in range(1, len(chunks)):
        # The book's name is the tail of the chunk before the seam: "<title>
        # by <Author>". Everything earlier in that chunk belongs to the
        # previous book's formats.
        # What precedes the title is the previous book's format controls, or -
        # for the first book - the shelf's filter bar. Each ends with a phrase
        # that never appears inside a book's name, so the title is whatever
        # follows the last of them. Cut the furniture first, then the author:
        # doing it the other way round leaves "Case Study Seven by Vineet
        # Pandey KDP Select: eBook", because the author is not always last.
        name = chunks[index - 1].strip()
        for furniture in _SHELF_FURNITURE:
            if furniture in name:
                name = name.rsplit(furniture, 1)[-1].strip()
        # Read before the author is cut: the enrolment phrase sits after the
        # author's name, so _AUTHOR_TAIL would take it away with everything
        # else it trims.
        enrolment = _KDP_SELECT.search(name)
        name = _AUTHOR_TAIL.split(name)[0].strip()
        body = chunks[index]
        kindle, asin = _KINDLE_ROW.search(body), _ASIN.search(body)
        if not kindle or not asin:
            continue          # a draft: real, but nobody can buy it yet
        price = _USD.search(body[kindle.end():asin.start()])
        titles.append({
            "asin": asin.group("asin"),
            "status": kindle.group("status").strip().lower(),
            "price_usd": float(price.group(1)) if price else None,
            "title": name[-180:].strip(),
            "kdp_select": (enrolment.group("state").lower() == "enrolled"
                           if enrolment else None),
            "submitted_on": _submitted_iso(body),
        })
    return titles


class SignInRequired(RuntimeError):
    """Amazon wants a person at the keyboard, and ONE will not be that person.

    Its own type so a caller can tell it apart from a page that merely failed
    to load: one needs the owner, the other needs a retry, and answering the
    first with the second wastes the run.
    """


SIGNIN_ATTEMPTS = 3


def _open_and_read(page: Any, url: str, marker: str, *, what: str,
                   attempts: int = SIGNIN_ATTEMPTS) -> str:
    """Load a KDP page and return its text once it has finished arriving.

    Waits for the page's own content rather than for a clock. The first
    version slept a flat nine seconds and then failed if the URL contained
    "signin", which reads an unfinished redirect as a logged-out profile.

    One bounce to the sign-in page is not proof of anything
    -----------------------------------------------------
    Amazon challenges this profile intermittently. Measured on 2026-09-24
    within a single minute, same profile, same headless browser: two reads
    returned the report and one landed on /ap/signin. Treating that one as a
    logged-out profile is what made the nightly sync report "needs its
    one-time login" while the session was in fact live - and it asked the
    owner for a password that was not actually missing.

    So a bounce is retried. Only a profile that lands on the sign-in form on
    every attempt has really been logged out, and then the job refuses rather
    than typing anything: ONE never handles the password.
    """
    last: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        page.goto(url, wait_until="domcontentloaded", timeout=120_000)
        try:
            page.wait_for_function(
                "marker => document.body && document.body.innerText.includes(marker)",
                arg=marker, timeout=75_000,
            )
            return page.locator("body").inner_text(timeout=20_000)
        except Exception as exc:  # noqa: BLE001 - the URL says which failure this is
            last = exc
            if "signin" not in page.url.lower():
                raise RuntimeError(
                    f"{what} did not finish loading within 75s; the page ended "
                    f"at {page.url}") from exc
            if attempt < attempts:
                # The bounce usually clears on the next hit, once Amazon has
                # re-issued the session cookie it just asked for.
                page.wait_for_timeout(5000)

    raise SignInRequired(
        f"Amazon sent this profile to the sign-in form on all {attempts} "
        f"attempts while opening {what}. ONE never types a password - run "
        "kdp-login.ps1 and sign in there. Before doing that, check the browser "
        "is starting in Chrome's new headless mode: the payments host refuses "
        "the old one and bounces it here, which looks identical to being "
        "logged out and is not.") from last


def read_bookshelf(*, headless: bool = True) -> list[dict[str, Any]]:
    """The owner's KDP shelf, read from their own profile."""
    from openjarvis.tools.kdp_browser_publisher import close_session

    context = _own_session(headless=headless)
    page = context.pages[0] if context.pages else context.new_page()
    try:
        text = _open_and_read(page, BOOKSHELF_URL, _SHELF_SEAM, what="the KDP bookshelf")
    finally:
        close_session(context)
    return parse_bookshelf(text)


def _own_session(*, headless: bool) -> Any:
    """The owner's KDP profile, and nothing else.

    Deliberately not the publisher's open_session(): that attaches to whatever
    is listening on LAO_KDP_CDP_URL first, which is right for a publish the
    owner is watching and wrong for a nightly read. On 2026-09-24 a debug
    Chrome unrelated to KDP was on that port and the reader landed on a
    sign-in page while the signed-in profile sat unused. A scheduled job must
    depend on the profile, not on which window happens to be open.
    """
    from playwright.sync_api import sync_playwright

    from openjarvis.tools.kdp_browser_publisher import profile_dir

    playwright = sync_playwright().start()
    # Always a real window. "headless" here means the owner should not see it,
    # not that Chrome runs headless - the window is simply parked off-screen.
    #
    # This took three wrong answers to pin down, each of which looked right
    # for a few days:
    #
    #   "the password expired"        it had not; the profile was never
    #                                 logged out, and the owner re-signed-in
    #                                 twice for nothing.
    #   "kdpreports re-authenticates" closer, but it blamed a schedule.
    #   "old headless is refused"     true, and still not the whole thing:
    #                                 --headless=new worked on 2026-09-29 and
    #                                 failed on 2026-10-02.
    #
    # What the evidence actually says, measured both days: a headed visit
    # works with nothing typed, and headless works immediately afterwards and
    # for a few days, then stops. The payments host's session can only be
    # minted by a real window; headless can ride one that exists but cannot
    # renew it. --headless=new passed on the 29th only because a headed test
    # had minted a session minutes earlier - which is exactly the trap the
    # first two answers fell into as well.
    #
    # So the nightly read uses a real window every time, which both reads and
    # renews, and parks it at -32000,-32000 so nobody watches it happen. The
    # bookshelf host never cared either way.
    args = ["--disable-blink-features=AutomationControlled"]
    if headless:
        args = ["--window-position=-32000,-32000", "--window-size=1440,1000", *args]
    context = playwright.chromium.launch_persistent_context(
        str(profile_dir()), channel="chrome", headless=False,
        viewport={"width": 1440, "height": 1000},
        args=args,
    )
    context._lao_playwright = playwright  # type: ignore[attr-defined]
    return context


def read_payments(*, headless: bool = True, today: date | None = None) -> dict[str, Any]:
    """Open the report in the owner's KDP profile and return the split."""
    from openjarvis.tools.kdp_browser_publisher import close_session

    context = _own_session(headless=headless)
    page = context.pages[0] if context.pages else context.new_page()
    try:
        # "Payout Amount" is the report's own column heading: it exists only
        # once the table itself has rendered, so waiting for it cannot be
        # satisfied by a loading shell or a redirect hop.
        text = _open_and_read(page, PAYMENTS_URL, "Payout Amount",
                              what="the payments report")
    finally:
        close_session(context)
    payments = parse_payments(text)
    if not payments:
        raise RuntimeError("No payment rows were found on KDP's payments report")
    return {"source": PAYMENTS_URL, **split_by_settlement(payments, today)}
