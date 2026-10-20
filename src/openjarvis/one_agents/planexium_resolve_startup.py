"""Bounded Windows Resolve startup; never kill an app or switch a user's project."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


class StartupBlocked(RuntimeError):
    pass


def processes():
    """Process metadata only; no desktop input or credential inspection."""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
         "Get-Process Resolve -ErrorAction SilentlyContinue | "
         "Select-Object Id,SessionId | ConvertTo-Json -Compress"],
        capture_output=True, text=True, timeout=15,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode not in (0, 1):
        raise StartupBlocked("resolve_process_inventory_failed")
    if result.stderr.strip():
        raise StartupBlocked("resolve_process_inventory_failed")
    data = json.loads(result.stdout) if result.stdout.strip() else []
    return data if isinstance(data, list) else [data]


def launch(settings):
    startup = settings["autostart"]
    executable = Path(startup["executable"])
    if not executable.is_file():
        raise StartupBlocked("resolve_executable_missing")
    import ctypes
    session = ctypes.c_ulong()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
        raise StartupBlocked("windows_session_unavailable")
    if session.value == 0:
        raise StartupBlocked("interactive_windows_logon_required")
    # ONE's worker uses a synthetic HOME. Resolve must use its real owner profile.
    owner = Path(startup["owner_profile"])
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "COMSPEC",
        "PATHEXT", "PROGRAMDATA", "ALLUSERSPROFILE", "USERNAME", "USERDOMAIN",
        "USERDOMAIN_ROAMINGPROFILE", "PROGRAMFILES", "PROGRAMFILES(X86)",
        "PROGRAMW6432", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)",
        "COMMONPROGRAMW6432", "OS", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
        "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL", "PROCESSOR_REVISION",
        "COMPUTERNAME", "SESSIONNAME", "PUBLIC"}}
    env.update(USERPROFILE=str(owner), APPDATA=str(owner/"AppData/Roaming"),
               LOCALAPPDATA=str(owner/"AppData/Local"),
               HOMEDRIVE=owner.drive, HOMEPATH=str(owner)[len(owner.drive):])
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    info.wShowWindow = 0
    return subprocess.Popen([str(executable)], env=env, startupinfo=info,
                     cwd=str(executable.parent),
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)


def connect(settings):
    # Use the existing authenticated bridge client; never log its configuration.
    server_root = str(Path(settings["server"]).parent.parent)
    if server_root not in sys.path:
        sys.path.insert(0, server_root)
    os.environ["DAVINCI_RESOLVE_BRIDGE_CONFIG"] = settings["bridge_config"]
    from src.utils.resolve_bridge_client import connect as bridge_connect, BridgeUnavailable
    try:
        return bridge_connect(require_enabled=False, timeout=3)
    except BridgeUnavailable:
        return None


def prepare_project(resolve, *, launched):
    manager = resolve.GetProjectManager()
    current = manager.GetCurrentProject()
    if current and current.IsRenderingInProgress():
        # Render ownership/resumption is checked by the existing finishing worker.
        return
    if current and current.GetName().startswith("PLANEXIUM_"):
        return
    # A newly launched Resolve starts at Project Manager with an empty default
    # project. Never infer that an existing user's Untitled Project is disposable.
    if not launched:
        raise StartupBlocked("unowned_resolve_project_open")
    if current:
        folder = current.GetMediaPool().GetRootFolder()
        empty = (current.GetName() == "Untitled Project"
                 and not resolve.GetCurrentPage()
                 and current.GetTimelineCount() == 0
                 and not folder.GetClipList() and not folder.GetSubFolderList())
        if not empty:
            raise StartupBlocked("unowned_resolve_project_open")
    project = (manager.LoadProject("PLANEXIUM_BOOTSTRAP")
               or manager.CreateProject("PLANEXIUM_BOOTSTRAP"))
    if not project or not manager.SaveProject():
        raise StartupBlocked("bootstrap_project_not_ready")


def ensure_ready(settings, *, connector=connect, inventory=processes,
                 launcher=launch, now=time.monotonic, sleep=time.sleep):
    """Caller holds the existing machine-wide Resolve finishing lock."""
    startup = settings.get("autostart", {})
    if not startup.get("enabled"):
        return
    root = Path(settings["work_root"])
    root.mkdir(parents=True, exist_ok=True)
    receipt = root/"startup-health.json"
    started, launched, child = now(), False, None

    def status(state, reason=None):
        value = {"status": state, "at_epoch": time.time(),
                 "elapsed_seconds": round(now()-started, 2),
                 "launched_resolve": launched, "reason": reason,
                 "public_publish_authorized": False}
        temp = receipt.with_suffix(".tmp")
        temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
        temp.replace(receipt)

    try:
        hook = Path(startup["hook"])
        if (not hook.is_file()
                or hashlib.sha256(hook.read_bytes()).hexdigest() != startup["hook_sha256"]):
            raise StartupBlocked("startup_hook_missing_or_changed")
        status("checking")
        deadline = started + min(180, max(10, int(startup.get("timeout", 120))))
        resolve = connector(settings)
        if resolve is None and not inventory():
            child = launcher(settings)
            launched = True
            status("starting")
        while resolve is None and now() < deadline:
            if child is not None and child.poll() is not None:
                raise StartupBlocked(f"resolve_exited_during_startup_{child.returncode}")
            sleep(3)
            resolve = connector(settings)
        if resolve is None:
            raise StartupBlocked("bridge_startup_timeout_no_forced_restart")
        prepare_project(resolve, launched=launched)
        status("ready")
    except Exception as exc:
        # Bridge exceptions may contain opaque provider data. Store stable codes only.
        reason = str(exc) if isinstance(exc, StartupBlocked) else type(exc).__name__
        status("blocked", reason)
        raise StartupBlocked(f"Resolve startup blocked: {reason}") from None
