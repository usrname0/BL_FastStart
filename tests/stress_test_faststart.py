"""
Fast Start Naming Stress Test
==============================
Paste into Blender's Text Editor and run (Alt+P).

Preconditions:
  - Scene has something to render (even just default cube)
  - Frame range is 1–11
  - Fast Start extension is installed and enabled
  - Output format will be set by this script (FFMPEG / MPEG-4)

Runs 14 test cases covering hashes, wrong extensions, mixed cases,
file-extension toggle on/off, etc. Uses frame_path() to discover
whatever Blender actually produced — no hardcoded expected filenames.
"""

import bpy
import os
import re

# ──────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────
OUTPUT_DIR = r"C:\Users\retcon\Desktop\faststart_test"
SUFFIX = "-faststart"  # must match the addon preference

# (output_path_tail, use_file_extension)
# output_path_tail is appended to OUTPUT_DIR to form scene.render.filepath
TEST_CASES = [
    # --- File Extension ON ---
    (r"\1test",                              True),
    (r"\2test.MP4",                          True),
    (r"\3te#st.MP4",                         True),
    (r"\4test.MOV",                          True),
    (r"\5te##st.MOV",                        True),
    (r"\6###TEST###TEST.MP4###",             True),
    (r"\7TEST###STE.MOV###.TEST",            True),
    # --- File Extension OFF ---
    (r"\8test",                              False),
    (r"\9test.MP4",                          False),
    (r"\10te#st.MP4",                        False),
    (r"\11test.MOV",                         False),
    (r"\12te##st.MOV",                       False),
    (r"\13###TEST###TEST.MP4###",            False),
    (r"\14TEST###STE.MOV###.TEST",           False),
]


def derive_faststart_path(rendered_path, suffix):
    """Same logic the extension uses: insert suffix before extension."""
    directory, basename = os.path.split(rendered_path)
    name, ext = os.path.splitext(basename)
    return os.path.join(directory, name + suffix + ext)


def run_stress_test():
    scene = bpy.context.scene

    # ── Ensure render settings ────────────────────────────
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.frame_start = 1
    scene.frame_end = 11

    # Ensure Fast Start is enabled (scene-level toggle)
    if hasattr(scene, "faststart_settings"):
        scene.faststart_settings.use_faststart_prop = True
    else:
        print("WARNING: faststart_settings not found on scene — "
              "is the extension installed and enabled?")

    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── Results accumulator ───────────────────────────────
    results = []

    for idx, (tail, use_ext) in enumerate(TEST_CASES, start=1):
        output_path = OUTPUT_DIR + tail
        print(f"\n{'='*60}")
        print(f"TEST {idx:>2}: filepath = ...{tail}")
        print(f"         use_file_extension = {use_ext}")
        print(f"{'='*60}")

        # Apply settings
        scene.render.filepath = output_path
        scene.render.use_file_extension = use_ext

        # Render
        bpy.ops.render.render(animation=True)

        # Discover rendered file via frame_path()
        rendered_path = bpy.path.abspath(
            scene.render.frame_path(frame=scene.frame_start)
        )
        rendered_name = os.path.basename(rendered_path)

        # Derive faststart path
        faststart_path = derive_faststart_path(rendered_path, SUFFIX)
        faststart_name = os.path.basename(faststart_path)

        # Check existence
        rendered_exists = os.path.isfile(rendered_path)
        faststart_exists = os.path.isfile(faststart_path)

        status = "PASS" if (rendered_exists and faststart_exists) else "FAIL"

        results.append({
            "num": idx,
            "tail": tail,
            "use_ext": use_ext,
            "rendered_name": rendered_name,
            "rendered_exists": rendered_exists,
            "faststart_name": faststart_name,
            "faststart_exists": faststart_exists,
            "status": status,
        })

        print(f"  Rendered  : {rendered_name}  {'FOUND' if rendered_exists else 'MISSING'}")
        print(f"  FastStart : {faststart_name}  {'FOUND' if faststart_exists else 'MISSING'}")
        print(f"  Result    : {status}")

    # ── Summary table ─────────────────────────────────────
    print(f"\n\n{'='*80}")
    print("STRESS TEST SUMMARY")
    print(f"{'='*80}")
    header = (f"{'#':>3}  {'Ext':>3}  {'Rendered File':<40} {'R?':>3}  "
              f"{'FastStart File':<50} {'F?':>3}  {'Result'}")
    print(header)
    print("-" * len(header))

    pass_count = 0
    for r in results:
        ext_str = "ON" if r["use_ext"] else "OFF"
        r_flag = "Y" if r["rendered_exists"] else "N"
        f_flag = "Y" if r["faststart_exists"] else "N"
        print(f"{r['num']:>3}  {ext_str:>3}  {r['rendered_name']:<40} {r_flag:>3}  "
              f"{r['faststart_name']:<50} {f_flag:>3}  {r['status']}")
        if r["status"] == "PASS":
            pass_count += 1

    print(f"\n{pass_count}/{len(results)} passed")
    if pass_count == len(results):
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED — check output above")


if __name__ == "__main__":
    run_stress_test()
