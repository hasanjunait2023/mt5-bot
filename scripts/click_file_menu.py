"""
Load MTF_Scalper profile via MT5 File > Profiles > Load Profile menu.
Uses mouse click to open File menu, then keyboard to navigate to Profiles.
"""
import ctypes
import ctypes.wintypes as wt
import win32gui
import win32api
import win32con
import time

user32 = ctypes.windll.user32
user32.GetMenu.restype = wt.HMENU
user32.GetMenuItemCount.restype = ctypes.c_int
user32.GetMenuItemRect.restype = wt.BOOL
user32.GetMenuItemRect.argtypes = [wt.HWND, wt.HMENU, wt.UINT, ctypes.POINTER(wt.RECT)]


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
    user32.AllowSetForegroundWindow(0xFFFFFFFF)
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.BringWindowToTop(hwnd)
    try: win32gui.SetForegroundWindow(hwnd)
    except Exception: pass
    time.sleep(0.4)


def click(x, y, delay=0.2):
    win32api.SetCursorPos((x, y))
    time.sleep(0.1)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
    time.sleep(0.07)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
    time.sleep(delay)


def press(vk, delay=0.15):
    win32api.keybd_event(vk, 0, 0, 0); time.sleep(0.06)
    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(delay)


def find_popup(timeout=2.5):
    """Find the largest visible popup menu (#32768)."""
    end = time.time() + timeout
    best = []
    while time.time() < end:
        found = []
        def cb(h, _):
            try:
                if win32gui.GetClassName(h) == "#32768" and win32gui.IsWindowVisible(h):
                    r = win32gui.GetWindowRect(h)
                    w = r[2] - r[0]
                    if w > 50:
                        found.append((h, r))
            except Exception: pass
        win32gui.EnumWindows(cb, None)
        if found:
            return sorted(found, key=lambda x: (x[1][2]-x[1][0])*(x[1][3]-x[1][1]), reverse=True)
        time.sleep(0.1)
    return []


def wait_dialog(timeout=4):
    """Wait for a top-level dialog or input window."""
    end = time.time() + timeout
    while time.time() < end:
        found = []
        def cb(h, _):
            try:
                cls = win32gui.GetClassName(h)
                if win32gui.IsWindowVisible(h) and cls not in ("Shell_TrayWnd", "#32768", "Progman"):
                    t = win32gui.GetWindowText(h)
                    if t and "Exness" not in t and "Visual Studio" not in t:
                        r = win32gui.GetWindowRect(h)
                        if 100 < r[2]-r[0] < 800 and 50 < r[3]-r[1] < 400:
                            found.append((h, cls, t, r))
            except Exception: pass
        win32gui.EnumWindows(cb, None)
        if found: return found
        time.sleep(0.1)
    return []


def main():
    mt5 = find_mt5()
    if not mt5:
        print("MT5 not found"); return

    activate(mt5)
    time.sleep(0.3)

    # Get File menu item rect from menu bar
    hmenu = user32.GetMenu(mt5)
    item_rect = wt.RECT()
    user32.GetMenuItemRect(mt5, hmenu, 0, ctypes.byref(item_rect))
    file_cx = (item_rect.left + item_rect.right) // 2
    file_cy = (item_rect.top + item_rect.bottom) // 2
    print(f"File menu at ({file_cx},{file_cy})")

    # STEP 1: Click File menu
    activate(mt5)
    click(file_cx, file_cy, delay=0.6)

    popup = find_popup(timeout=2)
    if not popup:
        print("File menu didn't open"); return
    menu_rect = popup[0][1]
    print(f"File menu popup: {menu_rect}")

    # STEP 2: Navigate Down to Profiles using keyboard
    # MT5 File menu order:  [0]New Chart [1]Offline [sep] [2]Save Pic [3]Save PDF
    # [sep] [4]Data Folder [5]Profiles [sep] [6]Print Preview [7]Print [sep] [8]Exit
    # Profiles is at position 7 (skipping separators = 5 presses of Down)
    # Actually let's just press Down and look for "Profiles" submenu to appear

    # Try clicking at the Y position for "Profiles"
    # Menu runs from menu_rect[1]+2 to menu_rect[3]-2
    # Find Profiles by hovering at different Y positions and watching for submenu
    menu_left  = menu_rect[0]
    menu_right = menu_rect[2]
    menu_top   = menu_rect[1]
    menu_bot   = menu_rect[3]
    menu_cx    = (menu_left + menu_right) // 2

    # Hover scan: move mouse down the menu slowly
    # When the mouse is over Profiles, a submenu arrow will appear
    # We detect: when hovering over a row produces a second popup

    profiles_y = None
    step = 4  # scan every 4 pixels
    prev_popup_count = 1

    for y in range(menu_top + 5, menu_bot - 5, step):
        win32api.SetCursorPos((menu_cx, y))
        time.sleep(0.08)
        pops = find_popup(timeout=0.15)
        count = len(pops)
        # When a submenu appears, we found an item with a submenu (Profiles!)
        if count > prev_popup_count:
            profiles_y = y
            print(f"  Found submenu trigger at y={y} (popup count: {count})")
            break
        prev_popup_count = max(prev_popup_count, count)

    if profiles_y is None:
        # Fall back to clicking at ~60% down the menu (Profiles position estimate)
        profiles_y = menu_top + int((menu_bot - menu_top) * 0.55)
        print(f"  Hovering scan failed — clicking at estimated y={profiles_y}")

    # STEP 3: Click Profiles
    print(f"Clicking Profiles at ({menu_cx}, {profiles_y})")
    click(menu_cx, profiles_y, delay=0.6)

    # STEP 4: Submenu for Profiles should appear
    pops = find_popup(timeout=2)
    print(f"Popups after Profiles click: {len(pops)}")
    for h, r in pops:
        print(f"  {r}")

    if len(pops) >= 2:
        # Find the submenu (smaller/to-the-right popup)
        submenu = None
        for h, r in pops:
            if r[0] >= menu_rect[2] - 10:  # to the right of File menu
                submenu = (h, r)
        if not submenu:
            # Take the one that's NOT the file menu
            for h, r in pops:
                if r != menu_rect:
                    submenu = (h, r)
        if submenu:
            sub_rect = submenu[1]
            sub_cx   = (sub_rect[0] + sub_rect[2]) // 2
            # "Load Profile" is first item in submenu
            load_y   = sub_rect[1] + 10
            print(f"Clicking 'Load Profile' at ({sub_cx}, {load_y})")
            click(sub_cx, load_y, delay=1.0)
        else:
            # Just click first item with Enter
            print("Using Enter for first submenu item")
            press(win32con.VK_RETURN, delay=0.5)
    elif len(pops) == 1:
        # Only one popup — might be the submenu replaced the parent
        h, r = pops[0]
        sub_cx = (r[0] + r[2]) // 2
        load_y = r[1] + 10
        print(f"One popup, clicking at ({sub_cx},{load_y})")
        click(sub_cx, load_y, delay=0.8)
    else:
        # No popup found — maybe Profiles was directly "Load" dialog
        print("No submenu — waiting for dialog")

    # STEP 5: Wait for "Load Profile" dialog and type name
    time.sleep(0.5)
    dialogs = wait_dialog(timeout=3)
    print(f"Dialogs found: {len(dialogs)}")
    for h, cls, txt, r in dialogs:
        print(f"  Dialog: {txt!r} cls={cls} rect={r}")

    if dialogs:
        d_hwnd = dialogs[0][0]
        activate(d_hwnd)
        # Clear any existing text and type MTF_Scalper
        press(win32con.VK_CONTROL if False else win32con.VK_END)  # go to end
        # Select all and type
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        win32api.keybd_event(0x41, 0, 0, 0); time.sleep(0.04)  # Ctrl+A
        win32api.keybd_event(0x41, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.2)

        print("Typing: MTF_Scalper")
        for ch in "MTF_Scalper":
            vk = win32api.VkKeyScan(ch) & 0xFF
            need_shift = (win32api.VkKeyScan(ch) >> 8) & 1
            if need_shift: win32api.keybd_event(win32con.VK_SHIFT, 0, 0, 0)
            win32api.keybd_event(vk, 0, 0, 0); time.sleep(0.04)
            win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
            if need_shift: win32api.keybd_event(win32con.VK_SHIFT, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.03)
        press(win32con.VK_RETURN, delay=1.0)
        print("SUCCESS: Profile load initiated!")
    else:
        # No dialog appeared — maybe Profiles was loaded directly without dialog
        # Or maybe the menu click failed
        print("No dialog found. Pressing Escape to clean up.")
        press(win32con.VK_ESCAPE)
        press(win32con.VK_ESCAPE)
        press(win32con.VK_ESCAPE)
        print("\n--- MANUAL STEP (30 seconds of your time) ---")
        print("In MT5: File > Profiles > Load Profile > type 'MTF_Scalper' > OK")
        print("This loads 10 M1 charts with MTF EA pre-attached (one-time setup)")


if __name__ == "__main__":
    main()
