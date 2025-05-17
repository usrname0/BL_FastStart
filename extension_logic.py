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

        # Draw the "Use Fast Start" checkbox
        if addon_settings: # Check if the property group itself exists
            row = layout.row(align=True)
            if hasattr(addon_settings, "use_faststart_prop"):
                # Determine the text for the checkbox based on whether autosplit is enabled
                checkbox_text = "Fast Start (moov atom to front)"
                if autosplit_enabled:
                    row.enabled = False 
                    checkbox_text = "Fast Start (disabled due to Autosplit)"
                
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
        output_extension_with_dot (str): The correct, lowercase file extension, including the dot (e.g., ".mp4").
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

    # Skip if 'Autosplit Output' is enabled (as Fast Start is incompatible)
    if hasattr(scene.render.ffmpeg, "use_autosplit") and scene.render.ffmpeg.use_autosplit:
        print("Fast Start (render_init): 'Autosplit Output' is enabled. Fast Start processing will be skipped for this render.")
        return

    original_filepath_setting = scene.render.filepath
    # Check if output path is specified, cancel render if not
    if not original_filepath_setting.strip():
        _render_job_cancelled_by_addon = True
        error_message = ("Fast Start: Output path setting is empty. "
                         "A directory or a file path is required. "
                         "Render job cancelled. Please specify an output path in "
                         "Properties > Output Properties > Output.")
        print(f"ERROR - {error_message}")
        raise RuntimeError(error_message) # This will stop the render
    print("Fast Start (render_init): Handler finished, checks passed.")


@persistent
def check_output_path_pre_render_faststart(scene, depsgraph=None):
    # This function is called before each frame is rendered (render_pre).
    # If the job was cancelled by this add-on in render_init, raise an error to stop.
    if _render_job_cancelled_by_addon:
        raise RuntimeError("Render job previously cancelled by Fast Start extension (e.g. due to empty output path).")

@persistent
def post_render_faststart_handler(scene, depsgraph=None):
    # This function is called after the entire render job is completed.
    global _render_job_cancelled_by_addon

    # Skip if the render was cancelled by this add-on
    if _render_job_cancelled_by_addon: 
        print("Fast Start (post_render): Skipping due to prior cancellation flag by add-on."); return

    scene_specific_settings = scene.fast_start_settings_prop
    # Skip if Fast Start is not enabled
    if not scene_specific_settings or not scene_specific_settings.use_faststart_prop:
        return

    # Skip if output is not FFMPEG MP4/MOV
    if not (scene.render.image_settings.file_format == 'FFMPEG' and \
            scene.render.ffmpeg.format in {'MPEG4', 'QUICKTIME'}):
        return
        
    # Skip if 'Autosplit Output' is enabled
    if hasattr(scene.render.ffmpeg, "use_autosplit") and scene.render.ffmpeg.use_autosplit:
        print("Fast Start (post_render): 'Autosplit Output' is enabled. Skipping Fast Start processing.")
        return

    print(f"Fast Start (post_render): Handler invoked. Proceeding with Fast Start logic.")

    # Get add-on preferences (for the suffix)
    addon_package_name = __package__ or "blender_faststart" 
    addon_prefs = None
    try:
        addon_prefs = bpy.context.preferences.addons[addon_package_name].preferences
    except KeyError:
        print(f"Fast Start (post_render) ERROR: Could not retrieve add-on preferences for '{addon_package_name}'.")

    default_suffix_value = "-faststart"
    custom_suffix = default_suffix_value 

    if addon_prefs and hasattr(addon_prefs, 'faststart_suffix_prop'):
        user_suffix_from_prefs = addon_prefs.faststart_suffix_prop
        user_suffix_stripped = user_suffix_from_prefs.strip() if user_suffix_from_prefs is not None else ""
        if user_suffix_stripped: 
            custom_suffix = user_suffix_stripped
        elif user_suffix_from_prefs is not None: # User explicitly set it to blank
            print(f"Fast Start (post_render): User-defined suffix is blank. Using default: '{default_suffix_value}'")
    else:
        print(f"Fast Start (post_render): Suffix property or addon_prefs missing. Using default suffix: '{default_suffix_value}'")

    # --- Sanitize the suffix ---
    suffix_before_final_sanitize = custom_suffix
    custom_suffix = custom_suffix.replace("..", "") # Prevent path traversal
    reserved_chars_pattern = r'[<>:"/\\|?*]' # Filesystem reserved characters
    custom_suffix = re.sub(reserved_chars_pattern, '_', custom_suffix)
    custom_suffix = re.sub(r'[\x00-\x1F]', '', custom_suffix) # ASCII control characters
    if not custom_suffix.strip(): 
        if suffix_before_final_sanitize and suffix_before_final_sanitize.strip() and suffix_before_final_sanitize != default_suffix_value:
            print(f"Fast Start (post_render): Suffix '{suffix_before_final_sanitize}' became blank after sanitization. Reverting to default: '{default_suffix_value}'")
        custom_suffix = default_suffix_value
    elif custom_suffix != suffix_before_final_sanitize:
        print(f"Fast Start (post_render): Suffix sanitized from '{suffix_before_final_sanitize}' to '{custom_suffix}'")
    # --- End Sanitization ---

    # --- Determine Original Rendered File Path (Logic based on user test cases) ---
    original_filepath_setting_raw = scene.render.filepath 
    abs_filepath_setting = bpy.path.abspath(original_filepath_setting_raw) 

    container_type = scene.render.ffmpeg.format 
    actual_container_ext = (".mp4" if container_type == 'MPEG4' else ".mov") 

    start_frame = scene.frame_start
    end_frame = scene.frame_end

    original_rendered_file = None
    blender_output_dir = ""
    user_setting_basename = "" 

    if os.path.isdir(abs_filepath_setting): 
        blender_output_dir = abs_filepath_setting
        if bpy.data.is_saved and bpy.data.filepath:
            user_setting_basename = Path(bpy.data.filepath).stem 
        else: 
            user_setting_basename = "" 
    else: 
        blender_output_dir = os.path.dirname(abs_filepath_setting)
        user_setting_basename = os.path.basename(abs_filepath_setting)

    print(f"Fast Start (post_render): User filepath setting: '{original_filepath_setting_raw}'")
    print(f"Fast Start (post_render): Absolute filepath setting: '{abs_filepath_setting}'")
    print(f"Fast Start (post_render): Blender output directory: '{blender_output_dir}'")
    print(f"Fast Start (post_render): Effective user setting basename: '{user_setting_basename}' (derived from path or .blend name)")
    print(f"Fast Start (post_render): Actual container extension: '{actual_container_ext}'")

    user_name_part, user_ext_part = os.path.splitext(user_setting_basename)
    user_ext_part_lower = user_ext_part.lower()

    base_for_construction = ""
    suffix_after_frames = "" 
    frame_padding = 0 

    was_user_ext_provided = bool(user_ext_part_lower)
    is_user_ext_correct = (user_ext_part_lower == actual_container_ext)

    if was_user_ext_provided and is_user_ext_correct:
        # Scenario A: User provided a CORRECT extension (e.g., "TEST.MP4" or "TEST###.MP4" for MP4 container)
        # Blender uses the user_name_part AS IS (e.g., "TEST" or "TEST###").
        # It does NOT process hashes into frame numbers in this specific case if a correct extension is given.
        # The extension is just lowercased.
        print(f"Fast Start (post_render): Scenario A - Correct extension provided ('{user_ext_part}'). Filename part used literally.")
        base_for_construction = user_name_part # This will be "TEST" or "TEST###"
        frame_padding = 0 # Crucial: No frame number processing by our helper for this specific case
        suffix_after_frames = ""
        print(f"Fast Start (post_render): Base for construction: '{base_for_construction}', Frame padding: {frame_padding} (no frame processing).")
    
    elif not was_user_ext_provided:
        # Scenario B: User provided NO extension (e.g., "TEST" or "###TEST###" for MP4 container)
        # Blender processes the RIGHTMOST hashes if present, or adds frame numbers if no hashes.
        print(f"Fast Start (post_render): Scenario B - No extension provided by user.")
        effective_stem_for_hashes = user_setting_basename # e.g., "TEST" or "###TEST###"
        
        # Find the rightmost sequence of hashes
        last_hash_match = None
        for match in re.finditer(r'(#+)', effective_stem_for_hashes):
            last_hash_match = match
        
        if last_hash_match:
            print(f"Fast Start (post_render): Rightmost hashes found in '{effective_stem_for_hashes}' at span {last_hash_match.span()}.")
            base_for_construction = effective_stem_for_hashes[:last_hash_match.start()]
            frame_padding = len(last_hash_match.group(1))
            suffix_after_frames = effective_stem_for_hashes[last_hash_match.end():]
        else: # No hashes found
            print(f"Fast Start (post_render): No hashes in '{effective_stem_for_hashes}'. Blender adds frame numbers (range format).")
            base_for_construction = effective_stem_for_hashes 
            frame_padding = 4 # Default padding, will result in range format e.g. 0001-0001
            suffix_after_frames = ""

    else: # was_user_ext_provided and not is_user_ext_correct
        # Scenario C: User provided an INCORRECT extension (e.g., "TEST.MP4" for MOV, or "###TEST###.txt" for MP4)
        # Blender processes the RIGHTMOST hashes in the name part if present, or adds frame numbers if no hashes,
        # and treats the incorrect user extension as part of the suffix before the correct one.
        print(f"Fast Start (post_render): Scenario C - Incorrect extension provided ('{user_ext_part}').")
        stem_candidate_for_hashes = user_name_part # e.g., "TEST" from "TEST.MP4", or "###TEST###" from "###TEST###.txt"

        # Find the rightmost sequence of hashes in the name part
        last_hash_match = None
        for match in re.finditer(r'(#+)', stem_candidate_for_hashes):
            last_hash_match = match

        if last_hash_match:
            # Hashes in name part, incorrect extension (e.g. "###TEST###.txt" for MP4 -> "###TEST001-010.txt.mp4")
            print(f"Fast Start (post_render): Rightmost hashes found in name part '{stem_candidate_for_hashes}' at span {last_hash_match.span()} despite incorrect extension.")
            base_for_construction = stem_candidate_for_hashes[:last_hash_match.start()] # "###TEST"
            frame_padding = len(last_hash_match.group(1)) # 3 (from the rightmost ###)
            # Suffix includes part after rightmost hashes AND the incorrect user extension
            suffix_after_frames = stem_candidate_for_hashes[last_hash_match.end():] + user_ext_part # e.g., "" + ".txt"
        else: # No hashes in name part
            # No hashes in name part, incorrect extension (e.g. "TEST.MP4" for MOV -> "TEST.MP40001-0001.mov")
            print(f"Fast Start (post_render): No hashes in name part '{stem_candidate_for_hashes}'. Entire user basename used as prefix before frames.")
            base_for_construction = user_setting_basename # Entire "TEST.MP4"
            frame_padding = 4 # Default padding, will result in range format
            suffix_after_frames = "" # The incorrect extension is already in base_for_construction

    # Construct the filename Blender is expected to create
    predicted_blender_filename = _construct_video_filename(
        base_for_construction,
        suffix_after_frames,
        start_frame,
        end_frame,
        frame_padding,
        actual_container_ext
    )
    
    potential_final_path = os.path.join(blender_output_dir, predicted_blender_filename)
    print(f"Fast Start (post_render): Predicted Blender output file: '{potential_final_path}'")

    if os.path.exists(potential_final_path) and not os.path.isdir(potential_final_path):
        original_rendered_file = potential_final_path
        print(f"Fast Start (post_render): Successfully found rendered file at predicted path: {original_rendered_file}")
    else:
        print(f"Fast Start (post_render) WARNING: Primary prediction for rendered file failed. Path: '{potential_final_path}' did not exist or was a directory.")

    if not original_rendered_file:
        print(f"Fast Start (post_render) ERROR: Could not find the actual rendered file. "
              f"Blender output setting: '{original_filepath_setting_raw}'. "
              f"Predicted based on logic: '{potential_final_path}'. "
              f"Please check Blender's console for the actual output filename if rendering completed. "
              f"Skipping Fast Start processing.")
        return
    
    if os.path.isdir(original_rendered_file): 
        print(f"Fast Start (post_render) ERROR: Resolved path '{original_rendered_file}' is a directory. "
              f"This should not happen for a video file. Skipping.")
        return

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
    # Registers all classes, properties, UI elements, and handlers for the add-on.
    global _active_handlers_info
    _active_handlers_info.clear()
    
    package_name = __package__
    if not package_name:
        package_name = "blender_faststart" 
        print(f"Warning: __package__ is not set. Defaulting to '{package_name}'. Ensure FastStartAddonPreferences.bl_idname is correct.")

    print(f"Registering Fast Start extension ('{package_name}')...")

    # Register classes
    for cls in classes_to_register:
        try:
            if cls == FastStartAddonPreferences: # Set bl_idname for preferences class
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

    # Add PointerProperty to Scene for scene-specific settings
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
    
    # Append UI drawing function to the render encoding panel
    try:
        if hasattr(bpy.types, "RENDER_PT_encoding") and hasattr(bpy.types.RENDER_PT_encoding, "append"):
            try: 
                bpy.types.RENDER_PT_encoding.remove(draw_faststart_checkbox_ui)
            except: pass 
            bpy.types.RENDER_PT_encoding.append(draw_faststart_checkbox_ui)
            print(f"  Appended checkbox UI to RENDER_PT_encoding panel.")
        else:
             print("  WARNING: Could not append checkbox UI. RENDER_PT_encoding panel or its append method not found.")
    except AttributeError: 
        print("  WARNING: RENDER_PT_encoding panel not found. UI not added (might be normal in headless mode).")
    except Exception as e_ui_append: 
        print(f"  Error appending checkbox UI: {e_ui_append}")

    # Register application handlers
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
        if hasattr(bpy.types, "RENDER_PT_encoding") and hasattr(bpy.types.RENDER_PT_encoding, "remove"):
            bpy.types.RENDER_PT_encoding.remove(draw_faststart_checkbox_ui)
            print(f"  Checkbox UI removed from RENDER_PT_encoding panel.")
    except Exception: 
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
