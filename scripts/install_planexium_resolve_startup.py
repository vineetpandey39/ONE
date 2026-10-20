"""Install only the PLANEXIUM-owned, non-blocking in-app startup hook."""
import argparse
import hashlib
import json
from pathlib import Path


def install(config_path, owner):
    config_path, owner = Path(config_path), Path(owner)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    settings = config["resolve"]
    root = Path(settings["work_root"])
    root.mkdir(parents=True, exist_ok=True)
    bridge = Path("C:/ProgramData/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/resolve_bridge.py")
    executable = Path("C:/Program Files/Blackmagic Design/DaVinci Resolve/Resolve.exe")
    for path in (bridge, executable, Path(settings["server"]), Path(settings["python"])):
        if not path.is_file():
            raise RuntimeError(f"Required installed component missing: {path.name}")
    hook = owner/"AppData/Roaming/Blackmagic Design/DaVinci Resolve/Support/Fusion/Scripts/PLANEXIUM_Autostart.scriptlib"
    log = (root/"startup-hook.log").as_posix()
    bridge_path = bridge.as_posix()
    if "]]" in log or "]]" in bridge_path:
        raise ValueError("Unsupported Lua path")
    text = f'''-- PLANEXIUM owned startup hook. No resident Execute loop or UI automation.
-- RunScript dispatches the installed in-app bridge and returns immediately.
local function note(message)
 local f=io.open([[{log}]], "a")
 if f then f:write(os.date("!%Y-%m-%dT%H:%M:%SZ") .. " " .. message .. "\\n"); f:close() end
end
if not _G.PLANEXIUM_BRIDGE_DISPATCHED then
 local app=fusion or fu
 if app and app.RunScript then
  _G.PLANEXIUM_BRIDGE_DISPATCHED=true
  local ok=pcall(function() app:RunScript([[{bridge_path}]]) end)
  note(ok and "bridge_dispatched" or "bridge_dispatch_failed")
 else note("fusion_not_ready") end
end
'''
    hook.parent.mkdir(parents=True, exist_ok=True)
    if hook.exists():
        previous = hook.read_text(encoding="utf-8")
        if not previous.startswith("-- PLANEXIUM owned startup"):
            raise RuntimeError("Refusing to overwrite an unowned startup hook")
        (root/"startup-hook.previous.scriptlib").write_text(previous, encoding="utf-8")
    (root/"startup-config.previous.json").write_bytes(config_path.read_bytes())
    hook.write_text(text, encoding="utf-8")
    settings["autostart"] = {
        "enabled": True, "executable": str(executable), "owner_profile": str(owner),
        "hook": str(hook), "hook_sha256": hashlib.sha256(hook.read_bytes()).hexdigest(),
        "timeout": 120,
    }
    config_path.write_text(json.dumps(config, indent=2)+"\n", encoding="utf-8")
    print("Installed PLANEXIUM hook; publishing setting unchanged.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--owner", required=True)
    args = parser.parse_args()
    install(args.config, args.owner)
