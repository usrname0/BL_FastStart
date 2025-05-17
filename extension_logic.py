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
        maxlen=100,
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


# --- Helper Function for Filename Construction ---
def _construct_video_filename(prefix, suffix, start_frame, end_frame, num_hashes, expected_ext):
    # Constructs filename based on single frame or frame range
    if start_frame == end_frame: # Single frame
        frame_str = f"{start_frame:0{num_hashes}d}"
        return f"{prefix}{frame_str}{suffix}{expected_ext}"
    else: # Frame range
        start_frame_str = f"{start_frame:0{num_hashes}d}"
        end_frame_str = f"{end_frame:0{num_hashes}d}"
        return f"{prefix}{start_frame_str}-{end_frame_str}{suffix}{expected_ext}"

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
            # This error is already printed above if 'processor' attribute is missing.
            # print("QTFASTSTART ERROR: qtfaststart.processor not loaded.") 
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
    initial_user_choice_for_suffix = default_suffix_value

    # Retrieve and validate the custom suffix from preferences
    if addon_prefs and hasattr(addon_prefs, 'faststart_suffix_prop'):
        user_suffix_from_prefs = addon_prefs.faststart_suffix_prop
        initial_user_choice_for_suffix = user_suffix_from_prefs if user_suffix_from_prefs is not None else ""
        user_suffix_stripped = user_suffix_from_prefs.strip() if user_suffix_from_prefs is not None else ""
        if user_suffix_stripped: 
            custom_suffix = user_suffix_stripped
        else:
            if user_suffix_from_prefs is not None:
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

    # Determine original rendered file path and expected extension
    original_filepath_setting = scene.render.filepath
    abs_filepath_setting = bpy.path.abspath(original_filepath_setting) # Convert to absolute path
    container = scene.render.ffmpeg.format
    expected_ext = ".mp4" if container == 'MPEG4' else ".mov"

    original_rendered_file = None
    start_frame = scene.frame_start
    end_frame = scene.frame_end

    # Path analysis to find the actual rendered file
    path_is_dir_itself = os.path.isdir(abs_filepath_setting)
    setting_output_dir = abs_filepath_setting if path_is_dir_itself else os.path.dirname(abs_filepath_setting)
    setting_basename = "" if path_is_dir_itself else os.path.basename(abs_filepath_setting)
    setting_filename_part, setting_ext_part = os.path.splitext(setting_basename)

    print(f"Fast Start (post_render): Analyzing output path setting: '{original_filepath_setting}'")
    # --- File Detection Strategies (Reduced Verbosity) ---
    # Strategy 1: Literal match for path with placeholders and extension
    if not path_is_dir_itself and '#' in setting_basename and setting_ext_part:
        if os.path.exists(abs_filepath_setting) and not os.path.isdir(abs_filepath_setting):
            original_rendered_file = abs_filepath_setting

    # Strategy 2: Process placeholders in filename part
    if not original_rendered_file and not path_is_dir_itself and '#' in setting_filename_part:
        last_hash_match = None
        for match in re.finditer(r'#+', setting_filename_part):
            last_hash_match = match
        if last_hash_match:
            num_hashes = len(last_hash_match.group(0))
            prefix = setting_filename_part[:last_hash_match.start()]
            suffix_after_hash = setting_filename_part[last_hash_match.end():]
            potential_filename_w_ext = _construct_video_filename(prefix, suffix_after_hash, start_frame, end_frame, num_hashes, expected_ext)
            potential_file_path = os.path.join(setting_output_dir, potential_filename_w_ext)
            if os.path.exists(potential_file_path) and not os.path.isdir(potential_file_path):
                original_rendered_file = potential_file_path
        # else: # Warning for no hash match can be noisy if other strategies succeed
            # print(f"Fast Start (post_render) Warning: Hashes in '{setting_filename_part}' but regex found no match.")

    # Strategy 3: Setting is filename without extension, no placeholders
    if not original_rendered_file and not path_is_dir_itself and not setting_ext_part and '#' not in setting_filename_part:
        filename_prefix = setting_filename_part
        default_padding = 4 
        potential_filename_w_ext_frame = _construct_video_filename(filename_prefix, "", start_frame, end_frame, default_padding, expected_ext)
        potential_file_path_frame = os.path.join(setting_output_dir, potential_filename_w_ext_frame)
        if os.path.exists(potential_file_path_frame) and not os.path.isdir(potential_file_path_frame):
            original_rendered_file = potential_file_path_frame
        elif start_frame == end_frame: # Single frame, try without frame number
            potential_file_path_no_frame = os.path.join(setting_output_dir, filename_prefix + expected_ext)
            if os.path.exists(potential_file_path_no_frame) and not os.path.isdir(potential_file_path_no_frame):
                original_rendered_file = potential_file_path_no_frame
                
    # Strategy 4: Path setting is a directory
    if not original_rendered_file and path_is_dir_itself:
        actual_output_dir = abs_filepath_setting
        default_padding = 4 
        potential_filename_w_ext_frame = _construct_video_filename("", "", start_frame, end_frame, default_padding, expected_ext)
        potential_file_path_frame = os.path.join(actual_output_dir, potential_filename_w_ext_frame)
        if os.path.exists(potential_file_path_frame) and not os.path.isdir(potential_file_path_frame):
            original_rendered_file = potential_file_path_frame
        elif start_frame == end_frame and bpy.data.filepath: # Single frame, try .blend filename
            blend_filename_stem = Path(bpy.data.filepath).stem
            if blend_filename_stem:
                potential_file_path_blend_name = os.path.join(actual_output_dir, blend_filename_stem + expected_ext)
                if os.path.exists(potential_file_path_blend_name) and not os.path.isdir(potential_file_path_blend_name):
                     original_rendered_file = potential_file_path_blend_name
            
    # Strategy 5: General pattern, strip all '#' from name part
    if not original_rendered_file and not path_is_dir_itself:
        filename_all_hashes_stripped = re.sub(r'#+', '', setting_filename_part)
        final_ext_for_stripped = setting_ext_part if setting_ext_part and setting_ext_part.startswith('.') else expected_ext
        potential_filename_w_ext = filename_all_hashes_stripped + final_ext_for_stripped
        potential_file_path = os.path.join(setting_output_dir, potential_filename_w_ext)
        if os.path.exists(potential_file_path) and not os.path.isdir(potential_file_path):
            original_rendered_file = potential_file_path
    # --- End File Detection ---

    # If original file not found, log error and skip
    if not original_rendered_file:
        print(f"Fast Start (post_render) ERROR: Could not find the actual rendered file. "
              f"Blender output setting: '{original_filepath_setting}'. Searched in '{setting_output_dir}'. "
              f"Skipping Fast Start processing."); return
    if os.path.isdir(original_rendered_file): # Should be caught by file detection, but as a safeguard
        print(f"Fast Start (post_render) ERROR: Resolved path '{original_rendered_file}' is a directory. "
              f"This should not happen for a video file. Skipping."); return

    print(f"Fast Start (post_render): Original rendered file identified as: {original_rendered_file}")
    try:
        source_dir, source_basename_full = os.path.split(original_rendered_file)
        source_name_part, source_ext_part = os.path.splitext(source_basename_full)

        # Ensure correct extension
        if not source_ext_part or source_ext_part.lower() not in ['.mp4', '.mov']:
            print(f"Fast Start (post_render) WARNING: Original file '{original_rendered_file}' has an unexpected or missing extension ('{source_ext_part}'). Using '{expected_ext}'.")
            source_ext_part = expected_ext

        # Construct the output path for the faststart version
        fast_start_name_part = f"{source_name_part}{custom_suffix}"
        fast_start_output_path = os.path.join(source_dir, fast_start_name_part + source_ext_part)

        print(f"Fast Start (post_render): Processing '{original_rendered_file}' to new file '{fast_start_output_path}' (Suffix: '{custom_suffix}')")
        # Run qtfaststart processing
        success = run_qtfaststart_processing(original_rendered_file, fast_start_output_path)

        if success:
            print(f"Fast Start (post_render): Successfully created 'Fast Start' version: {fast_start_output_path}")
        else:
            print(f"Fast Start (post_render): qtfaststart processing failed. Original file '{original_rendered_file}' is untouched.")
            # Remove empty/failed output file if it exists
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
        panel_draw_list_attr_names = ['_dyn_ui_initialize', '_dyn_ui_handlers'] # Blender 2.8x/2.9x dynamic UI list attributes
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
        if not appended_successfully: # Fallback for older Blender versions or if dynamic list not found
             print("  WARNING: Could not append checkbox UI. Panel draw list mechanism not found or UI already present via unknown means.")
    except AttributeError: # RENDER_PT_encoding might not exist (e.g. headless mode)
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
        _active_handlers_info.append((name, handler_list, func)) # Store for unregistration
        
    print(f"Fast Start Extension ('{package_name}') Registration COMPLETE.")

def unregister():
    # Unregisters all parts of the add-on in reverse order of registration.
    global _render_job_cancelled_by_addon, _active_handlers_info
    
    package_name = __package__ or "blender_faststart"
    print(f"Unregistering Fast Start Extension ('{package_name}')...")

    # Remove application handlers
    for name, handler_list, func in reversed(_active_handlers_info): # Iterate in reverse
        if func in handler_list:
            try: 
                handler_list.remove(func)
                print(f"  Removed handler: {func.__name__} from bpy.app.handlers.{name}.")
            except Exception as e_handler_rem:
                print(f"  ERROR removing handler {func.__name__} from {name}: {e_handler_rem}")
    _active_handlers_info.clear()

    # Remove UI drawing function
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
        if not removed_ui: # Fallback attempt
            try:
                bpy.types.RENDER_PT_encoding.remove(draw_faststart_checkbox_ui)
                print("  Checkbox UI removed from RENDER_PT_encoding panel (fallback direct remove attempt).")
            except: # Silently pass if not found or error during fallback
                pass 
    except Exception as e_ui_rem:
        print(f"  Error removing checkbox UI: {e_ui_rem}")
        pass # Continue unregistration

    # Delete PointerProperty from Scene
    if hasattr(bpy.types.Scene, 'fast_start_settings_prop'):
        try: 
            del bpy.types.Scene.fast_start_settings_prop
            print("  PropertyGroup 'fast_start_settings_prop' removed from Scene.")
        except Exception as e_pg_del: 
            print(f"  Error deleting PropertyGroup from Scene: {e_pg_del}")

    # Unregister classes
    for cls in reversed(classes_to_register): # Unregister in reverse order
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError: # Might already be unregistered if Blender is shutting down
            pass 
        except Exception as e_cls_unreg:
            print(f"  Error unregistering class {cls.__name__}: {e_cls_unreg}")
    print(f"  Unregistered classes.")
    
    # Reset global flags
    _render_job_cancelled_by_addon = False
    print(f"  Global variables reset (cancellation_flag).")
    print(f"Fast Start Extension ('{package_name}') Unregistration COMPLETE.")

