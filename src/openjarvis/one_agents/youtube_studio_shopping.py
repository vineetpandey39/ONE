"""Idempotent Studio product attachment, separated from YouTube upload."""
from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openjarvis.one_agents.youtube_shopping import plan_hash

SONIA_CHANNEL_ID = "UCyqSprXlCEpBXMQRdkstLqA"
SONIA_BROWSER_DIR = Path(r"C:\Users\pc\Documents\LAO\sonia-community")


def _save(path: Path, body: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"schema": "sonia-shopping-attachment/1", "recorded_at": datetime.now(timezone.utc).isoformat(), **body}
    path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return body


def _tokens(value: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", value.lower()) if len(w) > 2 and w not in {"india", "travel"}}


def result_matches(query: str, product_title: str) -> bool:
    wanted, found = _tokens(query), _tokens(product_title)
    return len(wanted & found) >= min(2, max(1, len(wanted)))


def _browser_helper() -> Any:
    path = SONIA_BROWSER_DIR / "sonia_chrome.py"
    spec = importlib.util.spec_from_file_location("sonia_chrome_for_shopping", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Sonia browser helper unavailable: {path}")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def apply_plan(video_id: str, plan: dict[str, Any], *, receipt_path: Path) -> dict[str, Any]:
    digest = plan_hash(plan)
    try: old = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError): old = {}
    terminal = {"attached_verified", "skipped_no_relevant_product", "skipped_no_catalog_match"}
    if old.get("video_id") == video_id and old.get("plan_sha256") == digest and old.get("status") in terminal:
        return {**old, "resumed": True}
    candidates = list(plan.get("candidates") or [])
    if not candidates:
        return _save(receipt_path, {"status": "skipped_no_relevant_product", "video_id": video_id,
                                    "plan_sha256": digest, "selected": []})
    selected = []
    try:
        launcher = _browser_helper()
        state = launcher.ensure()
        if str(state).startswith("failed"):
            raise RuntimeError(f"Sonia persistent Chrome is unavailable: {state}")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{launcher.PORT}", timeout=20_000)
            if not browser.contexts:
                raise RuntimeError("Sonia persistent Chrome has no browser context")
            page = browser.contexts[0].new_page()
            page.set_default_timeout(30_000)
            page.goto(f"https://studio.youtube.com/video/{video_id}/edit", wait_until="domcontentloaded")
            page.locator(f'a[href*="/channel/{SONIA_CHANNEL_ID}"]').first.wait_for(timeout=30000)
            page.get_by_role("button", name="Products", exact=True).click(timeout=15000)
            page.get_by_role("button", name="Edit products", exact=True).click(timeout=15000)
            dialog = page.get_by_role("dialog")
            for candidate in candidates:
                query = str(candidate.get("search_query") or "")
                search = dialog.get_by_role("searchbox")
                if not search.count(): search = dialog.locator('input[type="search"],input[placeholder*="Search" i]').first
                search.fill(query); page.wait_for_timeout(1800)
                rows = dialog.locator("ycp-product-list-item,tp-yt-paper-item,[role=listitem]")
                for index in range(min(rows.count(), 8)):
                    row = rows.nth(index); catalog_text = re.sub(r"\s+", " ", row.inner_text()).strip()
                    if result_matches(query, catalog_text):
                        row.get_by_role("button", name="Tag", exact=True).click()
                        selected.append({"category": candidate.get("category"), "query": query,
                                         "catalog_text": catalog_text[:240]}); break
            if not selected:
                dialog.get_by_role("button", name="Cancel", exact=True).click()
                return _save(receipt_path, {"status": "skipped_no_catalog_match", "video_id": video_id,
                                            "plan_sha256": digest, "selected": []})
            dialog.get_by_role("button", name="Done", exact=True).click()
            page.get_by_role("button", name="Save", exact=True).click(timeout=15000)
            page.wait_for_timeout(2500); page.reload(wait_until="domcontentloaded")
            page.get_by_role("button", name="Products", exact=True).click(timeout=15000)
            if "No tagged products" in page.locator("body").inner_text():
                raise RuntimeError("Studio reload did not verify selected products")
            page.close()
        return _save(receipt_path, {"status": "attached_verified", "video_id": video_id,
                                    "plan_sha256": digest, "selected": selected})
    except Exception as exc:
        return _save(receipt_path, {"status": "pending_studio_retry", "video_id": video_id,
                                    "plan_sha256": digest, "selected": selected,
                                    "error": f"{type(exc).__name__}: {str(exc)[:300]}"})


def apply_package(video_id: str, package_path: Path) -> dict[str, Any]:
    package = json.loads(package_path.read_text(encoding="utf-8"))
    return apply_plan(video_id, dict(package.get("shopping") or {}),
                      receipt_path=package_path.with_name("shopping-attachment-receipt.json"))
