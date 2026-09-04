"""
Headless register/unregister smoke test for BL Fast Start.

The cheap check that BLENDER.md -> Registration recommends: import the package,
register it, assert the panel draw function, the Scene property and the three
render handlers actually exist, then unregister and assert they are gone.

register() is deliberately unguarded, so a failure here surfaces as a traceback
rather than as the checkbox quietly never appearing.

Run against one Blender:

    "/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b \
        --factory-startup --python tests/smoke.py

or across all installed versions with tests/run.py.
"""

import sys
import traceback
from pathlib import Path

import bpy

# The addon uses relative imports, so it has to be imported as a package: put
# the workspace root on the path and import the project folder by name.
WORKSPACE = str(Path(__file__).resolve().parents[2])
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

import BL_FastStart as addon  # noqa: E402
from BL_FastStart import extension_logic as logic  # noqa: E402

HANDLERS = (
    ("render_init", "on_render_init_faststart"),
    ("render_pre", "check_output_path_pre_render_faststart"),
    ("render_complete", "post_render_faststart_handler"),
)


def draw_func_count():
    """How many copies of our draw function the encoding panel holds.

    WARNING: Panel.append() does not deduplicate. Counting rather than testing
    membership is what catches a reload leaving two checkboxes behind.
    """
    return bpy.types.RENDER_PT_encoding._dyn_ui_initialize().count(
        logic.draw_faststart_checkbox_ui)


def handler_count(list_name, func_name):
    return getattr(bpy.app.handlers, list_name).count(getattr(logic, func_name))


def main():
    version = bpy.app.version_string
    failures = []

    def check(label, got, want=True):
        if got != want:
            failures.append(f"{label}: expected {want}, got {got}")

    # Nothing should be registered yet; if these pass before register() the
    # assertions are not testing anything.
    for cls in logic.classes_to_register:
        check(f"{cls.__name__} absent before register", cls.is_registered, False)
    check("draw func absent before register", draw_func_count(), 0)
    check("Scene property absent before register",
          hasattr(bpy.types.Scene, "fast_start_settings_prop"), False)

    addon.register()

    for cls in logic.classes_to_register:
        check(f"{cls.__name__} registered", cls.is_registered)
    check("draw func appended once", draw_func_count(), 1)
    check("Scene property added",
          hasattr(bpy.types.Scene, "fast_start_settings_prop"))
    check("checkbox property present",
          hasattr(bpy.context.scene.fast_start_settings_prop,
                  "use_faststart_prop"))
    for list_name, func_name in HANDLERS:
        check(f"{list_name} handler added", handler_count(list_name, func_name), 1)

    # A reload is register() over a live registration. It must not double up.
    addon.unregister()
    addon.register()
    check("draw func still appended once after reload", draw_func_count(), 1)
    for list_name, func_name in HANDLERS:
        check(f"{list_name} handler not duplicated",
              handler_count(list_name, func_name), 1)

    addon.unregister()

    for cls in logic.classes_to_register:
        check(f"{cls.__name__} unregistered", cls.is_registered, False)
    check("draw func removed", draw_func_count(), 0)
    check("Scene property removed",
          hasattr(bpy.types.Scene, "fast_start_settings_prop"), False)
    for list_name, func_name in HANDLERS:
        check(f"{list_name} handler removed", handler_count(list_name, func_name), 0)

    if failures:
        print(f"SMOKE {version} FAIL")
        for line in failures:
            print(f"  - {line}")
        return 1

    print(f"SMOKE {version} PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print(f"SMOKE {bpy.app.version_string} ERROR")
        traceback.print_exc()
        sys.exit(1)
