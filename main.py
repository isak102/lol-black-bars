import time
import win32gui
import win32con
import tkinter as tk


def toggle_taskbar(show=True):
    print(f"Toggling taskbar to {show}...")
    hwnd = win32gui.FindWindow("Shell_TrayWnd", None)
    cmd = win32con.SW_SHOW if show else win32con.SW_HIDE
    win32gui.ShowWindow(hwnd, cmd)


def set_black_window_below_league(root_hwnd, league_hwnd):
    print("Putting background window below league...")
    win32gui.SetWindowPos(
        root_hwnd, league_hwnd, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
    )


def make_window_tool_window(hwnd):
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    style |= win32con.WS_EX_TOOLWINDOW
    style &= ~win32con.WS_EX_APPWINDOW
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)


def main():
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.configure(bg="black")
    root.withdraw()
    root.update()
    make_window_tool_window(root.winfo_id())

    try:
        while True:
            try:
                print("...")
                # Native Windows window finding
                hwnd = win32gui.FindWindow(None, "League of Legends (TM) Client")
                foreground_hwnd = win32gui.GetForegroundWindow()

                if foreground_hwnd == hwnd and hwnd != 0:
                    toggle_taskbar(False)
                    root.deiconify()
                    root.update()
                    set_black_window_below_league(root.winfo_id(), hwnd)
                    win32gui.SetForegroundWindow(hwnd)
                else:
                    toggle_taskbar(True)
                    root.withdraw()

                time.sleep(0.5)
            except Exception as e:
                print(f"Error: {e}, continuing...")
    except KeyboardInterrupt:
        toggle_taskbar(True)
        root.destroy()


if __name__ == "__main__":
    main()
