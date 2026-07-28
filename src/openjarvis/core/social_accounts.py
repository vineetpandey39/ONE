"""Per-channel social publishing accounts, with a hard cross-post guard.

Why this exists
---------------
ONE will post finished videos to Facebook and Instagram for several separate
brands/channels (ImagineIndia today, more later). Each channel has its OWN
Facebook Page and Instagram account. The one thing that must never happen is a
video going out on the wrong brand's account. The old vault held a single
global ``INSTAGRAM_ACCESS_TOKEN`` injected into ``os.environ`` -- fine for one
account, unusable (and dangerous) for many, because a second account's token
would silently overwrite the first under the same env key.

The model here
--------------
* Each channel is registered by a human name -> a stable slug.
* Its credentials live in dedicated vault sections, isolated per channel:
      [social_<slug>_instagram]  INSTAGRAM_ACCESS_TOKEN / _BUSINESS_ACCOUNT_ID / _EXPECTED_USERNAME
      [social_<slug>_facebook]   FACEBOOK_PAGE_ACCESS_TOKEN / _PAGE_ID / _EXPECTED_PAGE_NAME
  They are read straight from credentials.toml by section (never via the shared
  os.environ), so two channels' same-named keys can't collide.
* There is NO global/default account. To post you MUST name a channel.
* ``resolve_for_post`` re-verifies, live against the Graph API, that the token
  really belongs to THIS channel's registered account and identity before it
  hands any credentials to a poster. Any mismatch raises CrossPostGuardError --
  so even a token pasted into the wrong slot cannot post to the wrong account.
* The same underlying account id can't be registered under two channels.

Nothing here is ever hard-coded: tokens are entered by the user into the vault
(set-social-account.ps1 / the /credentials page) and this module only reads
them back. Per the standing vault-only rule, credentials.toml lives outside the
repo (~/.openjarvis) and is never committed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from openjarvis.core import credentials as _vault

# ---------------------------------------------------------------------------
# Schema: which keys each platform stores. The *_EXPECTED_* field is the
# human-recognisable identity used by the cross-post guard.
# ---------------------------------------------------------------------------
PLATFORMS: dict[str, dict[str, Any]] = {
    "instagram": {
        "token_key": "INSTAGRAM_ACCESS_TOKEN",
        "id_key": "INSTAGRAM_BUSINESS_ACCOUNT_ID",
        "expected_key": "INSTAGRAM_EXPECTED_USERNAME",
        "identity_field": "username",  # Graph API field on the account node
        "label": "Instagram",
    },
    "facebook": {
        "token_key": "FACEBOOK_PAGE_ACCESS_TOKEN",
        "id_key": "FACEBOOK_PAGE_ID",
        "expected_key": "FACEBOOK_EXPECTED_PAGE_NAME",
        "identity_field": "name",
        "label": "Facebook Page",
    },
}

_CHANNELS_SECTION = "social_channels"  # slug -> display name registry
_GRAPH = "https://graph.facebook.com/v21.0"
_TIMEOUT = 15


class SocialAccountError(Exception):
    """Base error for social-account configuration problems."""


class CrossPostGuardError(SocialAccountError):
    """Raised when a channel's stored credentials do not verifiably belong to
    that channel's registered account. Posting must be refused."""


@dataclass
class Account:
    channel: str          # slug
    channel_name: str     # human display name
    platform: str         # "instagram" | "facebook"
    token: str
    account_id: str
    expected_identity: str | None


# ---------------------------------------------------------------------------
# Slugs & registry
# ---------------------------------------------------------------------------
def slugify(name: str) -> str:
    """Human channel name -> stable bare-key-safe slug (a-z0-9-)."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    if not slug:
        raise ValueError(f"Channel name '{name}' has no usable characters for a slug")
    return slug


def _section(slug: str, platform: str) -> str:
    if platform not in PLATFORMS:
        raise ValueError(f"Unknown platform '{platform}' (expected one of {list(PLATFORMS)})")
    return f"social_{slug}_{platform}"


def register_channel(name: str, *, path=None) -> str:
    """Register (or look up) a channel by human name; returns its slug.
    Idempotent -- re-registering the same name is a no-op that returns the slug."""
    slug = slugify(name)
    existing = _vault.get_section_credential(_CHANNELS_SECTION, slug, path=path)
    if existing is None:
        _vault.save_section_credential(_CHANNELS_SECTION, slug, name, path=path)
    return slug


def channel_name(slug: str, *, path=None) -> str:
    return _vault.get_section_credential(_CHANNELS_SECTION, slug, path=path) or slug


def list_channel_slugs(*, path=None) -> list[str]:
    creds = _vault.load_credentials(path=path)
    return sorted((creds.get(_CHANNELS_SECTION) or {}).keys())


# ---------------------------------------------------------------------------
# Writing credentials (used by the CLI / PS1 helper -- never with baked-in values)
# ---------------------------------------------------------------------------
def set_account_field(channel: str, platform: str, key: str, value: str, *, path=None) -> None:
    """Store one field (token / id / expected identity) for a channel's platform
    account. ``channel`` may be a slug or a human name (it is slugified)."""
    slug = slugify(channel)
    spec = PLATFORMS.get(platform)
    if not spec:
        raise ValueError(f"Unknown platform '{platform}'")
    allowed = [spec["token_key"], spec["id_key"], spec["expected_key"]]
    if key not in allowed:
        raise ValueError(f"Key '{key}' not valid for {platform} (allowed: {allowed})")

    # Cross-channel duplicate-account guard: the same account id must not be
    # claimed by two different channels.
    if key == spec["id_key"]:
        for other in list_channel_slugs(path=path):
            if other == slug:
                continue
            other_id = _vault.get_section_credential(_section(other, platform), spec["id_key"], path=path)
            if other_id and other_id.strip() == value.strip():
                raise SocialAccountError(
                    f"{spec['label']} account id {value!r} is already registered to "
                    f"channel '{channel_name(other, path=path)}'. Refusing to attach the "
                    f"same account to two channels."
                )

    register_channel(channel, path=path)
    _vault.save_section_credential(_section(slug, platform), key, value, allowed=allowed, path=path)


def clear_account(channel: str, platform: str, *, path=None) -> None:
    """Remove all stored fields for a channel's platform account."""
    slug = slugify(channel)
    spec = PLATFORMS[platform]
    for key in (spec["token_key"], spec["id_key"], spec["expected_key"]):
        _vault.delete_section_credential(_section(slug, platform), key, path=path)


# ---------------------------------------------------------------------------
# Reading credentials (per-channel, straight from the TOML -- no env collisions)
# ---------------------------------------------------------------------------
def get_account(channel: str, platform: str, *, path=None) -> Account | None:
    """Return the stored Account for a channel+platform, or None if the token
    or account id is missing. Reads by section from credentials.toml, so
    multiple channels' accounts coexist without clobbering each other."""
    slug = slugify(channel)
    spec = PLATFORMS.get(platform)
    if not spec:
        raise ValueError(f"Unknown platform '{platform}'")
    sect = _section(slug, platform)
    token = _vault.get_section_credential(sect, spec["token_key"], path=path)
    acct_id = _vault.get_section_credential(sect, spec["id_key"], path=path)
    if not token or not acct_id:
        return None
    return Account(
        channel=slug,
        channel_name=channel_name(slug, path=path),
        platform=platform,
        token=token.strip(),
        account_id=acct_id.strip(),
        expected_identity=(_vault.get_section_credential(sect, spec["expected_key"], path=path) or None),
    )


def account_status(channel: str, platform: str, *, path=None) -> dict[str, bool]:
    """{field: configured?} for a channel's platform account -- for dashboards.
    Never returns values."""
    slug = slugify(channel)
    spec = PLATFORMS[platform]
    sect = _section(slug, platform)
    return {
        spec["token_key"]: bool(_vault.get_section_credential(sect, spec["token_key"], path=path)),
        spec["id_key"]: bool(_vault.get_section_credential(sect, spec["id_key"], path=path)),
        spec["expected_key"]: bool(_vault.get_section_credential(sect, spec["expected_key"], path=path)),
    }


def list_accounts(*, path=None) -> dict[str, dict[str, dict[str, bool]]]:
    """Full masked inventory: {channel_name: {platform: {field: configured?}}}."""
    out: dict[str, dict[str, dict[str, bool]]] = {}
    for slug in list_channel_slugs(path=path):
        name = channel_name(slug, path=path)
        out[name] = {p: account_status(slug, p, path=path) for p in PLATFORMS}
    return out


# ---------------------------------------------------------------------------
# The cross-post guard
# ---------------------------------------------------------------------------
def _graph_identity(account_id: str, token: str, field: str) -> tuple[str | None, str]:
    """Ask the Graph API for an account node's identity field (username / name).
    Returns (value, error). requests(verify=False): same Avast SSL-interception
    workaround already standard for web_search/Deepgram/instagram_insights on
    this machine."""
    try:
        import requests  # local import keeps module import cheap/offline-safe
    except Exception as exc:  # pragma: no cover
        return None, f"requests unavailable: {exc}"
    try:
        resp = requests.get(
            f"{_GRAPH}/{account_id}",
            params={"fields": field, "access_token": token},
            timeout=_TIMEOUT,
            verify=False,
        )
    except Exception as exc:
        return None, f"Graph API request failed: {exc}"
    if resp.status_code != 200:
        return None, f"Graph API {resp.status_code}: {resp.text[:200]}"
    try:
        return (resp.json().get(field), "")
    except Exception as exc:
        return None, f"Bad Graph API response: {exc}"


def verify_account(channel: str, platform: str, *, path=None) -> tuple[bool, str]:
    """Live check that a channel's stored token actually controls its stored
    account id, and (if an expected identity was set) that the live identity
    matches. Returns (ok, human_detail). Read-only; makes one Graph API call."""
    acct = get_account(channel, platform, path=path)
    spec = PLATFORMS[platform]
    if acct is None:
        return False, f"{spec['label']} for '{channel}' is not fully configured (missing token or account id)."
    live, err = _graph_identity(acct.account_id, acct.token, spec["identity_field"])
    if live is None:
        return False, f"Could not verify {spec['label']} for '{acct.channel_name}': {err}"
    if acct.expected_identity and live.strip().lower() != acct.expected_identity.strip().lower():
        return False, (
            f"IDENTITY MISMATCH for channel '{acct.channel_name}' {spec['label']}: token controls "
            f"'{live}', but this channel is registered as '{acct.expected_identity}'. "
            f"Refusing -- this is exactly the wrong-account case."
        )
    who = live if not acct.expected_identity else f"{live} (matches registered '{acct.expected_identity}')"
    return True, f"{spec['label']} for '{acct.channel_name}' verified: {who}."


def resolve_for_post(channel: str, platform: str, *, verify: bool = True, path=None) -> Account:
    """THE gate every poster must call. Returns the channel's verified Account,
    or raises CrossPostGuardError. There is no default channel: the caller must
    name one, and the credentials returned are guaranteed (when verify=True) to
    belong to that channel's registered account.

    verify=False skips the live Graph check (offline/testing only) and still
    enforces per-channel isolation and completeness."""
    acct = get_account(channel, platform, path=path)
    spec = PLATFORMS[platform]
    if acct is None:
        raise CrossPostGuardError(
            f"No configured {spec['label']} account for channel '{channel}'. "
            f"Add it before posting (set-social-account.ps1)."
        )
    if verify:
        ok, detail = verify_account(channel, platform, path=path)
        if not ok:
            raise CrossPostGuardError(detail)
    return acct
