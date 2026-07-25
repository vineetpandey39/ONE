"""Local screen control for the Ghost Agent -- see and click any GUI, on-machine.

Built 2026-07-25 after a real gap: asked to empty the Recycle Bin (and, more
generally, to "click through any GUI"), the Ghost Agent could only OPEN apps
(open_app) and then had to hand off to Vineet for every click. This closes
that loop so ONE's STT layer can drive the desktop directly.

DESIGN honoring Vineet's hard rule -- nothing about the screen leaves the
machine:
  * The screen is understood via Windows UI Automation (the OS accessibility
    layer), which yields a TEXT list of on-screen controls -- their names,
    types, and exact center coordinates -- computed 100% locally, no vision
    model, no GPU, no pixels. That text is what the (cloud) brain reasons
    over to choose a target, exactly the same trust boundary already accepted
    for system_query's folder names and web_search results. NO IMAGE is ever
    sent anywhere.
  * screenshots ARE capturable, but only ever written to a local folder under
    data/ and returned as a PATH string -- never uploaded, never attached to
    any outbound request. They're for Vineet's own eyes / local audit.
  * clicking/typing/scrolling is pure local OS actuation via pyautogui.

So the cloud brain sees only structured UI text; images and keystrokes never
cross the machine boundary.
"""

from __future__ import annotations

import time
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# Control types worth surfacing to the brain -- the things a person clicks or
# types into. Static text/panes are skipped unless they carry a name that
# helps orient (handled below).
_INTERACTIVE_TYPES = {
    "ButtonControl", "MenuItemControl", "EditControl", "CheckBoxControl",
    "RadioButtonControl", "ComboBoxControl", "ListItemControl", "TabItemControl",
    "HyperlinkControl", "TreeItemControl", "SplitButtonControl", "MenuControl",
    "DocumentControl", "SliderControl", "ThumbControl",
}

_MAX_ELEMENTS = 60      # cap the list so a huge window stays LLM-sized
_MAX_DEPTH = 14         # how deep to walk the control tree
_CAPTURE_DIRNAME = "screen_captures"
# Vineet's explicit requirement (2026-07-25): every click/keystroke must
# happen in plain sight on the real screen -- never a hidden background
# operation. So before acting we bring the target window to the front and
# un-minimize it, and the cursor travels slowly enough to follow with the
# eye rather than teleporting.
_CURSOR_MOVE_SECONDS = 0.55


def _flash_click_point(x: int, y: int, radius: int = 46, duration: float = 0.45) -> None:
    """Briefly flash a cyan ring at (x, y) so Vineet sees exactly where the
    click is about to land, before it happens. Pure stdlib Tkinter overlay,
    on-screen only. Cosmetic and best-effort -- any failure is swallowed so
    it can NEVER block or delay the real click."""
    try:
        import tkinter as tk

        margin = 5
        size = radius * 2 + margin * 2
        trans = "magenta"  # color key rendered fully transparent
        root = tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        try:
            root.attributes("-transparentcolor", trans)
        except tk.TclError:
            pass
        root.configure(bg=trans)
        root.geometry(f"{size}x{size}+{int(x - size / 2)}+{int(y - size / 2)}")
        cv = tk.Canvas(root, width=size, height=size, bg=trans, highlightthickness=0)
        cv.pack()
        cv.create_oval(margin, margin, size - margin, size - margin,
                       outline="#00e5ff", width=5)
        cv.create_oval(size / 2 - 8, size / 2 - 8, size / 2 + 8, size / 2 + 8,
                       outline="#00e5ff", width=2)
        root.update()
        time.sleep(duration)
        root.destroy()
    except Exception:
        pass


def _top_window(auto, ctrl):
    """Climb from a control to its top-level Window/Pane."""
    top = ctrl
    try:
        while top.GetParentControl() is not None and top.ControlTypeName not in (
            "WindowControl", "PaneControl"
        ):
            top = top.GetParentControl()
    except Exception:
        return ctrl
    return top


def _bring_to_front(auto, ctrl) -> str:
    """Un-minimize + foreground the window we're about to act on, so the
    action is visible to Vineet. Returns the window title (best effort)."""
    top = _top_window(auto, ctrl)
    title = ""
    try:
        title = top.Name or ""
    except Exception:
        pass
    # Restore if minimized.
    try:
        wp = top.GetWindowPattern()
        if wp and wp.WindowVisualState == auto.WindowVisualState.Minimized:
            wp.SetWindowVisualState(auto.WindowVisualState.Normal)
            time.sleep(0.3)
    except Exception:
        pass
    # Bring to foreground (SetForegroundWindow under the hood).
    try:
        top.SetActive()
        time.sleep(0.2)
    except Exception:
        pass
    return title


def _capture_dir():
    from openjarvis.core.paths import get_config_dir

    d = get_config_dir() / _CAPTURE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _rect_center(ctrl) -> tuple[int, int] | None:
    try:
        r = ctrl.BoundingRectangle
    except Exception:
        return None
    if r is None:
        return None
    # Skip zero/offscreen rects (collapsed or not rendered).
    if r.width() <= 0 or r.height() <= 0:
        return None
    return int(r.xcenter()), int(r.ycenter())


def _enumerate_foreground(auto) -> tuple[str, list[dict[str, Any]]]:
    """Walk the foreground window's control tree -> (window title, elements)."""
    win = auto.GetForegroundControl()
    if win is None:
        return "", []
    # Climb to the top-level window for a stable title.
    top = win
    try:
        while top.GetParentControl() is not None and top.ControlTypeName not in (
            "WindowControl", "PaneControl"
        ):
            top = top.GetParentControl()
    except Exception:
        top = win
    title = ""
    try:
        title = top.Name or win.Name or ""
    except Exception:
        pass

    elements: list[dict[str, Any]] = []
    seen: set[tuple] = set()

    def walk(ctrl, depth: int) -> None:
        if depth > _MAX_DEPTH or len(elements) >= _MAX_ELEMENTS:
            return
        try:
            children = ctrl.GetChildren()
        except Exception:
            children = []
        for child in children:
            if len(elements) >= _MAX_ELEMENTS:
                return
            try:
                ctype = child.ControlTypeName
                name = (child.Name or "").strip()
                enabled = child.IsEnabled
            except Exception:
                continue
            center = _rect_center(child)
            interactive = ctype in _INTERACTIVE_TYPES
            if center and enabled and interactive and (name or ctype == "EditControl"):
                key = (name, ctype, center)
                if key not in seen:
                    seen.add(key)
                    elements.append(
                        {"name": name or "(unnamed field)", "type": ctype,
                         "x": center[0], "y": center[1]}
                    )
            walk(child, depth + 1)

    walk(top, 0)
    return title, elements


@ToolRegistry.register("screen_control")
class ScreenControlTool(BaseTool):
    """See on-screen UI as text and click/type it -- fully local."""

    tool_id = "screen_control"
    is_local = True

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="screen_control",
            description=(
                "See and operate whatever is on Vineet's screen right now, "
                "locally -- to actually DO GUI tasks (empty the recycle bin, "
                "click through an app, fill a form and submit) instead of "
                "handing off to him. Actions: 'describe_screen' lists the "
                "clickable controls of the foreground window as text with "
                "their exact x,y (call this FIRST to see what's there); "
                "'click'/'double_click'/'right_click' at an x,y from that "
                "list; 'type_text' types into the focused field; 'press_key' "
                "sends a key or combo (e.g. 'enter', 'ctrl+a', 'win'); "
                "'scroll' up/down; 'screenshot' saves a local image for "
                "Vineet (path only, never uploaded). WORKFLOW: describe_screen "
                "-> pick the target from the list -> click/type -> "
                "describe_screen again to confirm it worked. For anything "
                "that permanently deletes or sends, say what you're about to "
                "click and get Vineet's ok first, like a shell command."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "describe_screen", "click", "double_click",
                            "right_click", "type_text", "press_key",
                            "scroll", "screenshot",
                        ],
                    },
                    "x": {"type": "integer", "description": "click X (screen pixel)"},
                    "y": {"type": "integer", "description": "click Y (screen pixel)"},
                    "text": {"type": "string", "description": "text to type (type_text)"},
                    "keys": {
                        "type": "string",
                        "description": "key or combo for press_key, e.g. 'enter', 'ctrl+a', 'alt+f4'",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down"],
                        "description": "scroll direction",
                    },
                    "amount": {"type": "integer", "description": "scroll clicks (default 3)"},
                },
                "required": ["action"],
            },
            category="local_execution",
            cost_estimate=0.0,
            timeout_seconds=30,
        )

    def execute(self, **params: Any) -> ToolResult:
        import sys

        if sys.platform != "win32":
            return ToolResult(
                tool_name=self.tool_id,
                content="screen_control is only implemented for Windows right now.",
                success=False,
            )
        try:
            import pyautogui
            import uiautomation as auto
        except ImportError:
            return ToolResult(
                tool_name=self.tool_id,
                content="screen automation libs not installed (uiautomation, pyautogui).",
                success=False,
            )

        pyautogui.FAILSAFE = False  # top-left-corner abort would fire on legit clicks
        action = str(params.get("action", "")).strip()

        try:
            if action == "describe_screen":
                title, elements = _enumerate_foreground(auto)
                if not elements:
                    return ToolResult(
                        tool_name=self.tool_id,
                        content=(
                            f"Foreground window: {title or '(unknown)'}. No "
                            "readable clickable controls found -- it may be a "
                            "canvas/web view without an accessibility layer. "
                            "A screenshot won't help me either (I read text, "
                            "not pixels), so this window needs manual clicks."
                        ),
                        success=True,
                        metadata={"window": title, "count": 0},
                    )
                lines = [f"Foreground window: {title or '(unknown)'}",
                         "Clickable controls (click by x,y):"]
                for e in elements:
                    lines.append(f"  [{e['type'].replace('Control','')}] "
                                 f"\"{e['name']}\" -> x={e['x']}, y={e['y']}")
                return ToolResult(
                    tool_name=self.tool_id,
                    content="\n".join(lines),
                    success=True,
                    metadata={"window": title, "count": len(elements)},
                )

            if action in ("click", "double_click", "right_click"):
                x, y = params.get("x"), params.get("y")
                if x is None or y is None:
                    return ToolResult(
                        tool_name=self.tool_id,
                        content=f"{action} needs x and y (get them from describe_screen).",
                        success=False,
                    )
                x, y = int(x), int(y)
                # Make it visible: foreground the window, then move the
                # cursor slowly enough for Vineet to watch it land.
                win = _bring_to_front(auto, auto.GetForegroundControl())
                pyautogui.moveTo(x, y, duration=_CURSOR_MOVE_SECONDS)
                _flash_click_point(x, y)  # show the exact spot before clicking
                if action == "click":
                    pyautogui.click()
                elif action == "double_click":
                    pyautogui.doubleClick()
                else:
                    pyautogui.rightClick()
                time.sleep(0.4)  # let the UI react before the next describe
                return ToolResult(
                    tool_name=self.tool_id,
                    content=f"{action} at ({x}, {y}) in '{win}' (done in front of you). "
                            "Call describe_screen to see the result.",
                    success=True,
                    metadata={"x": x, "y": y, "window": win},
                )

            if action == "type_text":
                text = str(params.get("text", ""))
                if not text:
                    return ToolResult(tool_name=self.tool_id, content="No text to type.", success=False)
                _bring_to_front(auto, auto.GetForegroundControl())
                # Slightly slower than instant so the typing is visibly
                # happening on screen, not injected silently.
                pyautogui.typewrite(text, interval=0.03)
                return ToolResult(
                    tool_name=self.tool_id,
                    content=f"Typed {len(text)} characters into the focused field (visible on screen).",
                    success=True,
                )

            if action == "press_key":
                keys = str(params.get("keys", "")).strip().lower()
                if not keys:
                    return ToolResult(tool_name=self.tool_id, content="No keys given.", success=False)
                if "+" in keys:
                    pyautogui.hotkey(*[k.strip() for k in keys.split("+")])
                else:
                    pyautogui.press(keys)
                time.sleep(0.3)
                return ToolResult(
                    tool_name=self.tool_id,
                    content=f"Pressed {keys}. Call describe_screen to see the result.",
                    success=True,
                )

            if action == "scroll":
                direction = str(params.get("direction", "down")).strip()
                amount = int(params.get("amount") or 3)
                clicks = amount * 120 * (1 if direction == "up" else -1)
                pyautogui.scroll(clicks)
                time.sleep(0.3)
                return ToolResult(
                    tool_name=self.tool_id,
                    content=f"Scrolled {direction} {amount}.",
                    success=True,
                )

            if action == "screenshot":
                path = _capture_dir() / f"screen_{int(time.time())}.png"
                pyautogui.screenshot(str(path))
                return ToolResult(
                    tool_name=self.tool_id,
                    content=(
                        f"Screenshot saved locally to {path} (stays on this "
                        "machine, not uploaded). I read the screen via "
                        "describe_screen, not from images."
                    ),
                    success=True,
                    metadata={"path": str(path)},
                )

            return ToolResult(
                tool_name=self.tool_id, content=f"Unknown action '{action}'.", success=False
            )
        except Exception as exc:
            return ToolResult(
                tool_name=self.tool_id,
                content=f"screen_control {action} failed: {type(exc).__name__}: {exc}",
                success=False,
            )


__all__ = ["ScreenControlTool"]
