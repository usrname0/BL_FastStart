# filename: extension_logic.py
# Main logic for the Fast Start Blender Extension, using bundled qtfaststart.

# --- Blender File Naming Conventions (as of Blender 4.x) ---
# This script attempts to replicate Blender's output file naming logic.
# IF THERE'S SOME WAY TO JUST PULL THAT OUT OF PYTHON LET ME KNOW
# Key behaviors observed and implemented:
#
# General Principle: If frame numbers are to be added, Blender typically processes
# the RIGHTMOST sequence of hash characters ('#') in the full user-provided filepath string
# to determine padding and placement of frame numbers.
#
# --- WHEN "File Extension" checkbox is CHECKED (scene.render.use_file_extension is True): ---
# 1. Final Extension: Blender appends the correct, lowercase extension for the chosen container (e.g., ".mp4", ".mov").
#
# 2. User Provides Correct Extension (No Frame Numbers unless explicitly handled by other rules):
#    a. "NAME.CORRECT_EXT" (e.g., "TEST.MP4", MP4 container, NAME has no hashes):
#        - Output: "NAME.correct_ext" (e.g., "TEST.mp4"). No frame numbers.
#    b. "NAME###.CORRECT_EXT" (e.g., "TEST###.MP4", MP4 container):
#        - Output: "NAME###.correct_ext" (e.g., "TEST###.mp4").
#        - The "###" in "NAME###" are treated as literal characters. No frame numbers.
#        - This rule (2b) takes precedence over general hash processing if the user-provided extension matches the container.
#
# 3. Hashes Present (and not overridden by Rule 2b):
#    - If the user's input doesn't perfectly match Rule 2a or 2b, but contains hashes:
#    - The RIGHTMOST "###" sequence in the *entire* user_filepath string determines frame numbers.
#    - Example: "te##st.mov###" (MP4 container) -> "te##st.mov<frames>.mp4" (e.g., "te##st.mov001-013.mp4")
#      The "##" are literal. The final "###" provide padding for frame numbers.
#    - Example: "NAME###.WRONG_EXT" (MP4 container) -> "NAME<frames>.WRONG_EXT.<correct_ext>" (e.g., "TEST001-005.TXT.mp4")
#    - Example: "NAME###" (MP4 container) -> "NAME<frames>.<correct_ext>" (e.g., "TEST001-005.mp4")
#
# 4. No Hashes & Incorrect/No User Extension:
#    - If user_filepath is "NAME" or "NAME.WRONG_EXT" (and "NAME" has no hashes, and not Rule 2a):
#        - The entire user_filepath ("NAME" or "NAME.WRONG_EXT") becomes the base.
#        - Default frame numbers (e.g., "0001-0005") are appended.
#        - The correct container extension is then added.
#        - Output: "NAME<frames>.<correct_ext>" or "NAME.WRONG_EXT<frames>.<correct_ext>"
#
# --- WHEN "File Extension" checkbox is UNCHECKED (scene.render.use_file_extension is False): ---
# 5. Extension Handling: The user's typed extension (if any, after the last dot) is used literally (case-sensitive). If no dot, no extension.
#
# 6. Frame Numbering:
#    - If the user_filepath (potentially including a user-typed literal extension) contains "###":
#        - The RIGHTMOST "###" sequence in the *entire user_filepath string* is replaced by frame numbers.
#        - The part of the string after these rightmost hashes becomes the literal suffix/extension.
#        - Example: "#" -> "1-13"
#        - Example: "#.MP4" -> "1-13.MP4"
#        - Example: "te##st.mov###" -> "te##st.mov001-013"
#    - If the user_filepath has NO "###":
#        - The filename is used as is, with its literal user-typed extension. No frame numbers.
#        - Example: "test" -> "test"
#        - Example: "test.MP4" -> "test.MP4"
#
# Note on empty paths: If original_filepath_setting_raw is empty, this addon's render_init handler will raise an error.
# ---

import bpy
import os
import re # For regular expression-based placeholder stripping
from bpy.props import BoolProperty, StringProperty
from bpy.types import PropertyGroup, AddonPreferences
from bpy.app.handlers import persistent

# Imports for bundled qtfaststart
import sys
from pathlib import Path

# --- Module-level globals ---
_render_job_cancelled_by_addon = False
_active_handlers_info = []

# --- Add-on Preferences ---
class FastStartAddonPreferences(AddonPreferences):
    bl_idname = __package__ # Relies on the __package__ variable when run as an addon

    faststart_suffix_prop: StringProperty(
        name="Fast Start Suffix",
        description="Suffix for the fast start file (e.g., '-faststart', '_optimized'). Applied globally. Invalid characters will be replaced. If blank, defaults to '-faststart'.",
        default="-faststart", # Default for the UI field
        maxlen=128,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "faststart_suffix_prop")

# --- Define a Property Group (Scene-specific settings) ---
class FastStartSettingsGroup(PropertyGroup):
    use_faststart_prop: BoolProperty(
        name="Use Fast Start",
        description="Enable Fast Start for MP4/MOV output (moves moov atom, creates new suffixed file)",
        default=False,
    )

# --- UI Panel Drawing Function ---
def draw_faststart_checkbox_ui(self, context):
    scene = context.scene
    addon_settings = scene.fast_start_settings_prop # This is FastStartSettingsGroup

    # Check if the output format is FFMPEG and container is MP4 or QUICKTIME
    if scene.render.image_settings.file_format == 'FFMPEG' and \
       scene.render.ffmpeg.format in {'MPEG4', 'QUICKTIME'}:

        layout = self.layout

        # Determine if 'Autosplit Output' is enabled
        autosplit_enabled = False
        if hasattr(scene.render.ffmpeg, "use_autosplit"):
            autosplit_enabled = scene.render.ffmpeg.use_autosplit

        # Determine if Stereoscopy/Multiview is enabled
        multiview_enabled = scene.render.use_multiview

        # Draw the "Use Fast Start" checkbox
        if addon_settings: # Check if the property group itself exists
            row = layout.row(align=True)
            if hasattr(addon_settings, "use_faststart_prop"):
                checkbox_text = "Fast Start (moov atom to front)"
                can_enable_faststart = True # Assume enabled by default

                # Prioritize disabling conditions:
                # If either multiview or autosplit is enabled, faststart should be disabled.
                # The message should reflect the most relevant or primary reason.

                if multiview_enabled:
                    can_enable_faststart = False
                    checkbox_text = "Fast Start (disabled due to Stereoscopy/Multiview)"
                elif autosplit_enabled: # Only check autosplit if multiview isn't already disabling it
                    can_enable_faststart = False
                    checkbox_text = "Fast Start (disabled due to Autosplit)"

                row.enabled = can_enable_faststart
                row.prop(addon_settings, "use_faststart_prop", text=checkbox_text)
            else:
                row.label(text="Fast Start Prop Missing!", icon='ERROR')


# --- Helper Function for Filename Construction (Simplified) ---
def _construct_video_filename(base_name_part, suffix_after_frame_numbers, start_frame, end_frame, frame_padding_digits, output_extension_with_dot):
    """
    Constructs a filename string based on Blender's naming patterns.
    If frame_padding_digits > 0, always uses start-end frame format (e.g., 0001-0001 for single frame).
    Args:
        base_name_part (str): The initial part of the filename, before any frame numbers.
        suffix_after_frame_numbers (str): Any characters that should appear after frame numbers but before the extension.
                                          Can include user's incorrect extension if applicable.
        start_frame (int): The starting frame number.
        end_frame (int): The ending frame number.
        frame_padding_digits (int): Number of digits for frame number padding (e.g., 4 for "0001").
                                   If 0, no frame number component is added.
        output_extension_with_dot (str): The file extension, including the dot (e.g., ".mp4", ".MP4", or "").
    """
    frame_str_component = ""

    if frame_padding_digits > 0: # Only add frame numbers if padding is explicitly requested
        # Always use range format if padding is specified
        start_frame_str = f"{start_frame:0{frame_padding_digits}d}"
        end_frame_str = f"{end_frame:0{frame_padding_digits}d}"
        frame_str_component = f"{start_frame_str}-{end_frame_str}"

    return f"{base_name_part}{frame_str_component}{suffix_after_frame_numbers}{output_extension_with_dot}"


# --- QTFASTSTART Processing Logic ---
def run_qtfaststart_processing(input_path_str, output_path_str):
    # Prints a message indicating the start of qtfaststart processing
    print(f"QTFASTSTART: Attempting to process '{input_path_str}' to '{output_path_str}'")
    # Checks if the input file exists
    if not os.path.exists(input_path_str):
        print(f"QTFASTSTART ERROR: Input file not found: {input_path_str}"); return False
    # Checks if the input path is a directory (it should be a file)
    if os.path.isdir(input_path_str):
        print(f"QTFASTSTART ERROR: Input path '{input_path_str}' is a directory, but expected a file."); return False

    # Creates the output directory if it doesn't exist
    output_dir = os.path.dirname(output_path_str)
    if output_dir and not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir, exist_ok=True)
            print(f"QTFASTSTART: Created output directory for faststart file: {output_dir}")
        except Exception as e_dir:
            print(f"QTFASTSTART ERROR: Could not create output directory '{output_dir}': {e_dir}"); return False

    # Locates the bundled qtfaststart library
    addon_root_dir = Path(__file__).parent.resolve()
    libs_dir = addon_root_dir / "libs"

    original_sys_path = list(sys.path) # Store original sys.path
    qt_processor_module = None
    # Define custom exception types (will be overwritten by actual exceptions from qtfaststart if available)
    QtFastStartSetupError = Exception
    QtMalformedFileError = Exception
    QtUnsupportedFormatError = Exception

    # Temporarily add libs_dir to sys.path to allow importing qtfaststart
    if str(libs_dir) not in sys.path:
        sys.path.insert(0, str(libs_dir))

    try:
        import qtfaststart # Attempt to import the library

        # Check if the processor submodule exists
        if hasattr(qtfaststart, 'processor'):
            qt_processor_module = qtfaststart.processor
        else:
            print(f"QTFASTSTART ERROR: 'qtfaststart' package does not have a 'processor' attribute/submodule.")
            if str(libs_dir) in sys.path: sys.path = original_sys_path # Restore sys.path
            return False

        # Try to get specific exception types from the library for better error handling
        if hasattr(qtfaststart, 'exceptions'):
            if hasattr(qtfaststart.exceptions, 'FastStartSetupError'): QtFastStartSetupError = qtfaststart.exceptions.FastStartSetupError
            if hasattr(qtfaststart.exceptions, 'MalformedFileError'): QtMalformedFileError = qtfaststart.exceptions.MalformedFileError
            if hasattr(qtfaststart.exceptions, 'UnsupportedFormatError'): QtUnsupportedFormatError = qtfaststart.exceptions.UnsupportedFormatError
    except ImportError as e_import:
        print(f"QTFASTSTART ERROR: Import failed for 'qtfaststart' from '{libs_dir}': {e_import}")
        if str(libs_dir) in sys.path: sys.path = original_sys_path # Restore sys.path
        return False
    except Exception as e_generic_import:
        print(f"QTFASTSTART ERROR: A generic error occurred during the import phase of qtfaststart: {e_generic_import}")
        if str(libs_dir) in sys.path: sys.path = original_sys_path # Restore sys.path
        return False

    success = False
    try:
        if not qt_processor_module:
            return False
        # Process the video file
        qt_processor_module.process(input_path_str, output_path_str)
        # Check if the output file was created and is not empty
        if os.path.exists(output_path_str) and os.path.getsize(output_path_str) > 0:
            success = True
        else:
            print(f"QTFASTSTART ERROR: Output file '{output_path_str}' not found or is empty after process seemed to complete.")
    # Handle specific qtfaststart errors
    except QtFastStartSetupError as e_setup: print(f"QTFASTSTART ERROR (Setup): {e_setup}")
    except QtMalformedFileError as e_malformed: print(f"QTFASTSTART ERROR (Malformed File): {e_malformed}")
    except QtUnsupportedFormatError as e_unsupported: print(f"QTFASTSTART ERROR (Unsupported Format): {e_unsupported}")
    except FileNotFoundError as e_fnf: print(f"QTFASTSTART ERROR (File Not Found during process): {e_fnf}")
    except Exception as e_runtime: print(f"QTFASTSTART ERROR: An unexpected error occurred during qtfaststart.process execution: {e_runtime}")
    finally:
        # Restore the original sys.path
        if str(libs_dir) in sys.path:
             sys.path = original_sys_path
    return success

# --- Application Handlers ---
@persistent # Ensures the handler persists across Blender sessions
def on_render_init_faststart(scene, depsgraph=None):
    # This function is called when a render job is initialized.
    global _render_job_cancelled_by_addon
    _render_job_cancelled_by_addon = False # Reset cancellation flag
    print("Fast Start (render_init): Handler invoked.")

    addon_settings = scene.fast_start_settings_prop
    # Skip if Fast Start is not enabled in scene settings
    if not addon_settings or not addon_settings.use_faststart_prop:
        print("Fast Start (render_init): Feature not enabled in scene settings. Skipping.")
        return

    # Skip if output is not FFMPEG MP4/MOV
    if not (scene.render.image_settings.file_format == 'FFMPEG' and \
            scene.render.ffmpeg.format in {'MPEG4', 'QUICKTIME'}):
        print("Fast Start (render_init): Not FFMPEG MP4/MOV output. Skipping.")
        return

    # Skip if Stereoscopy/Multiview is enabled
    if scene.render.use_multiview:
        print("Fast Start (render_init): Stereoscopy/Multiview is enabled. Fast Start processing will be skipped for this render.")
        return

    # Skip if 'Autosplit Output' is enabled (as Fast Start is incompatible)
    if hasattr(scene.render.ffmpeg, "use_autosplit") and scene.render.ffmpeg.use_autosplit:
        print("Fast Start (render_init): 'Autosplit Output' is enabled. Fast Start processing will be skipped for this render.")
        return

    original_filepath_setting = scene.render.filepath
    if not original_filepath_setting.strip():
        _render_job_cancelled_by_addon = True
        error_message = ("Fast Start: Output path setting is empty. "
                         "A directory or a file path is required. "
                         "Render job cancelled. Please specify an output path in "
                         "Properties > Output Properties > Output.")
        print(f"ERROR - {error_message}")
        raise RuntimeError(error_message)
    print("Fast Start (render_init): Handler finished, checks passed.")


@persistent
def check_output_path_pre_render_faststart(scene, depsgraph=None):
    if _render_job_cancelled_by_addon:
        raise RuntimeError("Render job previously cancelled by Fast Start extension (e.g. due to empty output path).")

@persistent
def post_render_faststart_handler(scene, depsgraph=None):
    global _render_job_cancelled_by_addon
    if _render_job_cancelled_by_addon:
        print("Fast Start (post_render): Skipping due to prior cancellation flag by add-on."); return

    scene_specific_settings = scene.fast_start_settings_prop
    if not scene_specific_settings or not scene_specific_settings.use_faststart_prop: return
    if not (scene.render.image_settings.file_format == 'FFMPEG' and \
            scene.render.ffmpeg.format in {'MPEG4', 'QUICKTIME'}): return

    # Skip if Stereoscopy/Multiview is enabled
    if scene.render.use_multiview:
        print("Fast Start (post_render): Stereoscopy/Multiview is enabled. Skipping Fast Start processing.")
        return

    if hasattr(scene.render.ffmpeg, "use_autosplit") and scene.render.ffmpeg.use_autosplit:
        print("Fast Start (post_render): 'Autosplit Output' is enabled. Skipping Fast Start processing."); return

    print(f"Fast Start (post_render): Handler invoked. Proceeding with Fast Start logic.")

    addon_package_name = __package__ or "blender_faststart"
    addon_prefs = None
    try:
        if FastStartAddonPreferences.bl_idname:
            addon_prefs = bpy.context.preferences.addons[FastStartAddonPreferences.bl_idname].preferences
        else:
            print(f"Fast Start (post_render) WARNING: FastStartAddonPreferences.bl_idname is not set. Attempting fallback with '{addon_package_name}'.")
            addon_prefs = bpy.context.preferences.addons[addon_package_name].preferences
    except KeyError:
        print(f"Fast Start (post_render) ERROR: Could not retrieve add-on preferences using '{FastStartAddonPreferences.bl_idname or addon_package_name}'. Check registration and bl_idname.")

    default_suffix_value = "-faststart"
    custom_suffix = default_suffix_value
    if addon_prefs and hasattr(addon_prefs, 'faststart_suffix_prop'):
        user_suffix_from_prefs = addon_prefs.faststart_suffix_prop
        user_suffix_stripped = user_suffix_from_prefs.strip() if user_suffix_from_prefs is not None else ""
        if user_suffix_stripped: custom_suffix = user_suffix_stripped
        elif user_suffix_from_prefs is not None: print(f"Fast Start (post_render): User-defined suffix is blank. Using default: '{default_suffix_value}'")
    else: print(f"Fast Start (post_render): Suffix property or addon_prefs missing. Using default suffix: '{default_suffix_value}'")

    suffix_before_final_sanitize = custom_suffix
    custom_suffix = custom_suffix.replace("..", "")
    custom_suffix = re.sub(r'[<>:"/\\|?*]', '_', custom_suffix)
    custom_suffix = re.sub(r'[\x00-\x1F]', '', custom_suffix)
    if not custom_suffix.strip():
        if suffix_before_final_sanitize and suffix_before_final_sanitize.strip() and suffix_before_final_sanitize != default_suffix_value:
            print(f"Fast Start (post_render): Suffix '{suffix_before_final_sanitize}' became blank after sanitization. Reverting to default: '{default_suffix_value}'")
        custom_suffix = default_suffix_value
    elif custom_suffix != suffix_before_final_sanitize:
        print(f"Fast Start (post_render): Suffix sanitized from '{suffix_before_final_sanitize}' to '{custom_suffix}'")

    original_filepath_setting_raw = scene.render.filepath
    abs_filepath_setting = bpy.path.abspath(original_filepath_setting_raw)
    container_type = scene.render.ffmpeg.format
    start_frame = scene.frame_start
    end_frame = scene.frame_end

    blender_output_dir = ""
    user_setting_basename = ""
    if os.path.isdir(abs_filepath_setting):
        blender_output_dir = abs_filepath_setting
        if bpy.data.is_saved and bpy.data.filepath: user_setting_basename = Path(bpy.data.filepath).stem
        else: user_setting_basename = ""
    else:
        blender_output_dir = os.path.dirname(abs_filepath_setting)
        user_setting_basename = os.path.basename(abs_filepath_setting)

    print(f"Fast Start (post_render): User filepath setting: '{original_filepath_setting_raw}'")
    print(f"Fast Start (post_render): Blender output directory: '{blender_output_dir}'")
    print(f"Fast Start (post_render): Effective user setting basename: '{user_setting_basename}'")

    # --- Start of Revised Naming Logic ---
    base_for_construction = ""
    frame_padding_final = 0
    suffix_for_constructor = "" # Text between frame numbers and the very final extension
    final_extension_for_constructor = "" # The actual extension string with dot, or empty

    # Determine where the rightmost frame placeholders are in the *entire* user_setting_basename
    text_before_rightmost_hashes = user_setting_basename # Default if no hashes
    padding_from_rightmost_hashes = 0
    text_after_rightmost_hashes = "" # Default if no hashes, or hashes are at the end

    last_hash_match_in_full_basename = None
    for match in re.finditer(r'(#+)', user_setting_basename):
        last_hash_match_in_full_basename = match

    if last_hash_match_in_full_basename:
        text_before_rightmost_hashes = user_setting_basename[:last_hash_match_in_full_basename.start()]
        padding_from_rightmost_hashes = len(last_hash_match_in_full_basename.group(1))
        text_after_rightmost_hashes = user_setting_basename[last_hash_match_in_full_basename.end():]
        print(f"Fast Start (post_render): Parsed full basename: BeforeHashes='{text_before_rightmost_hashes}', Padding={padding_from_rightmost_hashes}, AfterHashes='{text_after_rightmost_hashes}'")


    use_blender_file_extensions_setting = scene.render.use_file_extension
    print(f"Fast Start (post_render): Blender 'File Extension' checkbox is {'ON' if use_blender_file_extensions_setting else 'OFF'}.")

    if use_blender_file_extensions_setting: # "File Extension" CHECKED
        actual_correct_ext_lower = (".mp4" if container_type == 'MPEG4' else ".mov")
        final_extension_for_constructor = actual_correct_ext_lower # Blender will append this

        # Split user_setting_basename to check its own extension
        user_input_name_part, user_input_ext_part = os.path.splitext(user_setting_basename)

        # Rule 2b: "NAME###.CORRECT_EXT" -> "NAME###.correct_ext" (literal hashes in name, correct user ext)
        if user_input_ext_part.lower() == actual_correct_ext_lower and \
           re.search(r'#+', user_input_name_part):
            print("Applying Rule 2b (NAME###.CORRECT_EXT -> NAME###.correct_ext)")
            base_for_construction = user_input_name_part # e.g., NAME###
            frame_padding_final = 0 # No frame processing by helper
            suffix_for_constructor = ""

        # Rule 2a: "NAME.CORRECT_EXT" -> "NAME.correct_ext" (no hashes in name, correct user ext)
        elif user_input_ext_part.lower() == actual_correct_ext_lower and \
             not re.search(r'#+', user_input_name_part): # Ensure name part has no hashes
            print("Applying Rule 2a (NAME.CORRECT_EXT -> NAME.correct_ext)")
            base_for_construction = user_input_name_part # e.g., NAME
            frame_padding_final = 0 # No frame processing by helper
            suffix_for_constructor = ""

        # Rule 3: Hashes are present somewhere in user_setting_basename (and not covered by Rule 2b)
        elif padding_from_rightmost_hashes > 0:
            print("Applying Rule 3 (use_ext=True, rightmost hashes in full string processed)")
            base_for_construction = text_before_rightmost_hashes
            frame_padding_final = padding_from_rightmost_hashes
            suffix_for_constructor = text_after_rightmost_hashes # This is part between frames and final .mp4/.mov

        # Rule 4: No hashes anywhere in user_setting_basename, and extension was incorrect or missing
        # (This also covers cases where user_input_ext_part.lower() != actual_correct_ext_lower)
        else:
            print("Applying Rule 4 (use_ext=True, no hashes, incorrect/no user ext OR no specific rule matched -> default frame append)")
            base_for_construction = user_setting_basename # Full user input becomes base before frames
            frame_padding_final = 4
            suffix_for_constructor = ""

    else: # "File Extension" UNCHECKED
        if padding_from_rightmost_hashes > 0: # Hashes found in full string, use them
            print("Applying hash processing (use_ext=False, rightmost hashes in full string)")
            base_for_construction = text_before_rightmost_hashes
            frame_padding_final = padding_from_rightmost_hashes
            # text_after_rightmost_hashes becomes the literal extension (or empty if hashes were at the very end)
            suffix_for_constructor = ""
            final_extension_for_constructor = text_after_rightmost_hashes
        else: # No hashes anywhere in full string
            print("No hashes in full string, literal output (use_ext=False)")
            # Output is user_setting_basename as is. Split it for constructor.
            base_for_construction, final_extension_for_constructor = os.path.splitext(user_setting_basename)
            # Handle case like "test" where splitext gives ext="" but user_setting_basename is "test"
            if not user_setting_basename.endswith(final_extension_for_constructor) and final_extension_for_constructor == "":
                 base_for_construction = user_setting_basename

            frame_padding_final = 0
            suffix_for_constructor = ""

    print(f"Fast Start (post_render): Final construction params: Base='{base_for_construction}', SuffixAfterFrames='{suffix_for_constructor}', Padding={frame_padding_final}, FinalExt='{final_extension_for_constructor}'")

    predicted_blender_filename = _construct_video_filename(
        base_for_construction,
        suffix_for_constructor,
        start_frame,
        end_frame,
        frame_padding_final,
        final_extension_for_constructor
    )
    # --- End of Revised Naming Logic ---

    potential_final_path = os.path.join(blender_output_dir, predicted_blender_filename)
    print(f"Fast Start (post_render): Predicted Blender output file: '{potential_final_path}'")

    original_rendered_file = None
    if os.path.exists(potential_final_path) and not os.path.isdir(potential_final_path):
        original_rendered_file = potential_final_path
        print(f"Fast Start (post_render): Successfully found rendered file at predicted path: {original_rendered_file}")
    else:
        print(f"Fast Start (post_render) WARNING: Primary prediction for rendered file failed. Path: '{potential_final_path}' did not exist or was a directory.")

    if not original_rendered_file:
        if os.path.isdir(abs_filepath_setting):
            if use_blender_file_extensions_setting:
                blend_name_base = ""
                if bpy.data.is_saved and bpy.data.filepath: blend_name_base = Path(bpy.data.filepath).stem
                if blend_name_base:
                    alt_filename_blend = _construct_video_filename(blend_name_base, "", start_frame, end_frame, 4, final_extension_for_constructor if use_blender_file_extensions_setting else "")
                    alt_path_blend = os.path.join(blender_output_dir, alt_filename_blend)
                    if os.path.exists(alt_path_blend) and not os.path.isdir(alt_path_blend):
                        original_rendered_file = alt_path_blend
                        print(f"Fast Start (post_render): Found with fallback (blend name in dir): {original_rendered_file}")
                if not original_rendered_file:
                    alt_filename_frames = _construct_video_filename("", "", start_frame, end_frame, 4, final_extension_for_constructor if use_blender_file_extensions_setting else "")
                    alt_path_frames = os.path.join(blender_output_dir, alt_filename_frames)
                    if os.path.exists(alt_path_frames) and not os.path.isdir(alt_path_frames):
                        original_rendered_file = alt_path_frames
                        print(f"Fast Start (post_render): Found with fallback (frames in dir): {original_rendered_file}")

        if not original_rendered_file:
            print(f"Fast Start (post_render) ERROR: Could not find the actual rendered file after fallbacks. "
                  f"Blender output setting: '{original_filepath_setting_raw}'. "
                  f"Initial Prediction: '{potential_final_path}'. "
                  f"Skipping Fast Start processing.")
            return

    if os.path.isdir(original_rendered_file):
        print(f"Fast Start (post_render) ERROR: Resolved path '{original_rendered_file}' is a directory. Skipping."); return

    print(f"Fast Start (post_render): Original rendered file identified as: {original_rendered_file}")
    try:
        source_dir, source_basename_full = os.path.split(original_rendered_file)
        source_name_part, source_ext_part = os.path.splitext(source_basename_full)
        fast_start_name_part = f"{source_name_part}{custom_suffix}"
        fast_start_output_path = os.path.join(source_dir, fast_start_name_part + source_ext_part)
        print(f"Fast Start (post_render): Processing '{original_rendered_file}' to new file '{fast_start_output_path}' (Suffix: '{custom_suffix}')")
        success = run_qtfaststart_processing(original_rendered_file, fast_start_output_path)
        if success:
            print(f"Fast Start (post_render): Successfully created 'Fast Start' version: {fast_start_output_path}")
        else:
            print(f"Fast Start (post_render): qtfaststart processing failed. Original file '{original_rendered_file}' is untouched.")
            if os.path.exists(fast_start_output_path) and os.path.getsize(fast_start_output_path) == 0:
                try: os.remove(fast_start_output_path); print(f"Fast Start (post_render): Removed empty/failed output file: {fast_start_output_path}")
                except Exception as e_rem: print(f"Fast Start (post_render): Could not remove potentially failed output {fast_start_output_path}: {e_rem}")
    except Exception as e_path:
        print(f"Fast Start (post_render) ERROR during path processing or calling qtfaststart: {e_path}")
        print(f"  Original file considered was: {original_rendered_file if original_rendered_file else 'Not determined'}")

# --- Registration ---
classes_to_register = (
    FastStartAddonPreferences,
    FastStartSettingsGroup,
)

def register():
    global _active_handlers_info; _active_handlers_info.clear()
    package_name = __package__ or Path(__file__).stem
    FastStartAddonPreferences.bl_idname = package_name
    print(f"Registering Fast Start extension ('{package_name}')...")
    for cls in classes_to_register:
        try: bpy.utils.register_class(cls)
        except ValueError:
            print(f"  Class {cls.__name__} already registered. Attempting re-register.")
            try: bpy.utils.unregister_class(cls); bpy.utils.register_class(cls)
            except Exception as e_rereg: print(f"    Could not re-register {cls.__name__}: {e_rereg}")
        except Exception as e_reg: print(f"  Error registering class {cls.__name__}: {e_reg}")
    print(f"  Registered classes.")
    try:
        bpy.types.Scene.fast_start_settings_prop = bpy.props.PointerProperty(type=FastStartSettingsGroup)
        print("  SUCCESS: PropertyGroup 'fast_start_settings_prop' added to Scene.")
    except Exception as e_pg: print(f"  INFO/ERROR with PropertyGroup: {e_pg}.")
    try:
        if hasattr(bpy.types, "RENDER_PT_encoding") and hasattr(bpy.types.RENDER_PT_encoding, "append"):
            try: bpy.types.RENDER_PT_encoding.remove(draw_faststart_checkbox_ui)
            except: pass
            bpy.types.RENDER_PT_encoding.append(draw_faststart_checkbox_ui)
            print(f"  Appended checkbox UI to RENDER_PT_encoding panel.")
        else: print("  WARNING: Could not append checkbox UI.")
    except Exception as e_ui_append: print(f"  Error appending checkbox UI: {e_ui_append}")
    handler_definitions = [
        ("render_init", bpy.app.handlers.render_init, on_render_init_faststart),
        ("render_pre", bpy.app.handlers.render_pre, check_output_path_pre_render_faststart),
        ("render_complete", bpy.app.handlers.render_complete, post_render_faststart_handler)
    ]
    for name, handler_list, func in handler_definitions:
        if func not in handler_list:
            try: handler_list.append(func); print(f"  Appended handler: {func.__name__} to {name}.")
            except Exception as e_h_append: print(f"  ERROR appending handler {func.__name__}: {e_h_append}")
        else: print(f"  Handler {func.__name__} already in {name}.")
        _active_handlers_info.append((name, handler_list, func))
    print(f"Fast Start Extension ('{package_name}') Registration COMPLETE.")

def unregister():
    global _render_job_cancelled_by_addon, _active_handlers_info
    package_name = __package__ or Path(__file__).stem
    print(f"Unregistering Fast Start Extension ('{package_name}')...")
    for name, handler_list, func in reversed(_active_handlers_info):
        if func in handler_list:
            try: handler_list.remove(func); print(f"  Removed handler: {func.__name__} from {name}.")
            except Exception as e_h_rem: print(f"  ERROR removing handler {func.__name__}: {e_h_rem}")
    _active_handlers_info.clear()
    try:
        if hasattr(bpy.types, "RENDER_PT_encoding") and hasattr(bpy.types.RENDER_PT_encoding, "remove"):
            bpy.types.RENDER_PT_encoding.remove(draw_faststart_checkbox_ui)
            print(f"  Checkbox UI removed.")
    except: pass
    if hasattr(bpy.types.Scene, 'fast_start_settings_prop'):
        try: del bpy.types.Scene.fast_start_settings_prop; print("  PropertyGroup removed.")
        except Exception as e_pg_del: print(f"  Error deleting PropertyGroup: {e_pg_del}")
    for cls in reversed(classes_to_register):
        try: bpy.utils.unregister_class(cls)
        except: pass
    print(f"  Unregistered classes.")
    _render_job_cancelled_by_addon = False
    print(f"Fast Start Extension ('{package_name}') Unregistration COMPLETE.")