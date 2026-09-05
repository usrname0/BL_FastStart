"""
End-to-end render test for BL Fast Start.

Renders a real five-frame MPEG-4 animation with the checkbox on, then reads the
top-level atom order out of both files: the copy must have moov before mdat, and
the original must be left exactly as Blender wrote it.

Also covers the two things that are only visible through the handler, not
through the helpers it calls:

  * a conversion that fails partway must not leave a truncated file on disk
  * autosplit and multiview must keep the addon from running at all

and one guarantee inside the vendored library, which is asserted here because
the library itself is kept verbatim: a file with no moov atom is refused before
anything reads the moov.

Run against one Blender:

    "/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b \
        --factory-startup --python tests/test_render.py

or across all installed versions with tests/run.py.
"""

import os
import struct
import sys
import tempfile
import traceback
from pathlib import Path

import bpy

WORKSPACE = str(Path(__file__).resolve().parents[2])
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)

import BL_FastStart as addon  # noqa: E402
from BL_FastStart import extension_logic as logic  # noqa: E402
from BL_FastStart.qtfaststart_lib import MalformedFileError  # noqa: E402

FRAME_START = 1
FRAME_END = 5
RENDER_NAME = "myrender0001-0005.mp4"
FAST_NAME = "myrender0001-0005-faststart.mp4"


def atom(name, payload=b""):
    """One length-prefixed MP4 box, for building a deliberately broken file."""
    return struct.pack(">L4s", 8 + len(payload), name.encode("ascii")) + payload


def top_level_atoms(path, limit=8):
    """Names of the top-level MP4 atoms, in file order.

    An MP4 is a flat sequence of length-prefixed boxes, so walking it needs no
    parser: read a 4-byte big-endian size and a 4-byte name, then skip ahead by
    the size. A size of 1 means the real 64-bit size follows the name.
    """
    names = []
    total = os.path.getsize(path)
    with open(path, "rb") as handle:
        pos = 0
        while pos < total and len(names) < limit:
            handle.seek(pos)
            header = handle.read(8)
            if len(header) < 8:
                break
            size = struct.unpack(">I", header[:4])[0]
            names.append(header[4:8].decode("latin1"))
            if size == 1:
                size = struct.unpack(">Q", handle.read(8))[0]
            if size < 8:
                break
            pos += size
    return names


def configure(scene, out_dir):
    """Set the scene up for a small MPEG-4 animation render."""
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.render.resolution_x = 64
    scene.render.resolution_y = 64
    scene.frame_start = FRAME_START
    scene.frame_end = FRAME_END

    image_settings = scene.render.image_settings
    # Blender 5.0 split media_type out of file_format; FFMPEG is only
    # assignable once the media type is VIDEO. On 4.x there is no such
    # property and file_format takes FFMPEG directly.
    if hasattr(image_settings, "media_type"):
        image_settings.media_type = 'VIDEO'
    image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.filepath = os.path.join(out_dir, "myrender")


def main():
    version = bpy.app.version_string
    failures = []

    # want is annotated because it defaults to True and would otherwise infer
    # as bool, which reports against every count and filename asserted below.
    def check(label: str, got: object, want: object = True):
        if got != want:
            failures.append(f"{label}: expected {want}, got {got}")

    addon.register()
    scene = bpy.context.scene

    with tempfile.TemporaryDirectory() as out_dir:
        configure(scene, out_dir)

        check("format recognized", logic._is_faststart_format(scene))
        check("no incompatible features",
              logic._has_incompatible_features(scene), False)

        # The path the handler will use must be the path Blender actually
        # writes. Asserted before the render so a mismatch names itself rather
        # than presenting as a missing output file.
        check("frame_path matches the render filename",
              os.path.basename(scene.render.frame_path(frame=scene.frame_start)),
              RENDER_NAME)

        scene.fast_start_settings_prop.use_faststart_prop = True
        bpy.ops.render.render(animation=True)

        produced = sorted(os.listdir(out_dir))
        check("both files present", produced, [FAST_NAME, RENDER_NAME])

        if FAST_NAME in produced:
            fast = top_level_atoms(os.path.join(out_dir, FAST_NAME))
            original = top_level_atoms(os.path.join(out_dir, RENDER_NAME))
            check(f"moov before mdat in the copy ({fast})",
                  fast.index("moov") < fast.index("mdat"))
            check(f"original still has moov last ({original})",
                  original.index("moov") > original.index("mdat"))

            # The other side of the moov/mdat comparison: a file that is
            # already optimized is refused rather than rewritten.
            try:
                logic.qtfaststart_process(os.path.join(out_dir, FAST_NAME),
                                          os.path.join(out_dir, "again.mp4"))
                raised = "nothing"
            except Exception as exc:
                raised = type(exc).__name__
            check("an already-optimized file is refused", raised,
                  "FastStartSetupError")

        # A conversion that fails partway leaves a truncated file behind. Only
        # the handler cleans it up, so drive the handler rather than the helper.
        real_process = logic.qtfaststart_process

        def fail_partway(infile, outfile):
            with open(outfile, "wb") as handle:
                handle.write(b"\x00" * 4096)
            raise MalformedFileError("injected")

        logic.qtfaststart_process = fail_partway
        try:
            os.remove(os.path.join(out_dir, FAST_NAME))
            logic.post_render_faststart_handler(scene)
            check("no truncated file left after a failed write",
                  os.path.exists(os.path.join(out_dir, FAST_NAME)), False)
        finally:
            logic.qtfaststart_process = real_process

    # The two configurations the addon must refuse.
    scene.render.ffmpeg.use_autosplit = True
    check("autosplit is incompatible", logic._has_incompatible_features(scene))
    scene.render.ffmpeg.use_autosplit = False

    scene.render.use_multiview = True
    check("multiview is incompatible", logic._has_incompatible_features(scene))
    scene.render.use_multiview = False

    check("suffix sanitized", logic._sanitize_suffix('a<b>c:d/e'), "a_b_c_d_e")
    check("blank suffix falls back", logic._sanitize_suffix("   "), "-faststart")

    # qtfaststart binds moov_atom inside a loop over the index and reads it
    # after the loop, which a type checker reports as possibly unbound five
    # times. It cannot be: get_index() raises unless both moov and mdat are
    # top-level atoms. The library is vendored verbatim, so the guarantee is
    # pinned here rather than annotated there - an UnboundLocalError from a
    # future upstream version would fail this check rather than reach a user.
    with tempfile.TemporaryDirectory() as broken_dir:
        no_moov = os.path.join(broken_dir, "no_moov.mp4")
        with open(no_moov, "wb") as handle:
            handle.write(atom("ftyp", b"isom") + atom("mdat", bytes(16)))
        try:
            logic.qtfaststart_process(no_moov, os.path.join(broken_dir, "out.mp4"))
            raised = "nothing"
        except Exception as exc:
            raised = type(exc).__name__
        check("a file with no moov atom is refused", raised, "MalformedFileError")

    addon.unregister()

    if failures:
        print(f"RENDER {version} FAIL")
        for line in failures:
            print(f"  - {line}")
        return 1

    print(f"RENDER {version} PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        print(f"RENDER {bpy.app.version_string} ERROR")
        traceback.print_exc()
        sys.exit(1)
