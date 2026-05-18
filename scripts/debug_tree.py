"""
Walk UIA tree to find Navigator Scripts > Setup_MTF_Charts.
"""
import uiautomation as auto
import time

auto.SetGlobalSearchTimeout(3)

mt5 = auto.WindowControl(searchDepth=1, SubName="Exness-MT5")
if not mt5.Exists():
    print("MT5 not found"); exit()
print(f"MT5: {mt5.Name}")
mt5.SetFocus()
time.sleep(0.5)

def walk_uia(ctrl, depth=0, max_depth=5):
    if depth > max_depth: return
    name = ctrl.Name or ""
    ctype = ctrl.ControlTypeName
    if name or depth < 2:
        print(f"{'  '*depth}[{ctype}] {name!r}")
    try:
        for child in ctrl.GetChildren():
            walk_uia(child, depth+1, max_depth)
    except Exception as e:
        print(f"{'  '*depth}  ERROR: {e}")

# Search specifically for tree items with "Scripts" or "Setup_MTF"
print("\nSearching for tree items...")
tree_items = mt5.GetChildren()  # start with top children

def find_control(root, name_contains=None, ctrl_type=None, max_depth=6):
    """DFS search for a control."""
    results = []
    def _walk(ctrl, depth):
        if depth > max_depth: return
        n = ctrl.Name or ""
        t = ctrl.ControlTypeName
        match = True
        if name_contains and name_contains.lower() not in n.lower(): match = False
        if ctrl_type and ctrl_type != t: match = False
        if match and (name_contains or ctrl_type):
            results.append((ctrl, depth, n, t))
        try:
            for c in ctrl.GetChildren():
                _walk(c, depth+1)
        except Exception:
            pass
    _walk(root, 0)
    return results

# Find all TreeControl items
print("\nAll TreeItems:")
for ctrl, depth, name, ctype in find_control(mt5, ctrl_type="TreeItemControl", max_depth=8):
    print(f"  {'  '*depth}[{ctype}] {name!r}")

# Find items containing "Script"
print("\nItems containing 'Script':")
for ctrl, depth, name, ctype in find_control(mt5, name_contains="script", max_depth=8):
    print(f"  {'  '*depth}[{ctype}] {name!r}")

# Find items containing "Setup"
print("\nItems containing 'Setup':")
for ctrl, depth, name, ctype in find_control(mt5, name_contains="Setup", max_depth=8):
    print(f"  {'  '*depth}[{ctype}] {name!r}")
