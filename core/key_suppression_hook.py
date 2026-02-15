"""Key suppression hook — macOS stub.

On macOS, key suppression is handled directly by the CGEventTap in
hotkey_manager.py (returning None from the callback suppresses the event).
This module is kept as an empty stub for import compatibility.
"""
