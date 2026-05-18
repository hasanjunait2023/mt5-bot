"""
load_profile.py
Loads the 'MTF_Scalper' profile in the running MT5 terminal via
keyboard automation: File → Profiles → Load → MTF_Scalper → OK
"""
import win32gui, win32api, win32con
import time

def find_mt5():
    found = []
    def cb(h, _):
        if not win32gui.IsWindowVisible(h): return
        try:
            t = win32gui.GetWindowText(h)
            if "Exness-MT5" in t: found.append(h)
        except Exception: pass
    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def activate(hwnd):
    import ctypes
    user32 = ctypes.windll.user32
    user32.AllowSetForegroundWindow(0xFFFFFFFF)
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.BringWindowToTop(hwnd)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        # Alt-trick to steal focus
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        try: win32gui.SetForegroundWindow(hwnd)
        except Exception: pass
    time.sleep(0.5)


def press(vk, delay=0.12):
    win32api.keybd_event(vk, 0, 0, 0)
    time.sleep(0.05)
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(delay)


def combo(vks, delay=0.15):
    for v in vks:
        win32api.keybd_event(v, 0, 0, 0)
        time.sleep(0.04)
    time.sleep(0.06)
    for v in reversed(vks):
        win32api.keybd_event(v, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.04)
    time.sleep(delay)


def wait_for_window(title_contains, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        found = []
        def cb(h, _):
            try:
                t = win32gui.GetWindowText(h)
                if title_contains.lower() in t.lower() and win32gui.IsWindowVisible(h):
                    found.append(h)
            except Exception: pass
        win32gui.EnumWindows(cb, None)
        if found: return found[0]
        time.sleep(0.2)
    return None


def main():
    mt5 = find_mt5()
    if not mt5:
        print("ERROR: MT5 not running"); return
    print(f"MT5 hwnd={mt5}")
    activate(mt5)

    # Method 1: Use MT5 keyboard shortcut for Profiles
    # In MT5: File menu = Alt+F, then look for Profiles submenu
    # Press Alt to open menu bar
    print("Opening File menu...")
    press(win32con.VK_F10)  # Activate menu bar
    time.sleep(0.4)

    # Press Alt+F for File menu
    combo([win32con.VK_MENU, 0x46])  # Alt+F
    time.sleep(0.6)

    # Look for Profiles option — navigate down to find it
    # MT5 File menu items (roughly): New Chart, Open Offline, Profiles, Save as Picture...
    # Press 'R' for pRofiles (or navigate with arrows)
    # In MT5 File menu, "Profiles" might be accessed with 'r' key
    # Try typing 'r' for pRofiles
    press(0x52)  # R
    time.sleep(0.5)

    # Check if a submenu or dialog opened
    profile_win = wait_for_window("Profile", timeout=2)
    if profile_win:
        print(f"Profile window opened: {win32gui.GetWindowText(profile_win)}")
        # Type MTF_Scalper and press OK
        for ch in "MTF_Scalper":
            vk = win32api.VkKeyScan(ch)
            lo = vk & 0xFF
            hi = (vk >> 8) & 0xFF
            if hi & 1: win32api.keybd_event(win32con.VK_SHIFT, 0, 0, 0)
            win32api.keybd_event(lo, 0, 0, 0); time.sleep(0.04)
            win32api.keybd_event(lo, 0, win32con.KEYEVENTF_KEYUP, 0)
            if hi & 1: win32api.keybd_event(win32con.VK_SHIFT, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.03)
        press(win32con.VK_RETURN)
        print("Profile name entered and confirmed")
        return

    # Method 2: Navigate File menu with arrow keys
    # First escape from whatever state we're in
    press(win32con.VK_ESCAPE)
    time.sleep(0.3)
    press(win32con.VK_ESCAPE)
    time.sleep(0.3)

    activate(mt5)
    print("Trying View > Profiles approach...")

    # Some MT5 versions have Profiles under a different menu
    # Let's try Ctrl+F5 which might be a shortcut
    combo([win32con.VK_CONTROL, win32con.VK_F5])
    time.sleep(0.5)

    profile_win = wait_for_window("Profile", timeout=2)
    if profile_win:
        print(f"Profile window opened via Ctrl+F5: {win32gui.GetWindowText(profile_win)}")
        press(win32con.VK_RETURN)
        return

    # Escape and try File > Profiles via careful navigation
    press(win32con.VK_ESCAPE)
    time.sleep(0.3)
    activate(mt5)

    print("Navigating File menu step by step...")
    # Alt to activate menu
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0); time.sleep(0.08)
    win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(0.4)
    press(win32con.VK_RETURN)  # Open first menu item (File)
    time.sleep(0.4)

    # Navigate down to Profiles (usually 3rd item in File menu)
    for _ in range(3):
        press(win32con.VK_DOWN)
    time.sleep(0.3)
    press(win32con.VK_RETURN)
    time.sleep(0.5)

    profile_win = wait_for_window("Profile", timeout=3)
    if profile_win:
        print(f"Profile window: {win32gui.GetWindowText(profile_win)}")
    else:
        print("Profile dialog not found — pressing Escape to clean up")
        press(win32con.VK_ESCAPE)
        press(win32con.VK_ESCAPE)
        print("\nFallback: Load the profile manually:")
        print("  In MT5: File → Profiles → Load → MTF_Scalper → OK")
        print("  (Profile already created at profiles\\MTF_Scalper)")


if __name__ == "__main__":
    main()
