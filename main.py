"""
League of Legends Black Bars Script (Event-Driven Version)

Creates a black background behind the League of Legends game window when it's focused,
and hides the Windows taskbar. Restores everything when League loses focus or is minimized.

Uses Windows Event Hooks (SetWinEventHook) for efficient event-driven detection instead of polling.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import signal
import sys
from typing import Any

import win32api
import win32con
import win32gui

# Constants
LEAGUE_WINDOW_TITLE = "League of Legends (TM) Client"
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


def is_league_game_window(hwnd: int) -> bool:
    """Check if the given window handle is the League of Legends game window."""
    return get_window_title(hwnd) == LEAGUE_WINDOW_TITLE


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
    class_name = "LeagueBlackBarsWindow"

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


def show_black_window(hwnd: int, league_hwnd: int) -> None:
    """Show the black window and position it just below the League window in z-order."""
    # Position the black window just below League in the z-order
    # This ensures it's behind League but in front of everything else
    win32gui.SetWindowPos(
        hwnd,
        league_hwnd,  # Insert after (below) League window
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


def activate_black_bars(league_hwnd: int) -> None:
    """Activate black bars mode for the given League window."""
    global black_window_hwnd, black_bars_active

    # Get the monitor where League is displayed
    monitor_rect = get_monitor_rect(league_hwnd)
    if not monitor_rect:
        print("Warning: Could not determine monitor for League window")
        return

    # Create and show the black background window
    if black_window_hwnd is None:
        black_window_hwnd = create_black_window(monitor_rect)

    show_black_window(black_window_hwnd, league_hwnd)
    hide_taskbar()
    black_bars_active = True
    print(f"Black bars activated on monitor: {monitor_rect}")


def deactivate_black_bars() -> None:
    """Deactivate black bars mode."""
    global black_window_hwnd, black_bars_active

    if black_window_hwnd:
        hide_black_window(black_window_hwnd)

    show_taskbar()
    black_bars_active = False
    print("Black bars deactivated")


def ensure_black_window_z_order(league_hwnd: int) -> None:
    """Ensure the black window is positioned directly below the League window in z-order."""
    global black_window_hwnd

    if black_window_hwnd is None:
        return

    try:
        # Get the window directly below League in z-order
        window_below_league = win32gui.GetWindow(league_hwnd, win32con.GW_HWNDNEXT)

        # If our black window is not directly below League, reposition it
        if window_below_league != black_window_hwnd:
            win32gui.SetWindowPos(
                black_window_hwnd,
                league_hwnd,  # Insert after (below) League window
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

    if is_league_game_window(foreground_hwnd) and not is_window_minimized(
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
# Main Logic
# =============================================================================


def cleanup() -> None:
    """Clean up resources and restore system state."""
    global black_window_hwnd, hook_handles

    print("\nCleaning up...")

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
    cleanup()
    sys.exit(0)


def main() -> None:
    """Main entry point."""
    global hook_handles

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print("League of Legends Black Bars Script (Event-Driven)")
    print("=" * 50)
    print(f"Monitoring for window: '{LEAGUE_WINDOW_TITLE}'")
    print("Using Windows Event Hooks (no polling)")
    print("Press Ctrl+C to exit")
    print("=" * 50)

    try:
        # Install the Windows event hooks
        hook_handles = install_event_hooks()
        if not hook_handles:
            print("Error: Failed to install Windows event hooks")
            sys.exit(1)

        print(f"Event hooks installed successfully ({len(hook_handles)} hooks)")

        # Check initial state (in case League is already focused)
        check_and_update_state()

        # Run the Windows message loop to receive events
        # This is required for the event hook to work
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        msg = ctypes.wintypes.MSG()

        while True:
            # GetMessage blocks until a message is available
            # Returns 0 for WM_QUIT, -1 for error, positive for other messages
            result = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)

            if result == 0:
                # WM_QUIT received
                break
            elif result == -1:
                # Error occurred
                print("Error in message loop")
                break
            else:
                # Dispatch the message
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

    except Exception as e:
        print(f"Error: {e}")
    finally:
        cleanup()


if __name__ == "__main__":
    main()
