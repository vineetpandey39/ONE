"""Small, dependency-free Obsidian memory adapter for ONE."""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any


_VAULT_FILE_TYPES = {".md", ".base", ".canvas"}
_SENSITIVE_PATTERN = re.compile(
    r"\b(password|passcode|api[_ -]?key|access[_ -]?token|client[_ -]?secret|private[_ -]?key)\b",
    re.IGNORECASE,
)


def _home() -> Path:
    return Path(os.environ.get("OPENJARVIS_HOME", Path.home() / ".openjarvis"))


def _settings_path() -> Path:
    return _home() / "one_settings.json"


def get_settings() -> dict[str, Any]:
    path = _settings_path()
    if not path.exists():
        return {"obsidian_path": ""}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"obsidian_path": ""}


def set_obsidian_path(value: str) -> dict[str, Any]:
    path = Path(value.strip()).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("That folder does not exist")
    markdown_count = sum(1 for _ in path.rglob("*.md"))
    settings = get_settings()
    settings["obsidian_path"] = str(path)
    target = _settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return {"path": str(path), "notes": markdown_count, "connected": True}


def obsidian_status() -> dict[str, Any]:
    raw = str(get_settings().get("obsidian_path", ""))
    path = Path(raw) if raw else None
    connected = bool(path and path.is_dir())
    notes = sum(1 for _ in path.rglob("*.md")) if connected and path else 0
    return {"connected": connected, "path": raw, "notes": notes}


def recent_memories(limit: int = 12) -> list[dict[str, Any]]:
    status = obsidian_status()
    if not status["connected"]:
        return []
    root = Path(status["path"])
    notes = []
    for path in root.rglob("*.md"):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            stat = path.stat()
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        notes.append({
            "title": path.stem,
            "path": str(path.relative_to(root)),
            "updated": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "preview": " ".join(content[:240].split()),
        })
    notes.sort(key=lambda item: item["updated"], reverse=True)
    return notes[: max(1, min(limit, 30))]


def memory_graph(limit: int = 80) -> dict[str, Any]:
    """Build a privacy-safe graph from vault folders, notes, and journal turns."""
    status = obsidian_status()
    if not status["connected"]:
        return {"nodes": [], "edges": [], "connected": False}
    root = Path(status["path"]).resolve()
    max_nodes = max(20, min(int(limit), 140))
    files: list[tuple[float, Path, str]] = []
    for path in root.rglob("*.md"):
        relative = path.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        try:
            files.append((path.stat().st_mtime, path, path.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    files.sort(key=lambda item: item[0], reverse=True)
    files = files[: min(38, max_nodes)]

    def node_id(prefix: str, value: str) -> str:
        digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
        return f"{prefix}-{digest}"

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str, str]] = set()
    note_by_title: dict[str, str] = {}
    note_records: list[tuple[str, Path, str]] = []

    def add_node(node: dict[str, Any]) -> None:
        if node["id"] not in seen_nodes and len(nodes) < max_nodes:
            seen_nodes.add(node["id"])
            nodes.append(node)

    def add_edge(source: str, target: str, kind: str) -> None:
        key = (source, target, kind)
        if source in seen_nodes and target in seen_nodes and key not in seen_edges:
            seen_edges.add(key)
            edges.append({"source": source, "target": target, "kind": kind})

    for modified, path, content in files:
        relative = path.relative_to(root)
        folder = relative.parent.as_posix() if relative.parent != Path(".") else "Vault"
        folder_id = node_id("folder", folder)
        add_node({
            "id": folder_id,
            "title": folder.split("/")[-1],
            "path": folder,
            "kind": "folder",
            "updated": datetime.fromtimestamp(modified).isoformat(timespec="seconds"),
            "preview": f"{folder} memory cluster",
            "weight": 4,
        })
        note_id = node_id("note", relative.as_posix())
        preview = " ".join(re.sub(r"[#*_`>]", " ", content[:520]).split())[:220]
        add_node({
            "id": note_id,
            "title": path.stem.replace(" - ONE Journal", ""),
            "path": relative.as_posix(),
            "kind": "note",
            "updated": datetime.fromtimestamp(modified).isoformat(timespec="seconds"),
            "preview": preview,
            "weight": 3,
        })
        note_by_title[path.stem.lower()] = note_id
        note_records.append((note_id, path, content))
        add_edge(folder_id, note_id, "contains")

        if "ONE Journal" in path.name and len(nodes) < max_nodes:
            turns = list(re.finditer(r"(?ms)^##\s+([^\n]+)\n(.*?)(?=^##\s+|\Z)", content))[-8:]
            for turn_index, turn in enumerate(turns):
                body = turn.group(2)
                user_match = re.search(r"(?ms)\*\*Vineet:\*\*\s*(.*?)(?=\n\*\*ONE:\*\*|\Z)", body)
                one_match = re.search(r"(?ms)\*\*ONE:\*\*\s*(.*)$", body)
                user_text = " ".join((user_match.group(1) if user_match else "Conversation").split())
                one_text = " ".join((one_match.group(1) if one_match else "").split())
                conversation_id = node_id("turn", f"{relative}:{turn.group(1)}:{turn_index}")
                add_node({
                    "id": conversation_id,
                    "title": user_text[:54] or "Conversation",
                    "path": relative.as_posix(),
                    "kind": "conversation",
                    "updated": datetime.fromtimestamp(modified).isoformat(timespec="seconds"),
                    "preview": one_text[:220],
                    "weight": 1,
                })
                add_edge(note_id, conversation_id, "conversation")

    for note_id, _path, content in note_records:
        for target_title in re.findall(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]", content):
            target_id = note_by_title.get(Path(target_title.strip()).stem.lower())
            if target_id and target_id != note_id:
                add_edge(note_id, target_id, "wikilink")

    return {
        "nodes": nodes,
        "edges": edges,
        "connected": True,
        "vault_notes": status["notes"],
    }


def remember_exchange(command: str, response: str) -> dict[str, Any]:
    status = obsidian_status()
    if not status["connected"]:
        raise ValueError("Obsidian is not connected")
    combined = f"{command}\n{response}"
    if re.search(r"\b(password|passcode|api[_ -]?key|access[_ -]?token|client[_ -]?secret|private[_ -]?key)\b", combined, re.I):
        return {"saved": False, "reason": "sensitive content was not persisted"}
    now = datetime.now().astimezone()
    root = Path(status["path"])
    folder = root / "Memory" / now.strftime("%Y") / now.strftime("%m")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{now.strftime('%Y-%m-%d')} - ONE Journal.md"
    if not path.exists():
        path.write_text(f"# ONE Memory Journal - {now.strftime('%d %B %Y')}\n", encoding="utf-8")
    entry = (
        f"\n## {now.strftime('%H:%M:%S')}\n"
        f"\n**Vineet:** {command.strip()}\n"
        f"\n**ONE:** {response.strip()}\n"
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(entry)
    return {"saved": True, "path": str(path.relative_to(root)), "updated": now.isoformat(timespec="seconds")}


def search_obsidian(query: str, limit: int = 8) -> list[dict[str, Any]]:
    status = obsidian_status()
    if not status["connected"]:
        raise ValueError("Obsidian is not connected")
    terms = [term.lower() for term in re.findall(r"[A-Za-z0-9_-]+", query) if len(term) > 1]
    if not terms:
        raise ValueError("A search query is required")
    root = Path(status["path"])
    matches: list[dict[str, Any]] = []
    for path in root.rglob("*.md"):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        haystack = f"{path.stem}\n{content}".lower()
        score = sum(haystack.count(term) for term in terms)
        if not score:
            continue
        first = min((haystack.find(term) for term in terms if term in haystack), default=0)
        start = max(0, first - 100)
        snippet = " ".join(content[start : start + 520].split())
        matches.append({"title": path.stem, "path": str(path.relative_to(root)), "score": score, "snippet": snippet})
    matches.sort(key=lambda item: (-item["score"], item["path"]))
    return matches[: max(1, min(limit, 20))]


def _resolve_vault_file(relative_path: str) -> tuple[Path, Path]:
    status = obsidian_status()
    if not status["connected"]:
        raise ValueError("Obsidian is not connected")
    value = str(relative_path or "").strip().replace("\\", "/")
    relative = Path(value)
    if not value or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Use a safe path relative to the Obsidian vault")
    if any(part.startswith(".") for part in relative.parts):
        raise ValueError("Hidden Obsidian internals cannot be accessed")
    if relative.suffix.lower() not in _VAULT_FILE_TYPES:
        raise ValueError("ONE may only access .md, .base, and .canvas vault files")
    root = Path(status["path"]).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Path escapes the Obsidian vault")
    return root, target


def read_obsidian_file(relative_path: str, max_chars: int = 20_000) -> dict[str, Any]:
    root, target = _resolve_vault_file(relative_path)
    if not target.is_file():
        raise ValueError("That Obsidian file does not exist")
    content = target.read_text(encoding="utf-8", errors="replace")
    limit = max(500, min(int(max_chars), 50_000))
    return {
        "path": str(target.relative_to(root)),
        "content": content[:limit],
        "truncated": len(content) > limit,
    }


def write_obsidian_file(
    relative_path: str,
    content: str,
    *,
    mode: str = "create",
) -> dict[str, Any]:
    root, target = _resolve_vault_file(relative_path)
    clean_content = str(content or "")
    if not clean_content.strip():
        raise ValueError("Note content is required")
    if len(clean_content.encode("utf-8")) > 1_000_000:
        raise ValueError("Obsidian note content exceeds ONE's 1 MB safety limit")
    if _SENSITIVE_PATTERN.search(clean_content):
        raise ValueError("Sensitive credentials cannot be written to Obsidian")
    if mode not in {"create", "append"}:
        raise ValueError("Mode must be create or append")
    if mode == "create" and target.exists():
        raise ValueError("That note already exists; use append to preserve its content")
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "append":
        if not target.exists():
            raise ValueError("Cannot append because that note does not exist")
        with target.open("a", encoding="utf-8") as handle:
            handle.write(clean_content)
    else:
        target.write_text(clean_content, encoding="utf-8")
    return {
        "saved": True,
        "path": str(target.relative_to(root)),
        "mode": mode,
        "size_bytes": target.stat().st_size,
    }
