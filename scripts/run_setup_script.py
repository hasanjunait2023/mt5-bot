"""
run_setup_script.py
Runs Setup_MTF_Charts script inside the live MT5 terminal using win32 automation.
Brings MT5 to foreground, opens Script via Navigator or View menu.
"""
import win32gui
import win32con
import win32api
import time
import sys

# ── Find MT5 window ──────────────────────────────────────────────────────────
def find_mt5():
    result = []
    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        try:
            t = win32gui.GetWindowText(hwnd)
        except Exception:
            return
        if "Exness-MT5" in t or ("MetaTrader 5" in t and "MetaEditor" not in t):
            result.append(hwnd)
    win32gui.EnumWindows(_cb, None)
    return result[0] if result else None


def activate(hwnd):
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.6)


def key_combo(vk_list):
    """Press a combo of VK codes simultaneously, then release."""
    for vk in vk_list:
        win32api.keybd_event(vk, 0, 0, 0)
        time.sleep(0.04)
    time.sleep(0.08)
    for vk in reversed(vk_list):
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.04)
    time.sleep(0.15)


def press(vk):
    win32api.keybd_event(vk, 0, 0, 0)
    time.sleep(0.06)
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.12)


def type_text(text):
    """Type ASCII text using VK codes."""
    for ch in text:
        vk = win32api.VkKeyScan(ch)
        lo = vk & 0xFF
        hi = (vk >> 8) & 0xFF
        if hi & 1:  # shift needed
            win32api.keybd_event(win32con.VK_SHIFT, 0, 0, 0)
        win32api.keybd_event(lo, 0, 0, 0)
        time.sleep(0.04)
        win32api.keybd_event(lo, 0, win32con.KEYEVENTF_KEYUP, 0)
        if hi & 1:
            win32api.keybd_event(win32con.VK_SHIFT, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.04)


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    hwnd = find_mt5()
    if not hwnd:
        print("ERROR: MT5 window not found. Open MetaTrader 5 first.")
        sys.exit(1)

    title = win32gui.GetWindowText(hwnd)
    print(f"MT5 found: {title}")
    activate(hwnd)

    # Step 1: Open Navigator panel with Ctrl+N
    print("Opening Navigator (Ctrl+N)...")
    key_combo([win32con.VK_CONTROL, 0x4E])  # Ctrl+N
    time.sleep(1.0)

    # Step 2: The script is in Navigator > Scripts > Setup_MTF_Charts
    # Use View menu to make sure Navigator is visible, then use keyboard to navigate
    # Alt to open menu bar
    print("Navigator opened. Finding Scripts > Setup_MTF_Charts...")

    # Find the Navigator TreeView child
    children = []
    def _enum_child(h, _):
        cls = win32gui.GetClassName(h)
        if cls == "SysTreeView32":
            rect = win32gui.GetWindowRect(h)
            children.append((h, rect))
    try:
        win32gui.EnumChildWindows(hwnd, _enum_child, None)
    except Exception:
        pass

    if children:
        tree_hwnd, rect = children[0]
        print(f"Found Navigator TreeView: hwnd={tree_hwnd}")
        # Click on the TreeView to focus it
        cx = (rect[0] + rect[2]) // 2
        cy = (rect[1] + rect[3]) // 2
        win32api.SetCursorPos((cx, cy))
        time.sleep(0.2)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        time.sleep(0.08)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
        time.sleep(0.3)

        # Use keyboard search: press first letter to jump to Scripts
        # MT5 Navigator tree: Accounts, Indicators, Expert Advisors, Scripts, Services
        # Press 'S' multiple times to get to Scripts
        for _ in range(3):
            press(0x53)  # S key
            time.sleep(0.2)

        # Expand Scripts with right arrow
        press(win32con.VK_RIGHT)
        time.sleep(0.5)

        # Press S again to jump to Setup_MTF_Charts
        press(0x53)
        time.sleep(0.3)

        # Enter to run the script
        print("Running Setup_MTF_Charts script via Enter key...")
        press(win32con.VK_RETURN)
        time.sleep(3.0)
        print("Script triggered! MT5 should now open all 10 M1 charts.")
        print("Watch the MT5 window for chart windows appearing.")
    else:
        print("Navigator TreeView not found via enum.")
        print("\nFallback: Navigator is open in MT5.")
        print("Please expand 'Scripts' and double-click 'Setup_MTF_Charts'")
        print("This will open all 10 M1 charts with the EA attached automatically.")


if __name__ == "__main__":
    main()
