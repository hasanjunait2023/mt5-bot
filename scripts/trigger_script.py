"""
trigger_script.py  (v3 — 64-bit struct packing fix)
Finds 'Setup_MTF_Charts' in MT5 Navigator tree and double-clicks it.
"""
import ctypes
import ctypes.wintypes as wt
import struct
import time
import sys

import win32gui
import win32api
import win32con
import win32process

kernel32 = ctypes.windll.kernel32
user32   = ctypes.windll.user32

# Declare proper types so 64-bit addresses don't overflow
kernel32.OpenProcess.restype          = wt.HANDLE
kernel32.VirtualAllocEx.restype       = ctypes.c_void_p
kernel32.VirtualAllocEx.argtypes      = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                          wt.DWORD, wt.DWORD]
kernel32.VirtualFreeEx.restype        = wt.BOOL
kernel32.VirtualFreeEx.argtypes       = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                          wt.DWORD]
kernel32.WriteProcessMemory.restype   = wt.BOOL
kernel32.WriteProcessMemory.argtypes  = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.restype    = wt.BOOL
kernel32.ReadProcessMemory.argtypes   = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.CloseHandle.argtypes         = [wt.HANDLE]

TVM_GETNEXTITEM = 0x110A
TVM_GETITEMW    = 0x1138
TVM_EXPAND      = 0x1102
TVM_GETITEMRECT = 0x1104
TVM_SELECTITEM  = 0x110B
TVGN_ROOT  = 0
TVGN_NEXT  = 1
TVGN_CHILD = 4
TVGN_CARET = 9
TVE_EXPAND = 2
TVIF_TEXT   = 0x0001
TVIF_HANDLE = 0x0010

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT   = 0x1000
MEM_RESERVE  = 0x2000
MEM_RELEASE  = 0x8000
PAGE_READWRITE = 4


# ── Remote memory helpers ────────────────────────────────────────────────────

def open_proc(pid):
    h = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    return h  # 0 = fail

def alloc_remote(hproc, size):
    # Returns c_void_p (Python None or int)
    return kernel32.VirtualAllocEx(hproc, None, ctypes.c_size_t(size),
                                   MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)

def free_remote(hproc, addr):
    if addr:
        kernel32.VirtualFreeEx(hproc, addr, ctypes.c_size_t(0), MEM_RELEASE)

def write_remote(hproc, addr, data: bytes):
    n   = ctypes.c_size_t(0)
    buf = ctypes.create_string_buffer(data, len(data))
    kernel32.WriteProcessMemory(hproc, addr, buf, ctypes.c_size_t(len(data)),
                                ctypes.byref(n))
    return n.value

def read_remote(hproc, addr, size) -> bytes:
    buf = ctypes.create_string_buffer(size)
    n   = ctypes.c_size_t(0)
    kernel32.ReadProcessMemory(hproc, addr, buf, ctypes.c_size_t(size), ctypes.byref(n))
    return buf.raw[:n.value]


# ── TVITEMW struct (64-bit Windows layout) ────────────────────────────────────
# Offsets verified for x64:
#  0: mask        UINT (4)
#  4: pad         (4)
#  8: hItem       HTREEITEM / pointer (8)
# 16: state       UINT (4)
# 20: stateMask   UINT (4)
# 24: pszText     LPWSTR / pointer (8)
# 32: cchTextMax  int (4)
# 36: iImage      int (4)
# 40: iSelectedImage int (4)
# 44: cChildren   int (4)
# 48: lParam      LPARAM / pointer (8)
# Total = 56 bytes

TVITEMW_FMT  = "=IIQIIQIIIII"  # 4+4+8+4+4+8+4+4+4+4+4 = 52? let's recalc
# I + I + Q + I + I + Q + I + I + I + I + I
# 4 + 4 + 8 + 4 + 4 + 8 + 4 + 4 + 4 + 4 + 4 = 52 bytes but with padding:
# Actually with = (standard/no alignment), no auto-padding.
# Let's use explicit padding byte fields instead.

def pack_tvitemw(mask, hitem, text_addr, cch=256):
    # Manual packing with proper 64-bit padding
    data  = struct.pack('<I', mask)          # 0: mask UINT (4)
    data += b'\x00' * 4                      # 4: pad (4)  — pointer alignment
    data += struct.pack('<Q', hitem)         # 8: hItem (8)
    data += struct.pack('<II', 0, 0)         # 16: state, stateMask (4+4)
    data += struct.pack('<Q', text_addr)     # 24: pszText (8)
    data += struct.pack('<i', cch)           # 32: cchTextMax (4)
    data += struct.pack('<iii', 0, 0, 0)     # 36: iImage, iSelectedImage, cChildren (4+4+4)
    data += struct.pack('<Q', 0)             # 48: lParam (8)
    return data   # 56 bytes total


def get_item_text(tree_hwnd, hitem, pid):
    hproc = open_proc(pid)
    if not hproc:
        return ""
    TEXT_BYTES = 512  # 256 wchars
    text_remote = alloc_remote(hproc, TEXT_BYTES)
    tvi_remote  = alloc_remote(hproc, 64)   # 56 + slack
    try:
        tvi_bytes = pack_tvitemw(TVIF_TEXT | TVIF_HANDLE, hitem, text_remote, 256)
        write_remote(hproc, tvi_remote, tvi_bytes)
        win32gui.SendMessage(tree_hwnd, TVM_GETITEMW, 0, tvi_remote)
        raw = read_remote(hproc, text_remote, TEXT_BYTES)
        return raw.decode('utf-16-le').rstrip('\x00')
    finally:
        free_remote(hproc, text_remote)
        free_remote(hproc, tvi_remote)
        kernel32.CloseHandle(hproc)


def get_item_rect_screen(tree_hwnd, hitem, pid):
    """TVM_GETITEMRECT — lparam is ptr to RECT that initially holds hItem."""
    hproc = open_proc(pid)
    if not hproc:
        return None
    buf_remote = alloc_remote(hproc, 32)
    try:
        # Write hItem into first 8 bytes of buffer
        write_remote(hproc, buf_remote, struct.pack('<Q', hitem))
        ok = win32gui.SendMessage(tree_hwnd, TVM_GETITEMRECT, 1, buf_remote)
        if not ok:
            return None
        data = read_remote(hproc, buf_remote, 16)
        l, t, r, b = struct.unpack('<iiii', data)
        pt = wt.POINT(l, t)
        user32.ClientToScreen(tree_hwnd, ctypes.byref(pt))
        w, h = r - l, b - t
        return (pt.x, pt.y, pt.x + w, pt.y + h)
    finally:
        free_remote(hproc, buf_remote)
        kernel32.CloseHandle(hproc)


# ── Tree walker ──────────────────────────────────────────────────────────────

def walk(tree_hwnd, pid, parent=None, depth=0, max_depth=4):
    msg_start = TVM_GETNEXTITEM
    if parent is None:
        node = win32gui.SendMessage(tree_hwnd, msg_start, TVGN_ROOT, 0)
    else:
        node = win32gui.SendMessage(tree_hwnd, msg_start, TVGN_CHILD, parent)
    while node:
        text = get_item_text(tree_hwnd, node, pid)
        yield node, text, depth
        if depth < max_depth:
            yield from walk(tree_hwnd, pid, node, depth + 1, max_depth)
        node = win32gui.SendMessage(tree_hwnd, msg_start, TVGN_NEXT, node)


# ── Window helpers ────────────────────────────────────────────────────────────

def find_mt5():
    found = []
    def cb(h, _):
        if not win32gui.IsWindowVisible(h): return
        try:
            t = win32gui.GetWindowText(h)
            if "Exness-MT5" in t or "MetaTrader 5" in t:
                found.append(h)
        except Exception: pass
    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def find_treeview(parent):
    trees = []
    def cb(h, _):
        if win32gui.GetClassName(h) == "SysTreeView32":
            trees.append(h)
    try: win32gui.EnumChildWindows(parent, cb, None)
    except Exception: pass
    return trees[0] if trees else None


def activate(hwnd):
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.BringWindowToTop(hwnd)
    try:
        # Allow this process to set foreground window
        user32.AllowSetForegroundWindow(0xFFFFFFFF)  # ASFW_ANY
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        # Fallback: use keybd_event trick to steal focus
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
    time.sleep(0.5)


def double_click_screen(x, y):
    win32api.SetCursorPos((x, y))
    time.sleep(0.15)
    for _ in range(2):
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        time.sleep(0.06)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP,  0, 0)
        time.sleep(0.07)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    mt5 = find_mt5()
    if not mt5:
        print("ERROR: MT5 not running"); return

    activate(mt5)

    # Open Navigator
    win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
    time.sleep(0.05)
    win32api.keybd_event(0x4E, 0, 0, 0); time.sleep(0.05)
    win32api.keybd_event(0x4E, 0, win32con.KEYEVENTF_KEYUP, 0); time.sleep(0.05)
    win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(1.0)

    tree = find_treeview(mt5)
    if not tree:
        print("ERROR: TreeView not found"); return

    _, pid = win32process.GetWindowThreadProcessId(tree)
    print(f"TreeView={tree}  PID={pid}")

    # Walk tree — find Scripts and Setup_MTF_Charts
    scripts_h = None
    setup_h   = None
    print("Walking Navigator tree (reading item names)...")

    for hitem, text, depth in walk(tree, pid, max_depth=2):
        if text:
            print(f"{'  '*depth}{text!r}")
        if text == "Scripts" and depth == 0:
            scripts_h = hitem
        if "Setup_MTF" in text and depth == 1:
            setup_h = hitem
            break

    if not scripts_h:
        print("\nERROR: 'Scripts' node not found — is Navigator open?")
        return

    # Expand Scripts
    win32gui.SendMessage(tree, TVM_EXPAND, TVE_EXPAND, scripts_h)
    time.sleep(0.6)

    if not setup_h:
        # Re-walk children of Scripts
        for hitem, text, depth in walk(tree, pid, parent=scripts_h, max_depth=1):
            if text:
                print(f"  Script: {text!r}")
            if "Setup_MTF" in text:
                setup_h = hitem
                break

    if not setup_h:
        print("ERROR: Setup_MTF_Charts not found — check it compiled to .ex5")
        return

    print(f"\nFound Setup_MTF_Charts handle={hex(setup_h)}")

    # Select it and get rect
    win32gui.SendMessage(tree, TVM_SELECTITEM, TVGN_CARET, setup_h)
    time.sleep(0.3)

    rect = get_item_rect_screen(tree, setup_h, pid)
    if rect:
        cx = (rect[0] + rect[2]) // 2
        cy = (rect[1] + rect[3]) // 2
        print(f"Double-clicking at ({cx}, {cy})")
        activate(mt5)
        double_click_screen(cx, cy)
    else:
        print("Rect not available — using Enter key")
        activate(mt5)
        win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
        time.sleep(0.1)
        win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)

    time.sleep(3)
    print("\nDone! Check MT5 for 10 new M1 chart windows with EA attached.")


if __name__ == "__main__":
    main()
