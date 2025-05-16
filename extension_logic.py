# filename: extension_logic.py
# Main logic for the Fast Start Blender Extension, using bundled qtfaststart.

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
    bl_idname = __package__ 

    faststart_suffix_prop: StringProperty(
        name="Fast Start Suffix",
        description="Suffix for the fast start file (e.g., '-faststart', '_optimized'). Applied globally. Invalid characters will be replaced. If blank, defaults to '-faststart'.",
        default="-faststart", # Default for the UI field
        maxlen=1024,
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
    addon_settings = scene.fast_start_settings_prop

    if scene.render.image_settings.file_format == 'FFMPEG' and \
       scene.render.ffmpeg.format in {'MPEG4', 'QUICKTIME'}:
        
        layout = self.layout
        
        autosplit_enabled = False
        if hasattr(scene.render.ffmpeg, "use_autosplit"):
            autosplit_enabled = scene.render.ffmpeg.use_autosplit

        if autosplit_enabled:
            box = layout.box()
            box.alert = True 
            box.label(text="Fast Start inactive: 'Autosplit Output' is enabled.", icon='ERROR')

        if addon_settings: # Check if the property group itself exists
            row = layout.row(align=True)
            if hasattr(addon_settings, "use_faststart_prop"):
                if autosplit_enabled:
                    row.enabled = False # Disable the checkbox itself
                row.prop(addon_settings, "use_faststart_prop", text="Fast Start (moov atom to front)")
            else:
                row.label(text="Fast Start Prop Missing!", icon='ERROR')


# --- Helper Function for Filename Construction ---
def _construct_video_filename(prefix, suffix, start_frame, end_frame, num_hashes, expected_ext):
    if start_frame == end_frame: # Single frame
        frame_str = f"{start_frame:0{num_hashes}d}"
        return f"{prefix}{frame_str}{suffix}{expected_ext}"
    else: # Frame range
        start_frame_str = f"{start_frame:0{num_hashes}d}"
        end_frame_str = f"{end_frame:0{num_hashes}d}"
        return f"{prefix}{start_frame_str}-{end_frame_str}{suffix}{expected_ext}"

# --- QTFASTSTART Processing Logic ---
def run_qtfaststart_processing(input_path_str, output_path_str):
    print(f"QTFASTSTART: Attempting to process '{input_path_str}' to '{output_path_str}'")
    if not os.path.exists(input_path_str):
        print(f"QTFASTSTART ERROR: Input file not found: {input_path_str}"); return False
    if os.path.isdir(input_path_str):
        print(f"QTFASTSTART ERROR: Input path '{input_path_str}' is a directory, but expected a file."); return False

    output_dir = os.path.dirname(output_path_str)
    if output_dir and not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir, exist_ok=True)
            print(f"QTFASTSTART: Created output directory for faststart file: {output_dir}")
        except Exception as e_dir:
            print(f"QTFASTSTART ERROR: Could not create output directory '{output_dir}': {e_dir}"); return False

    addon_root_dir = Path(__file__).parent.resolve()
    libs_dir = addon_root_dir / "libs"

    original_sys_path = list(sys.path)
    qt_processor_module = None
    QtFastStartSetupError = Exception
    QtMalformedFileError = Exception
    QtUnsupportedFormatError = Exception

    if str(libs_dir) not in sys.path:
        sys.path.insert(0, str(libs_dir))
        # print(f"QTFASTSTART: Added '{libs_dir}' to sys.path for import.") # Less verbose

    try:
        import qtfaststart
        # print(f"QTFASTSTART: Successfully imported 'qtfaststart' package from {qtfaststart.__file__}") # Less verbose

        if hasattr(qtfaststart, 'processor'):
            qt_processor_module = qtfaststart.processor
        else:
            print(f"QTFASTSTART ERROR: 'qtfaststart' package does not have a 'processor' attribute/submodule.")
            if str(libs_dir) in sys.path: sys.path = original_sys_path # Restore sys.path before returning
            return False

        if hasattr(qtfaststart, 'exceptions'):
            # print(f"QTFASTSTART: Accessing 'qtfaststart.exceptions'.") # Less verbose
            if hasattr(qtfaststart.exceptions, 'FastStartSetupError'): QtFastStartSetupError = qtfaststart.exceptions.FastStartSetupError
            if hasattr(qtfaststart.exceptions, 'MalformedFileError'): QtMalformedFileError = qtfaststart.exceptions.MalformedFileError
            if hasattr(qtfaststart.exceptions, 'UnsupportedFormatError'): QtUnsupportedFormatError = qtfaststart.exceptions.UnsupportedFormatError
        # else: # Less verbose
            # print("QTFASTSTART WARNING: 'qtfaststart.exceptions' module not found.")

    except ImportError as e_import:
        print(f"QTFASTSTART ERROR: Import failed for 'qtfaststart' from '{libs_dir}': {e_import}")
        if str(libs_dir) in sys.path: sys.path = original_sys_path
        return False
    except Exception as e_generic_import:
        print(f"QTFASTSTART ERROR: A generic error occurred during the import phase of qtfaststart: {e_generic_import}")
        if str(libs_dir) in sys.path: sys.path = original_sys_path
        return False

    success = False
    try:
        if not qt_processor_module: 
            print("QTFASTSTART ERROR: qtfaststart.processor not loaded.")
            # No sys.path restoration needed here if qt_processor_module is None due to earlier failure and sys.path already restored
            return False 
        # print(f"QTFASTSTART: Calling qt_processor_module.process('{input_path_str}', '{output_path_str}')") # Verbose
        qt_processor_module.process(input_path_str, output_path_str)
        if os.path.exists(output_path_str) and os.path.getsize(output_path_str) > 0:
            # print(f"QTFASTSTART: Success. Fast start video created: {output_path_str}"); # Less verbose success
            success = True
        else:
            print(f"QTFASTSTART ERROR: Output file '{output_path_str}' not found or is empty after process seemed to complete.")
    except QtFastStartSetupError as e_setup: print(f"QTFASTSTART ERROR (Setup): {e_setup}")
    except QtMalformedFileError as e_malformed: print(f"QTFASTSTART ERROR (Malformed File): {e_malformed}")
    except QtUnsupportedFormatError as e_unsupported: print(f"QTFASTSTART ERROR (Unsupported Format): {e_unsupported}")
    except FileNotFoundError as e_fnf: print(f"QTFASTSTART ERROR (File Not Found during process): {e_fnf}") # More specific
    except Exception as e_runtime: print(f"QTFASTSTART ERROR: An unexpected error occurred during qtfaststart.process execution: {e_runtime}")
    finally:
        if str(libs_dir) in sys.path: # Restore sys.path only if it was modified during this function call
             sys.path = original_sys_path
        # print(f"QTFASTSTART: Restored sys.path after processing attempt.") # Less verbose
    return success

# --- Application Handlers ---
@persistent
def on_render_init_faststart(scene, depsgraph=None):
    global _render_job_cancelled_by_addon
    _render_job_cancelled_by_addon = False # Reset flag at the beginning of each render job
    print("Fast Start (render_init): Handler invoked.")

    addon_settings = scene.fast_start_settings_prop # This is FastStartSettingsGroup
    if not addon_settings or not addon_settings.use_faststart_prop:
        print("Fast Start (render_init): Feature not enabled in scene settings. Skipping.")
        return

    if not (scene.render.image_settings.file_format == 'FFMPEG' and \
            scene.render.ffmpeg.format in {'MPEG4', 'QUICKTIME'}):
        print("Fast Start (render_init): Not FFMPEG MP4/MOV output. Skipping.")
        return

    if hasattr(scene.render.ffmpeg, "use_autosplit") and scene.render.ffmpeg.use_autosplit:
        print("Fast Start (render_init): 'Autosplit Output' is enabled. Fast Start processing will be skipped for this render.")
        return

    original_filepath_setting = scene.render.filepath
    if not original_filepath_setting.strip():
        _render_job_cancelled_by_addon = True # Set cancellation flag
        error_message = ("Fast Start: Output path setting is empty. "
                         "A directory or a file path is required. "
                         "Render job cancelled. Please specify an output path in "
                         "Properties > Output Properties > Output.")
        print(f"ERROR - {error_message}")
        raise RuntimeError(error_message)
    # else: # No need for extensive path logging here if not cancelling (keep it less verbose)
    #    # ... (your previous detailed logging of path analysis if desired, or keep it concise) ...
    #    print(f"Fast Start (render_init): Output path checks passed. Path: '{original_filepath_setting}'")
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
    if not scene_specific_settings or not scene_specific_settings.use_faststart_prop:
        return

    if not (scene.render.image_settings.file_format == 'FFMPEG' and \
            scene.render.ffmpeg.format in {'MPEG4', 'QUICKTIME'}):
        return
        
    if hasattr(scene.render.ffmpeg, "use_autosplit") and scene.render.ffmpeg.use_autosplit:
        print("Fast Start (post_render): 'Autosplit Output' is enabled. Skipping Fast Start processing.")
        return

    print(f"Fast Start (post_render): Handler invoked. Proceeding with Fast Start logic.")

    addon_package_name = __package__ or "blender_faststart" 
    addon_prefs = None
    try:
        addon_prefs = bpy.context.preferences.addons[addon_package_name].preferences
    except KeyError:
        print(f"Fast Start (post_render) ERROR: Could not retrieve add-on preferences for '{addon_package_name}'.")

    default_suffix_value = "-faststart"
    custom_suffix = default_suffix_value 
    initial_user_choice_for_suffix = default_suffix_value # Tracks what user typed before any defaulting/sanitizing for logging

    if addon_prefs and hasattr(addon_prefs, 'faststart_suffix_prop'):
        user_suffix_from_prefs = addon_prefs.faststart_suffix_prop # Get the raw value from prefs
        initial_user_choice_for_suffix = user_suffix_from_prefs if user_suffix_from_prefs is not None else "" # Store exactly what user had, or empty if None

        user_suffix_stripped = user_suffix_from_prefs.strip() if user_suffix_from_prefs is not None else ""

        if user_suffix_stripped: 
            custom_suffix = user_suffix_stripped # Use stripped value if not blank
        else:
            if user_suffix_from_prefs is not None: # Log only if it was explicitly set to blank (not if prop was missing)
                 print(f"Fast Start (post_render): User-defined suffix is blank. Using default: '{default_suffix_value}'")
            # custom_suffix remains default_suffix_value
    else:
        print(f"Fast Start (post_render): Suffix property or addon_prefs missing. Using default suffix: '{default_suffix_value}'")
        # custom_suffix is already default_suffix_value

    # --- Sanitize the suffix ---
    # 'custom_suffix' now holds the user's stripped value, or the default if the user's value was blank.
    # 'initial_user_choice_for_suffix' holds what was in the pref field before defaulting for blankness.
    
    suffix_before_final_sanitize = custom_suffix # This is the value we intend to use, before this specific sanitization pass
    
    # 1. Remove ".." to prevent basic path traversal.
    custom_suffix = custom_suffix.replace("..", "")

    # 2. Define a pattern for filesystem reserved characters to be replaced.
    reserved_chars_pattern = r'[<>:"/\\|?*]' 
    custom_suffix = re.sub(reserved_chars_pattern, '_', custom_suffix)
    
    # 3. Remove ASCII control characters (0-31).
    custom_suffix = re.sub(r'[\x00-\x1F]', '', custom_suffix)

    # 4. If sanitization resulted in an empty string, revert to default.
    if not custom_suffix.strip(): 
        # Only log a change if the suffix_before_final_sanitize was not already the default AND wasn't already blank.
        if suffix_before_final_sanitize and suffix_before_final_sanitize.strip() and suffix_before_final_sanitize != default_suffix_value:
            print(f"Fast Start (post_render): Suffix '{suffix_before_final_sanitize}' became blank after sanitization. Reverting to default: '{default_suffix_value}'")
        custom_suffix = default_suffix_value
    elif custom_suffix != suffix_before_final_sanitize: # Log if sanitization actually changed a non-blank, non-default suffix
        print(f"Fast Start (post_render): Suffix sanitized from '{suffix_before_final_sanitize}' to '{custom_suffix}'")
    # --- End Sanitization ---

    original_filepath_setting = scene.render.filepath
    abs_filepath_setting = bpy.path.abspath(original_filepath_setting)
    container = scene.render.ffmpeg.format
    expected_ext = ".mp4" if container == 'MPEG4' else ".mov"

    original_rendered_file = None
    start_frame = scene.frame_start
    end_frame = scene.frame_end

    path_is_dir_itself = os.path.isdir(abs_filepath_setting)
    setting_output_dir = abs_filepath_setting if path_is_dir_itself else os.path.dirname(abs_filepath_setting)
    setting_basename = "" if path_is_dir_itself else os.path.basename(abs_filepath_setting)
    setting_filename_part, setting_ext_part = os.path.splitext(setting_basename)

    print(f"Fast Start (post_render): Analyzing path setting: '{original_filepath_setting}'")
    # --- File Detection Strategies (Restored full verbose version) ---
    # Strategy 1: Literal match for path with placeholders and extension (e.g., /tmp/####.mp4 if that file exists literally)
    if not path_is_dir_itself and '#' in setting_basename and setting_ext_part:
        print(f"  Strategy 1: Checking for literal match for '{abs_filepath_setting}'")
        if os.path.exists(abs_filepath_setting) and not os.path.isdir(abs_filepath_setting):
            original_rendered_file = abs_filepath_setting
            print(f"    Found literal match: '{original_rendered_file}'")

    # Strategy 2: Process placeholders in filename part if extension is present or absent
    if not original_rendered_file and not path_is_dir_itself and '#' in setting_filename_part:
        print(f"  Strategy 2: Processing placeholders in filename part '{setting_filename_part}' from setting '{original_filepath_setting}'")
        last_hash_match = None
        for match in re.finditer(r'#+', setting_filename_part): # Correctly find last group of hashes
            last_hash_match = match
        if last_hash_match:
            num_hashes = len(last_hash_match.group(0))
            prefix = setting_filename_part[:last_hash_match.start()]
            suffix_after_hash = setting_filename_part[last_hash_match.end():] # Suffix part within the filename stem
            print(f"    Last hash group: Prefix='{prefix}', SuffixAfterHash='{suffix_after_hash}', Hashes={num_hashes}")
            potential_filename_w_ext = _construct_video_filename(prefix, suffix_after_hash, start_frame, end_frame, num_hashes, expected_ext)
            potential_file_path = os.path.join(setting_output_dir, potential_filename_w_ext)
            print(f"    Attempting to find: '{potential_file_path}'")
            if os.path.exists(potential_file_path) and not os.path.isdir(potential_file_path):
                original_rendered_file = potential_file_path
        else:
            print(f"    Warning: Hashes reported in '{setting_filename_part}' but regex found no match for last group.")

    # Strategy 3: Setting is filename without extension, no placeholders (Blender adds frame numbers and extension)
    if not original_rendered_file and not path_is_dir_itself and not setting_ext_part and '#' not in setting_filename_part:
        print(f"  Strategy 3: Setting '{original_filepath_setting}' is filename without extension, no placeholders.")
        filename_prefix = setting_filename_part
        default_padding = 4 # Blender's default padding for frame numbers
        
        # Try with frame numbers
        potential_filename_w_ext_frame = _construct_video_filename(filename_prefix, "", start_frame, end_frame, default_padding, expected_ext)
        potential_file_path_frame = os.path.join(setting_output_dir, potential_filename_w_ext_frame)
        print(f"    Attempting with default padding: '{potential_file_path_frame}'")
        if os.path.exists(potential_file_path_frame) and not os.path.isdir(potential_file_path_frame):
            original_rendered_file = potential_file_path_frame
        elif start_frame == end_frame: # For single frame renders, Blender might not add frame number if not specified with #
            # Try without frame number but with extension
            potential_file_path_no_frame = os.path.join(setting_output_dir, filename_prefix + expected_ext)
            print(f"    Attempting single frame (no frame num, prefix only): '{potential_file_path_no_frame}'")
            if os.path.exists(potential_file_path_no_frame) and not os.path.isdir(potential_file_path_no_frame):
                original_rendered_file = potential_file_path_no_frame
                
    # Strategy 4: Path setting is a directory (Blender uses frame numbers or .blend filename)
    if not original_rendered_file and path_is_dir_itself: # setting_output_dir is abs_filepath_setting
        print(f"  Strategy 4: Setting '{original_filepath_setting}' is a directory.")
        actual_output_dir = abs_filepath_setting
        default_padding = 4 
        
        # Case 1: Blender uses frame numbers as filename
        potential_filename_w_ext_frame = _construct_video_filename("", "", start_frame, end_frame, default_padding, expected_ext)
        potential_file_path_frame = os.path.join(actual_output_dir, potential_filename_w_ext_frame)
        print(f"    Attempting with frame numbers only: '{potential_file_path_frame}'")
        if os.path.exists(potential_file_path_frame) and not os.path.isdir(potential_file_path_frame):
            original_rendered_file = potential_file_path_frame
        # Case 2: For single frame, Blender might use .blend filename if output path is just a dir
        elif start_frame == end_frame and bpy.data.filepath: # Check if blend file is saved
            blend_filename_stem = Path(bpy.data.filepath).stem
            if blend_filename_stem: # Ensure there is a stem (not an unsaved file)
                potential_file_path_blend_name = os.path.join(actual_output_dir, blend_filename_stem + expected_ext)
                print(f"    Attempting single frame (blend file name as base): '{potential_file_path_blend_name}'")
                if os.path.exists(potential_file_path_blend_name) and not os.path.isdir(potential_file_path_blend_name):
                     original_rendered_file = potential_file_path_blend_name
            
    # Strategy 5: General pattern, strip all '#' from name part and use provided or expected extension
    if not original_rendered_file and not path_is_dir_itself: # Fallback for other cases where output is a file pattern
        print(f"  Strategy 5: Path setting '{original_filepath_setting}' treated as general file pattern (stripping all '#').")
        filename_all_hashes_stripped = re.sub(r'#+', '', setting_filename_part)
        # Ensure extension starts with a dot, use expected_ext if setting_ext_part is missing or invalid
        final_ext_for_stripped = setting_ext_part if setting_ext_part and setting_ext_part.startswith('.') else expected_ext
        potential_filename_w_ext = filename_all_hashes_stripped + final_ext_for_stripped
        potential_file_path = os.path.join(setting_output_dir, potential_filename_w_ext)
        print(f"    Attempting file (all '#' stripped from name, ext corrected): '{potential_file_path}'")
        if os.path.exists(potential_file_path) and not os.path.isdir(potential_file_path):
            original_rendered_file = potential_file_path
    # --- End File Detection ---

    if not original_rendered_file:
        print(f"Fast Start (post_render) ERROR: Could not find the actual rendered file using any detection method. Original Blender output setting: '{original_filepath_setting}'. Skipping Fast Start processing."); return
    if os.path.isdir(original_rendered_file): # Should be caught by file detection, but as a safeguard
        print(f"Fast Start (post_render) ERROR: Resolved path '{original_rendered_file}' is a directory. This should not happen for a video file. Skipping."); return

    print(f"Fast Start (post_render): Original rendered file identified as: {original_rendered_file}")
    try:
        source_dir, source_basename_full = os.path.split(original_rendered_file)
        source_name_part, source_ext_part = os.path.splitext(source_basename_full)

        if not source_ext_part or source_ext_part.lower() not in ['.mp4', '.mov']:
            print(f"Fast Start (post_render) WARNING: Original file '{original_rendered_file}' has an unexpected or missing extension ('{source_ext_part}'). Using '{expected_ext}'.")
            source_ext_part = expected_ext

        fast_start_name_part = f"{source_name_part}{custom_suffix}" # Use the sanitized suffix
        fast_start_output_path = os.path.join(source_dir, fast_start_name_part + source_ext_part)

        print(f"Fast Start (post_render): Processing '{original_rendered_file}' to new file '{fast_start_output_path}' (Suffix: '{custom_suffix}')")
        success = run_qtfaststart_processing(original_rendered_file, fast_start_output_path)

        if success:
            print(f"Fast Start (post_render): Successfully created 'Fast Start' version: {fast_start_output_path}")
        else:
            print(f"Fast Start (post_render): qtfaststart processing failed. Original file '{original_rendered_file}' is untouched.")
            if os.path.exists(fast_start_output_path) and os.path.getsize(fast_start_output_path) == 0:
                try:
                    os.remove(fast_start_output_path)
                    print(f"Fast Start (post_render): Removed empty/failed output file: {fast_start_output_path}")
                except Exception as e_rem:
                    print(f"Fast Start (post_render): Could not remove potentially failed output {fast_start_output_path}: {e_rem}")
    except Exception as e_path:
        print(f"Fast Start (post_render) ERROR during path processing or calling qtfaststart: {e_path}")
        print(f"  Original file considered was: {original_rendered_file if original_rendered_file else 'Not determined'}")


# --- Registration ---
classes_to_register = (
    FastStartAddonPreferences,
    FastStartSettingsGroup,
)

def register():
    global _active_handlers_info
    _active_handlers_info.clear()
    
    package_name = __package__
    if not package_name:
        package_name = "blender_faststart" 
        print(f"Warning: __package__ is not set. Defaulting to '{package_name}'. Ensure FastStartAddonPreferences.bl_idname is correct.")

    print(f"Registering Fast Start extension ('{package_name}')...")

    for cls in classes_to_register:
        try:
            if cls == FastStartAddonPreferences:
                cls.bl_idname = package_name
            bpy.utils.register_class(cls)
        except ValueError: 
            print(f"  Class {cls.__name__} already registered. Attempting to unregister and re-register.")
            try: 
                bpy.utils.unregister_class(cls)
                bpy.utils.register_class(cls)
            except Exception as e_rereg: 
                print(f"    Could not re-register {cls.__name__}: {e_rereg}")
        except Exception as e_reg:
             print(f"  Error registering class {cls.__name__}: {e_reg}")
    print(f"  Registered classes.")

    try:
        bpy.types.Scene.fast_start_settings_prop = bpy.props.PointerProperty(type=FastStartSettingsGroup)
        print("  SUCCESS: PropertyGroup 'fast_start_settings_prop' added to Scene.")
    except (TypeError, AttributeError, RuntimeError) as e_pg:
        print(f"  INFO/ERROR with PropertyGroup 'fast_start_settings_prop': {e_pg}. Might already exist if re-registering.")
        current_prop = getattr(bpy.types.Scene, 'fast_start_settings_prop', None)
        if not (isinstance(current_prop, bpy.props.PointerProperty) and \
                current_prop.keywords.get('type') == FastStartSettingsGroup):
            print("    PropertyGroup 'fast_start_settings_prop' issue is not a simple re-registration. Manual check might be needed.")
        pass 
    
    try:
        panel_draw_list_attr_names = ['_dyn_ui_initialize', '_dyn_ui_handlers']
        appended_successfully = False
        for attr_name in panel_draw_list_attr_names:
            if hasattr(bpy.types.RENDER_PT_encoding, attr_name):
                panel_draw_list_func = getattr(bpy.types.RENDER_PT_encoding, attr_name)
                actual_list = panel_draw_list_func() if callable(panel_draw_list_func) else panel_draw_list_func

                if draw_faststart_checkbox_ui not in actual_list:
                    bpy.types.RENDER_PT_encoding.append(draw_faststart_checkbox_ui)
                    print(f"  Appended checkbox UI to RENDER_PT_encoding panel (via {attr_name}).")
                    appended_successfully = True
                    break 
                else:
                    print(f"  Checkbox UI already in RENDER_PT_encoding panel (via {attr_name}).")
                    appended_successfully = True 
                    break
        if not appended_successfully:
             print("  WARNING: Could not append checkbox UI. Panel draw list mechanism not found or UI already present via unknown means.")
    except AttributeError:
        print("  WARNING: RENDER_PT_encoding panel not found. UI not added (might be normal in headless mode).")
    except Exception as e_ui_append: 
        print(f"  Error appending checkbox UI: {e_ui_append}")

    handler_definitions = [
        ("render_init", bpy.app.handlers.render_init, on_render_init_faststart),
        ("render_pre", bpy.app.handlers.render_pre, check_output_path_pre_render_faststart),
        ("render_complete", bpy.app.handlers.render_complete, post_render_faststart_handler)
    ]
    _active_handlers_info.clear() 
    for name, handler_list, func in handler_definitions:
        if func not in handler_list:
            try: 
                handler_list.append(func)
                print(f"  Appended handler: {func.__name__} to bpy.app.handlers.{name}.")
            except Exception as e_handler_append: 
                print(f"  ERROR appending handler {func.__name__} to {name}: {e_handler_append}")
        else:
            print(f"  Handler {func.__name__} already in bpy.app.handlers.{name}.")
        _active_handlers_info.append((name, handler_list, func))
        
    print(f"Fast Start Extension ('{package_name}') Registration COMPLETE.")

def unregister():
    global _render_job_cancelled_by_addon, _active_handlers_info
    
    package_name = __package__ or "blender_faststart"
    print(f"Unregistering Fast Start Extension ('{package_name}')...")

    for name, handler_list, func in reversed(_active_handlers_info):
        if func in handler_list:
            try: 
                handler_list.remove(func)
                print(f"  Removed handler: {func.__name__} from bpy.app.handlers.{name}.")
            except Exception as e_handler_rem:
                print(f"  ERROR removing handler {func.__name__} from {name}: {e_handler_rem}")
    _active_handlers_info.clear()

    try:
        removed_ui = False
        panel_draw_list_attr_names = ['_dyn_ui_initialize', '_dyn_ui_handlers']
        for attr_name in panel_draw_list_attr_names:
            if hasattr(bpy.types.RENDER_PT_encoding, attr_name):
                panel_draw_list_func = getattr(bpy.types.RENDER_PT_encoding, attr_name)
                actual_list = panel_draw_list_func() if callable(panel_draw_list_func) else panel_draw_list_func
                if draw_faststart_checkbox_ui in actual_list:
                    bpy.types.RENDER_PT_encoding.remove(draw_faststart_checkbox_ui)
                    print(f"  Checkbox UI removed from RENDER_PT_encoding panel (via {attr_name}).")
                    removed_ui = True
                    break
        if not removed_ui:
            try:
                bpy.types.RENDER_PT_encoding.remove(draw_faststart_checkbox_ui)
                print("  Checkbox UI removed from RENDER_PT_encoding panel (fallback direct remove attempt).")
            except:
                pass 
    except Exception as e_ui_rem:
        print(f"  Error removing checkbox UI: {e_ui_rem}")
        pass

    if hasattr(bpy.types.Scene, 'fast_start_settings_prop'):
        try: 
            del bpy.types.Scene.fast_start_settings_prop
            print("  PropertyGroup 'fast_start_settings_prop' removed from Scene.")
        except Exception as e_pg_del: 
            print(f"  Error deleting PropertyGroup from Scene: {e_pg_del}")

    for cls in reversed(classes_to_register):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError: 
            pass 
        except Exception as e_cls_unreg:
            print(f"  Error unregistering class {cls.__name__}: {e_cls_unreg}")
    print(f"  Unregistered classes.")
    
    _render_job_cancelled_by_addon = False
    print(f"  Global variables reset (cancellation_flag).")
    print(f"Fast Start Extension ('{package_name}') Unregistration COMPLETE.")