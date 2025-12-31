"""
Black Bars Script (Event-Driven Version)

Creates a black background behind monitored game/application windows when focused,
and hides the Windows taskbar. Restores everything when the window loses focus or is minimized.

Uses Windows Event Hooks (SetWinEventHook) for efficient event-driven detection instead of polling.

Configuration:
    Set WINDOW_TITLES to a list of window titles to monitor, or pass them via --titles argument.
    Example: python main.py --titles "Window Title 1" "Window Title 2"

    Or create a black_bars_config.json file with the following format:
    {
        "window_titles": ["Window Title 1", "Window Title 2"]
    }
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import signal
import sys
import threading
from pathlib import Path
from typing import Any

import pystray
import win32api
import win32con
import win32gui
from PIL import Image, ImageDraw

# Constants
# List of window titles to monitor. Can be overridden via command-line arguments or config file
WINDOW_TITLES = ["League of Legends (TM) Client", "League of Legends"]
CONFIG_FILE = Path("black_bars_config.json")
TASKBAR_CLASS = "Shell_TrayWnd"
START_BUTTON_CLASS = "Button"

# Windows Event Constants
EVENT_SYSTEM_FOREGROUND = 0x0003  # Foreground window changed
EVENT_OBJECT_REORDER = 0x8004  # Z-order changed
EVENT_SYSTEM_MINIMIZESTART = 0x0016  # Window minimized
EVENT_SYSTEM_MINIMIZEEND = 0x0017  # Window restored from minimized
WINEVENT_OUTOFCONTEXT = 0x0000  # Events delivered async, no hook injection

# Global state
black_window_hwnd: int | None = None
black_bars_active: bool = False
hook_handles: list[int] = []
tray_icon: pystray.Icon | None = None
shutting_down: bool = False


# =============================================================================
# Configuration
# =============================================================================


def load_config() -> None:
    """Load configuration from file or command-line arguments."""
    global WINDOW_TITLES

    # Check for config file
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                config = json.load(f)
                if "window_titles" in config and isinstance(
                    config["window_titles"], list
                ):
                    WINDOW_TITLES = config["window_titles"]
                    print(f"Loaded {len(WINDOW_TITLES)} window titles from config file")
        except Exception as e:
            print(f"Warning: Failed to load config file: {e}")

    # Check for command-line arguments (override config file)
    if "--titles" in sys.argv:
        idx = sys.argv.index("--titles")
        titles = []
        for arg in sys.argv[idx + 1 :]:
            if arg.startswith("--"):
                break
            titles.append(arg)

        if titles:
            WINDOW_TITLES = titles
            print(
                f"Loaded {len(WINDOW_TITLES)} window titles from command-line arguments"
            )


# =============================================================================
# Window Detection
# =============================================================================


def get_foreground_window() -> int:
    """Get the handle of the currently focused window."""
    return win32gui.GetForegroundWindow()


def get_window_title(hwnd: int) -> str:
    """Get the title of a window by its handle."""
    try:
        return win32gui.GetWindowText(hwnd)
    except Exception:
        return ""


def is_window_minimized(hwnd: int) -> bool:
    """Check if a window is minimized."""
    try:
        return bool(win32gui.IsIconic(hwnd))
    except Exception:
        return False


def is_monitored_window(hwnd: int) -> bool:
    """Check if the given window handle is one of the monitored windows."""
    return get_window_title(hwnd) in WINDOW_TITLES


# =============================================================================
# Monitor Detection
# =============================================================================


def get_monitor_info(hwnd: int) -> Any:
    """Get information about the monitor containing the specified window."""
    try:
        monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        monitor_info = win32api.GetMonitorInfo(monitor)
        return monitor_info
    except Exception:
        return None


def get_monitor_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Get the full screen rectangle of the monitor containing the window.

    Returns (left, top, right, bottom) or None if unable to determine.
    """
    monitor_info = get_monitor_info(hwnd)
    if monitor_info:
        # Use 'Monitor' rect (full screen) instead of 'Work' rect (excludes taskbar)
        return monitor_info["Monitor"]
    return None


# =============================================================================
# Black Background Window
# =============================================================================


def create_window_class() -> str:
    """Register a window class for the black background window."""
    class_name = "BlackBarsWindow"

    wc = win32gui.WNDCLASS()
    wc.lpfnWndProc = {  # type: ignore[assignment]
        win32con.WM_DESTROY: lambda hwnd,
        msg,
        wparam,
        lparam: ctypes.windll.user32.PostQuitMessage(0),  # type: ignore[attr-defined]
    }
    wc.lpszClassName = class_name  # type: ignore[assignment]
    wc.hbrBackground = win32gui.GetStockObject(win32con.BLACK_BRUSH)  # type: ignore[assignment]
    wc.hCursor = win32gui.LoadCursor(0, win32con.IDC_ARROW)  # type: ignore[assignment]

    try:
        win32gui.RegisterClass(wc)
    except Exception:
        # Class may already be registered
        pass

    return class_name


def create_black_window(monitor_rect: tuple[int, int, int, int]) -> int:
    """Create a fullscreen black window on the specified monitor.

    Args:
        monitor_rect: (left, top, right, bottom) coordinates of the monitor

    Returns:
        Window handle of the created window
    """
    class_name = create_window_class()

    left, top, right, bottom = monitor_rect
    width = right - left
    height = bottom - top

    # Create a layered, tool window (no taskbar entry) that's also transparent to input
    ex_style = (
        win32con.WS_EX_LAYERED
        | win32con.WS_EX_TOOLWINDOW
        | win32con.WS_EX_TRANSPARENT  # Click-through
        | win32con.WS_EX_NOACTIVATE  # Don't take focus
    )

    style = win32con.WS_POPUP  # Borderless window

    hwnd = win32gui.CreateWindowEx(
        ex_style,
        class_name,
        "Black Background",
        style,
        left,
        top,
        width,
        height,
        0,
        0,
        0,
        None,
    )

    # Set the window to be fully opaque black
    # For layered windows, we need to set the layered attributes
    ctypes.windll.user32.SetLayeredWindowAttributes(  # type: ignore[attr-defined]
        hwnd,
        0,  # Color key (not used)
        255,  # Alpha (fully opaque)
        win32con.LWA_ALPHA,
    )

    return hwnd


def show_black_window(hwnd: int, monitored_hwnd: int) -> None:
    """Show the black window and position it just below the monitored window in z-order."""
    # Position the black window just below the monitored window in the z-order
    # This ensures it's behind the monitored window but in front of everything else
    win32gui.SetWindowPos(
        hwnd,
        monitored_hwnd,  # Insert after (below) monitored window
        0,
        0,
        0,
        0,
        win32con.SWP_NOMOVE
        | win32con.SWP_NOSIZE
        | win32con.SWP_NOACTIVATE
        | win32con.SWP_SHOWWINDOW,
    )


def hide_black_window(hwnd: int) -> None:
    """Hide the black background window."""
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
    except Exception:
        pass


def destroy_black_window(hwnd: int) -> None:
    """Destroy the black background window."""
    try:
        win32gui.DestroyWindow(hwnd)
    except Exception:
        pass


# =============================================================================
# Taskbar Management
# =============================================================================


def find_taskbar() -> int | None:
    """Find the Windows taskbar window handle."""
    return win32gui.FindWindow(TASKBAR_CLASS, None) or None


def find_start_button() -> int | None:
    """Find the Windows Start button window handle."""
    taskbar = find_taskbar()
    if taskbar:
        # The Start button is usually a child or nearby window
        start = win32gui.FindWindowEx(0, 0, START_BUTTON_CLASS, "Start")
        return start or None
    return None


def hide_taskbar() -> None:
    """Hide the Windows taskbar."""
    taskbar = find_taskbar()
    if taskbar:
        win32gui.ShowWindow(taskbar, win32con.SW_HIDE)

    # Also try to hide the Start button (Windows 10+)
    start = find_start_button()
    if start:
        win32gui.ShowWindow(start, win32con.SW_HIDE)


def show_taskbar() -> None:
    """Show the Windows taskbar."""
    taskbar = find_taskbar()
    if taskbar:
        win32gui.ShowWindow(taskbar, win32con.SW_SHOW)

    # Also restore the Start button
    start = find_start_button()
    if start:
        win32gui.ShowWindow(start, win32con.SW_SHOW)


# =============================================================================
# Black Bars State Management
# =============================================================================


def activate_black_bars(monitored_hwnd: int) -> None:
    """Activate black bars mode for the given monitored window."""
    global black_window_hwnd, black_bars_active

    # Get the monitor where the window is displayed
    monitor_rect = get_monitor_rect(monitored_hwnd)
    if not monitor_rect:
        window_title = get_window_title(monitored_hwnd)
        print(f"Warning: Could not determine monitor for window: '{window_title}'")
        return

    # Create and show the black background window
    if black_window_hwnd is None:
        black_window_hwnd = create_black_window(monitor_rect)

    show_black_window(black_window_hwnd, monitored_hwnd)
    hide_taskbar()
    black_bars_active = True
    window_title = get_window_title(monitored_hwnd)
    print(
        f"Black bars activated for window: '{window_title}' on monitor: {monitor_rect}"
    )


def deactivate_black_bars() -> None:
    """Deactivate black bars mode."""
    global black_window_hwnd, black_bars_active

    if black_window_hwnd:
        hide_black_window(black_window_hwnd)

    show_taskbar()
    black_bars_active = False
    print("Black bars deactivated")


def ensure_black_window_z_order(monitored_hwnd: int) -> None:
    """Ensure the black window is positioned directly below the monitored window in z-order."""
    global black_window_hwnd

    if black_window_hwnd is None:
        return

    try:
        # Get the window directly below the monitored window in z-order
        window_below = win32gui.GetWindow(monitored_hwnd, win32con.GW_HWNDNEXT)

        # If our black window is not directly below the monitored window, reposition it
        if window_below != black_window_hwnd:
            win32gui.SetWindowPos(
                black_window_hwnd,
                monitored_hwnd,  # Insert after (below) monitored window
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
            )
    except Exception:
        pass


def check_and_update_state() -> None:
    """Check the current foreground window and update black bars state accordingly."""
    foreground_hwnd = get_foreground_window()

    if is_monitored_window(foreground_hwnd) and not is_window_minimized(
        foreground_hwnd
    ):
        if not black_bars_active:
            activate_black_bars(foreground_hwnd)
        else:
            # Black bars already active - ensure z-order is correct
            ensure_black_window_z_order(foreground_hwnd)
    else:
        if black_bars_active:
            deactivate_black_bars()


# =============================================================================
# Windows Event Hook
# =============================================================================

# Define the callback type for SetWinEventHook
# WINEVENTPROC: void callback(HWINEVENTHOOK, DWORD, HWND, LONG, LONG, DWORD, DWORD)
WinEventProcType = ctypes.WINFUNCTYPE(  # type: ignore[attr-defined]
    None,
    ctypes.wintypes.HANDLE,  # hWinEventHook
    ctypes.wintypes.DWORD,  # event
    ctypes.wintypes.HWND,  # hwnd
    ctypes.wintypes.LONG,  # idObject
    ctypes.wintypes.LONG,  # idChild
    ctypes.wintypes.DWORD,  # idEventThread
    ctypes.wintypes.DWORD,  # dwmsEventTime
)


def win_event_callback(
    hWinEventHook: int,
    event: int,
    hwnd: int,
    idObject: int,
    idChild: int,
    idEventThread: int,
    dwmsEventTime: int,
) -> None:
    """Callback function for Windows events.

    Called when foreground window changes or a window is minimized/restored.
    """
    # Skip processing if we're shutting down
    if shutting_down:
        return

    # We handle all relevant events by checking the current state
    # This is simpler and more robust than trying to track specific window events
    check_and_update_state()


# Keep a reference to prevent garbage collection
_win_event_callback = WinEventProcType(win_event_callback)


def install_event_hooks() -> list[int]:
    """Install Windows event hooks for foreground changes, minimize events, and z-order changes.

    Returns a list of hook handles (empty if all failed).
    """
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    hooks = []

    # Hook 1: Foreground and minimize events (0x0003 to 0x0017)
    hook1 = user32.SetWinEventHook(
        EVENT_SYSTEM_FOREGROUND,  # eventMin
        EVENT_SYSTEM_MINIMIZEEND,  # eventMax
        0,  # hmodWinEventProc (0 for out-of-context)
        _win_event_callback,  # lpfnWinEventProc
        0,  # idProcess (0 = all processes)
        0,  # idThread (0 = all threads)
        WINEVENT_OUTOFCONTEXT,  # dwFlags
    )
    if hook1 != 0:
        hooks.append(hook1)

    # Hook 2: Z-order reorder events (0x8004)
    # This fires when windows are reordered in the z-order
    hook2 = user32.SetWinEventHook(
        EVENT_OBJECT_REORDER,  # eventMin
        EVENT_OBJECT_REORDER,  # eventMax
        0,  # hmodWinEventProc (0 for out-of-context)
        _win_event_callback,  # lpfnWinEventProc
        0,  # idProcess (0 = all processes)
        0,  # idThread (0 = all threads)
        WINEVENT_OUTOFCONTEXT,  # dwFlags
    )
    if hook2 != 0:
        hooks.append(hook2)

    return hooks


def uninstall_event_hooks(hooks: list[int]) -> None:
    """Uninstall all Windows event hooks."""
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    for hook in hooks:
        user32.UnhookWinEvent(hook)


# =============================================================================
# System Tray Icon
# =============================================================================


def create_tray_icon_image() -> Image.Image:
    """Create a simple icon image for the system tray.

    Creates a black square with a white border to represent the black bars concept.
    """
    size = 64
    image = Image.new("RGB", (size, size), "black")
    draw = ImageDraw.Draw(image)

    # Draw a white border to make it visible
    border = 4
    draw.rectangle(
        [border, border, size - border - 1, size - border - 1], outline="white", width=2
    )

    # Draw inner rectangle to represent the "game window"
    inner_margin = 16
    draw.rectangle(
        [inner_margin, inner_margin, size - inner_margin - 1, size - inner_margin - 1],
        outline="white",
        width=1,
    )

    return image


def on_tray_quit(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    """Handle quit action from the tray menu."""
    global shutting_down
    icon.stop()
    shutting_down = True


def get_status_text() -> str:
    """Get the current status text for the tray menu."""
    return "Active" if black_bars_active else "Inactive"


def create_tray_menu() -> pystray.Menu:
    """Create the system tray context menu."""
    return pystray.Menu(
        pystray.MenuItem(
            lambda text: f"Status: {get_status_text()}",
            None,
            enabled=False,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Exit", on_tray_quit),
    )


def setup_tray_icon() -> pystray.Icon:
    """Create and configure the system tray icon."""
    icon = pystray.Icon(
        name="black-bars",
        icon=create_tray_icon_image(),
        title="Black Bars",
        menu=create_tray_menu(),
    )
    return icon


def run_tray_icon(icon: pystray.Icon) -> None:
    """Run the tray icon in a separate thread."""
    icon.run()


# =============================================================================
# Main Logic
# =============================================================================


def cleanup() -> None:
    """Clean up resources and restore system state."""
    global black_window_hwnd, hook_handles, tray_icon

    print("\nCleaning up...")

    # Stop the tray icon
    if tray_icon:
        try:
            tray_icon.stop()
        except Exception:
            pass
        tray_icon = None

    # Uninstall the event hooks
    if hook_handles:
        uninstall_event_hooks(hook_handles)
        hook_handles = []

    # Always restore the taskbar
    show_taskbar()

    # Destroy the black window if it exists
    if black_window_hwnd:
        destroy_black_window(black_window_hwnd)
        black_window_hwnd = None

    print("Cleanup complete")


def signal_handler(signum: int, frame: Any) -> None:
    """Handle termination signals gracefully."""
    global shutting_down
    shutting_down = True
    cleanup()


def main() -> None:
    """Main entry point."""
    global hook_handles, tray_icon, shutting_down, WINDOW_TITLES

    # Load configuration
    load_config()

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("Black Bars Script (Event-Driven)")
    print("=" * 50)
    print(f"Monitoring {len(WINDOW_TITLES)} window(s):")
    for title in WINDOW_TITLES:
        print(f"  - '{title}'")
    print("Using Windows Event Hooks (no polling)")
    print("System tray icon active - right-click to access menu")
    print("Press Ctrl+C to exit")
    print("=" * 50)

    try:
        # Install the Windows event hooks
        hook_handles = install_event_hooks()
        if not hook_handles:
            print("Error: Failed to install Windows event hooks")
            sys.exit(1)

        print(f"Event hooks installed successfully ({len(hook_handles)} hooks)")

        # Set up and start the system tray icon in a separate thread
        tray_icon = setup_tray_icon()
        tray_thread = threading.Thread(
            target=run_tray_icon, args=(tray_icon,), daemon=True
        )
        tray_thread.start()
        print("System tray icon started")

        # Check initial state (in case a monitored window is already focused)
        check_and_update_state()

        # Run a non-blocking message loop using PeekMessage
        # This allows Ctrl+C to be processed properly
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        msg = ctypes.wintypes.MSG()

        WM_QUIT = 0x0012

        while not shutting_down:
            # PeekMessage is non-blocking: returns 0 if no message, positive if message found
            result = user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1)  # 1 = PM_REMOVE

            if result > 0:
                if msg.message == WM_QUIT:
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            else:
                # No message - sleep briefly to avoid busy waiting
                import time

                time.sleep(0.01)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
