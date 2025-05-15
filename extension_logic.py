# filename: extension_logic.py
# Main logic for the Fast Start Blender Extension, using bundled qtfaststart.

import bpy
import os
import re # For regular expression-based placeholder stripping
from bpy.props import BoolProperty, StringProperty # Operator removed from imports
from bpy.types import PropertyGroup # Operator removed from imports
from bpy.app.handlers import persistent

# Imports for bundled qtfaststart
import sys # For sys.path manipulation
from pathlib import Path # For cleaner path construction

# --- Module-level globals ---
_render_job_cancelled_by_addon = False
_active_handlers_info = [] # For robust handler management

# --- Operator to Show Filename Warning (from checkbox update) ---
# REMOVED WarnMissingFilenameOperator class

# --- Update callback for the 'use_faststart_prop' ---
# REMOVED update_faststart_checkbox function as the operator it called is removed.

# --- Define a Property Group ---
class FastStartSettingsGroup(PropertyGroup):
    use_faststart_prop: BoolProperty(
        name="Use Fast Start",
        description="Enable Fast Start for MP4/MOV output (moves moov atom, creates new suffixed file)",
        default=False,
        # REMOVED: update=update_faststart_checkbox 
        # The update callback is no longer needed as the warning popup is removed.
    )

# --- UI Panel Drawing Function ---
def draw_faststart_checkbox_ui(self, context):
    scene = context.scene
    addon_settings = scene.fast_start_settings_prop 

    if scene.render.image_settings.file_format == 'FFMPEG' and \
       scene.render.ffmpeg.format in {'MPEG4', 'QUICKTIME'}:
        if addon_settings:
            layout = self.layout
            row = layout.row(align=True)
            if hasattr(addon_settings, "use_faststart_prop"):
                row.prop(addon_settings, "use_faststart_prop", text="Fast Start (moov atom to front)")
            else:
                row.label(text="Fast Start PG Prop Missing!", icon='ERROR')

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
    """
    Processes the input MP4/MOV file to create an output file with the moov atom at the front.
    Uses the bundled qtfaststart library.
    """
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
        print(f"QTFASTSTART: Added '{libs_dir}' to sys.path for import.")

    try:
        import qtfaststart 
        print(f"QTFASTSTART: Successfully imported 'qtfaststart' package from {qtfaststart.__file__}")

        if hasattr(qtfaststart, 'processor'):
            qt_processor_module = qtfaststart.processor
            print(f"QTFASTSTART: Successfully accessed 'qtfaststart.processor' module.")
        else:
            print(f"QTFASTSTART ERROR: 'qtfaststart' package does not have a 'processor' attribute/submodule.")
            sys.path = original_sys_path
            return False

        if hasattr(qtfaststart, 'exceptions'):
            print(f"QTFASTSTART: Accessing 'qtfaststart.exceptions'.")
            if hasattr(qtfaststart.exceptions, 'FastStartSetupError'):
                QtFastStartSetupError = qtfaststart.exceptions.FastStartSetupError
                print("  Using qtfaststart.exceptions.FastStartSetupError")
            if hasattr(qtfaststart.exceptions, 'MalformedFileError'):
                QtMalformedFileError = qtfaststart.exceptions.MalformedFileError
                print("  Using qtfaststart.exceptions.MalformedFileError")
            if hasattr(qtfaststart.exceptions, 'UnsupportedFormatError'):
                QtUnsupportedFormatError = qtfaststart.exceptions.UnsupportedFormatError
                print("  Using qtfaststart.exceptions.UnsupportedFormatError")
        else:
            print("QTFASTSTART WARNING: 'qtfaststart.exceptions' module not found. Using generic error handling for specific qtfaststart errors.")

    except ImportError as e_import:
        print(f"QTFASTSTART ERROR: Import failed for 'qtfaststart' package or its 'processor'/'exceptions' submodules from '{libs_dir}': {e_import}")
        sys.path = original_sys_path
        print(f"QTFASTSTART: Restored sys.path after import error.")
        return False
    except Exception as e_generic_import:
        print(f"QTFASTSTART ERROR: A generic error occurred during the import phase of qtfaststart: {e_generic_import}")
        sys.path = original_sys_path
        print(f"QTFASTSTART: Restored sys.path after generic import error.")
        return False

    success = False
    try:
        if not qt_processor_module:
            print("QTFASTSTART ERROR: qtfaststart.processor module not loaded, cannot process.")
            return False 

        print(f"QTFASTSTART: Calling qt_processor_module.process('{input_path_str}', '{output_path_str}')")
        qt_processor_module.process(input_path_str, output_path_str)

        if os.path.exists(output_path_str) and os.path.getsize(output_path_str) > 0:
            print(f"QTFASTSTART: Success. Fast start video created: {output_path_str}")
            success = True
        else:
            print(f"QTFASTSTART ERROR: qtfaststart.process seemed to complete, but output file '{output_path_str}' not found or is empty.")
            success = False

    except QtFastStartSetupError as e_setup:
        print(f"QTFASTSTART ERROR (Setup): {e_setup}")
        success = False
    except QtMalformedFileError as e_malformed:
        print(f"QTFASTSTART ERROR (Malformed File): {e_malformed}")
        success = False
    except QtUnsupportedFormatError as e_unsupported:
        print(f"QTFASTSTART ERROR (Unsupported Format): {e_unsupported}")
        success = False
    except FileNotFoundError as e_fnf: 
        print(f"QTFASTSTART ERROR (File Not Found during process): {e_fnf}")
        success = False
    except Exception as e_runtime: 
        print(f"QTFASTSTART ERROR: An unexpected error occurred during qtfaststart.process execution: {e_runtime}")
        success = False
    finally:
        sys.path = original_sys_path
        print(f"QTFASTSTART: Restored sys.path after processing attempt.")

    return success


# --- Application Handlers ---
@persistent
def on_render_init_faststart(scene, depsgraph=None):
    global _render_job_cancelled_by_addon
    print("Fast Start (render_init): Handler invoked.")
    _render_job_cancelled_by_addon = False 
    
    addon_settings = scene.fast_start_settings_prop 
    if not addon_settings or not addon_settings.use_faststart_prop:
        print("Fast Start (render_init): Feature not enabled. Skipping.")
        return

    if scene.render.image_settings.file_format != 'FFMPEG' or \
       scene.render.ffmpeg.format not in {'MPEG4', 'QUICKTIME'}:
        print("Fast Start (render_init): Not FFMPEG MP4/MOV output. Skipping.")
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
    else:
        resolved_filepath_setting = bpy.path.abspath(original_filepath_setting)
        if os.path.isdir(resolved_filepath_setting):
            print(f"Fast Start (render_init): Output path setting '{original_filepath_setting}' is a directory. Addon will attempt to find frame-range file post-render.")
        else:
            output_dir_part = os.path.dirname(resolved_filepath_setting)
            base_name_part = os.path.basename(resolved_filepath_setting)
            filename_component, ext_from_setting = os.path.splitext(base_name_part)

            if os.path.isdir(output_dir_part) and not os.path.isdir(resolved_filepath_setting):
                if not ext_from_setting: 
                    if '#' in filename_component:
                        print(f"Fast Start (render_init): Path '{original_filepath_setting}' (filename with placeholders, no ext). Post-render will use last '#' group for frame numbers.")
                    else:
                        print(f"Fast Start (render_init): Path '{original_filepath_setting}' (filename, no ext). Post-render will use default padding for frame numbers.")
                elif '#' in filename_component : 
                     print(f"Fast Start (render_init): Path '{original_filepath_setting}' (filename with placeholders and ext). Post-render will first check literal, then process last '#' group or strip all '#'.")
                else: 
                    print(f"Fast Start (render_init): Path '{original_filepath_setting}' (full filename with ext). Post-render will use this pattern.")
            else: 
                 print(f"Fast Start (render_init): Path '{original_filepath_setting}' (filename pattern, possibly in blend file dir). Post-render will process accordingly.")
    print("Fast Start (render_init): Handler finished.")


@persistent
def check_output_path_pre_render_faststart(scene, depsgraph=None):
    global _render_job_cancelled_by_addon
    if _render_job_cancelled_by_addon: 
        raise RuntimeError("Render job previously cancelled by Fast Start extension due to empty output path setting.")

@persistent
def post_render_faststart_handler(scene, depsgraph=None):
    global _render_job_cancelled_by_addon
    
    if _render_job_cancelled_by_addon:
        print("Fast Start (post_render): Skipping processing due to prior cancellation by addon."); return

    addon_settings = scene.fast_start_settings_prop 
    if not addon_settings or not addon_settings.use_faststart_prop: return 

    if scene.render.image_settings.file_format != 'FFMPEG' or \
       scene.render.ffmpeg.format not in {'MPEG4', 'QUICKTIME'}:
        return 

    print(f"Fast Start (post_render): Handler invoked. Will use bundled qtfaststart.")

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
    # --- File Detection Strategies (Copied from your original, should be fine) ---
    if not path_is_dir_itself and '#' in setting_basename and setting_ext_part:
        print(f"Strategy 1: Checking for literal match for '{abs_filepath_setting}'")
        if os.path.exists(abs_filepath_setting) and not os.path.isdir(abs_filepath_setting):
            original_rendered_file = abs_filepath_setting
            print(f"  Found literal match: '{original_rendered_file}'")

    if not original_rendered_file and not path_is_dir_itself and '#' in setting_filename_part:
        print(f"Strategy 2: Processing placeholders in filename part '{setting_filename_part}' from setting '{original_filepath_setting}'")
        last_hash_match = None
        for match in re.finditer(r'#+', setting_filename_part): last_hash_match = match
        if last_hash_match:
            num_hashes = len(last_hash_match.group(0))
            prefix = setting_filename_part[:last_hash_match.start()]
            suffix = setting_filename_part[last_hash_match.end():]
            print(f"  Last hash group: Prefix='{prefix}', Suffix='{suffix}', Hashes={num_hashes}")
            potential_filename_w_ext = _construct_video_filename(prefix, suffix, start_frame, end_frame, num_hashes, expected_ext)
            potential_file_path = os.path.join(setting_output_dir, potential_filename_w_ext)
            print(f"  Attempting to find: '{potential_file_path}'")
            if os.path.exists(potential_file_path) and not os.path.isdir(potential_file_path):
                original_rendered_file = potential_file_path
        else:
            print(f"  Warning: Hashes reported in '{setting_filename_part}' but regex found no match for last group.")

    if not original_rendered_file and not path_is_dir_itself and not setting_ext_part and '#' not in setting_filename_part:
        print(f"Strategy 3: Setting '{original_filepath_setting}' is filename without extension, no placeholders.")
        filename_prefix = setting_filename_part; default_padding = 4
        if start_frame == end_frame:
            potential_filename_w_ext_frame = _construct_video_filename(filename_prefix, "", start_frame, end_frame, default_padding, expected_ext)
            potential_file_path_frame = os.path.join(setting_output_dir, potential_filename_w_ext_frame)
            print(f"  Attempting single frame (default padding): '{potential_file_path_frame}'")
            if os.path.exists(potential_file_path_frame) and not os.path.isdir(potential_file_path_frame):
                original_rendered_file = potential_file_path_frame
            else:
                potential_file_path_no_frame = os.path.join(setting_output_dir, filename_prefix + expected_ext)
                print(f"  Attempting single frame (no frame num, prefix only): '{potential_file_path_no_frame}'")
                if os.path.exists(potential_file_path_no_frame) and not os.path.isdir(potential_file_path_no_frame):
                    original_rendered_file = potential_file_path_no_frame
        else:
            potential_filename_w_ext_range = _construct_video_filename(filename_prefix, "", start_frame, end_frame, default_padding, expected_ext)
            potential_file_path_range = os.path.join(setting_output_dir, potential_filename_w_ext_range)
            print(f"  Attempting frame range (default padding): '{potential_file_path_range}'")
            if os.path.exists(potential_file_path_range) and not os.path.isdir(potential_file_path_range):
                original_rendered_file = potential_file_path_range

    if not original_rendered_file and path_is_dir_itself:
        print(f"Strategy 4: Setting '{original_filepath_setting}' is a directory.")
        actual_output_dir = abs_filepath_setting; default_padding = 4
        if start_frame == end_frame:
            potential_filename_w_ext_frame = _construct_video_filename("", "", start_frame, end_frame, default_padding, expected_ext)
            potential_file_path_frame = os.path.join(actual_output_dir, potential_filename_w_ext_frame)
            print(f"  Attempting single frame (frame number only): '{potential_file_path_frame}'")
            if os.path.exists(potential_file_path_frame) and not os.path.isdir(potential_file_path_frame):
                original_rendered_file = potential_file_path_frame
            else:
                dir_basename_as_filename_stem = os.path.basename(actual_output_dir.rstrip(os.sep))
                if dir_basename_as_filename_stem:
                    potential_file_path_dir_name = os.path.join(actual_output_dir, dir_basename_as_filename_stem + expected_ext)
                    print(f"  Attempting single frame (directory name as base): '{potential_file_path_dir_name}'")
                    if os.path.exists(potential_file_path_dir_name) and not os.path.isdir(potential_file_path_dir_name):
                        original_rendered_file = potential_file_path_dir_name
        else:
            potential_filename_w_ext_range = _construct_video_filename("", "", start_frame, end_frame, default_padding, expected_ext)
            potential_file_path_range = os.path.join(actual_output_dir, potential_filename_w_ext_range)
            print(f"  Attempting frame range (frame numbers only): '{potential_file_path_range}'")
            if os.path.exists(potential_file_path_range) and not os.path.isdir(potential_file_path_range):
                original_rendered_file = potential_file_path_range

    if not original_rendered_file and not path_is_dir_itself:
        print(f"Strategy 5: Path setting '{original_filepath_setting}' treated as general file pattern (stripping all '#').")
        filename_all_hashes_stripped = re.sub(r'#+', '', setting_filename_part)
        final_ext_for_stripped = setting_ext_part if setting_ext_part and setting_ext_part.startswith('.') else expected_ext
        potential_filename_w_ext = filename_all_hashes_stripped + final_ext_for_stripped
        potential_file_path = os.path.join(setting_output_dir, potential_filename_w_ext)
        print(f"  Attempting file (all '#' stripped from name, ext corrected): '{potential_file_path}'")
        if os.path.exists(potential_file_path) and not os.path.isdir(potential_file_path):
            original_rendered_file = potential_file_path
    # --- End File Detection ---

    if not original_rendered_file:
        print(f"Fast Start (post_render) ERROR: Could not find the actual rendered file using any detection method.")
        print(f"  Original setting: '{original_filepath_setting}'")
        print("  Skipping Fast Start processing.")
        return
             
    if os.path.isdir(original_rendered_file): 
        print(f"Fast Start (post_render) ERROR: Resolved path '{original_rendered_file}' is a directory. This should not happen. Skipping."); return

    print(f"Fast Start (post_render): Original rendered file identified as: {original_rendered_file}")

    try:
        source_dir = os.path.dirname(original_rendered_file)
        source_basename_full = os.path.basename(original_rendered_file)
        source_name_part, source_ext_part = os.path.splitext(source_basename_full)

        if not source_ext_part: source_ext_part = expected_ext 

        fast_start_name_part = f"{source_name_part}-faststart"
        fast_start_output_path = os.path.join(source_dir, fast_start_name_part + source_ext_part)

        print(f"Fast Start (post_render): Processing '{original_rendered_file}' to new file '{fast_start_output_path}' using qtfaststart")
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
    FastStartSettingsGroup, 
    # REMOVED: WarnMissingFilenameOperator,
)

def register():
    global _active_handlers_info
    _active_handlers_info.clear() 

    package_name = __package__ if __package__ else "blender_faststart" 
    print(f"Registering Fast Start extension ({package_name})...")

    for cls in classes_to_register:
        try:
            bpy.utils.register_class(cls)
        except ValueError: 
            print(f"  Class {cls.__name__} already registered or error. Attempting unregister and re-register.")
            try: bpy.utils.unregister_class(cls)
            except Exception as e_unreg_cls: print(f"    Could not unregister {cls.__name__}: {e_unreg_cls}")
            bpy.utils.register_class(cls) 
    print(f"  Registered classes.")

    try:
        bpy.types.Scene.fast_start_settings_prop = bpy.props.PointerProperty(type=FastStartSettingsGroup) 
        print("  SUCCESS: PropertyGroup 'fast_start_settings_prop' added to Scene.")
    except (TypeError, AttributeError, RuntimeError) as e_pg:
        print(f"  INFO/ERROR with PropertyGroup 'fast_start_settings_prop': {e_pg}. Might already exist.")
        current_prop = getattr(bpy.types.Scene, 'fast_start_settings_prop', None)
        if isinstance(current_prop, bpy.props.PointerProperty) and \
           current_prop.keywords.get('type') == FastStartSettingsGroup: 
            print("    PropertyGroup already exists and is of the correct type.")
        else:
            print("    PropertyGroup issue is not a simple re-registration. Manual check might be needed.")
        pass 

    try:
        already_appended = False
        if hasattr(bpy.types.RENDER_PT_encoding, '_dyn_ui_initialize'): 
            if draw_faststart_checkbox_ui in bpy.types.RENDER_PT_encoding._dyn_ui_initialize():
                already_appended = True
        
        if not already_appended:
            bpy.types.RENDER_PT_encoding.append(draw_faststart_checkbox_ui)
            print("  Appended checkbox UI to RENDER_PT_encoding panel.")
        else:
            print("  Checkbox UI already appended to RENDER_PT_encoding panel.")
    except AttributeError:
        print("  WARNING: RENDER_PT_encoding panel not found. UI not added (might be normal in headless mode).")
    except Exception as e_ui: 
        print(f"  Error appending checkbox UI: {e_ui}")

    handler_definitions = [
        ("render_init", bpy.app.handlers.render_init, on_render_init_faststart),
        ("render_pre", bpy.app.handlers.render_pre, check_output_path_pre_render_faststart),
        ("render_complete", bpy.app.handlers.render_complete, post_render_faststart_handler)
    ]

    for handler_name_str, handler_list_obj, func_ref in handler_definitions:
        if func_ref not in handler_list_obj:
            handler_list_obj.append(func_ref)
            print(f"  Appended handler: {func_ref.__name__} to bpy.app.handlers.{handler_name_str}.")
        else:
            print(f"  Handler {func_ref.__name__} already in bpy.app.handlers.{handler_name_str}.")
        _active_handlers_info.append((handler_name_str, handler_list_obj, func_ref)) 
        
    print(f"Fast Start Extension ({package_name}) Registration COMPLETE.")

def unregister():
    global _render_job_cancelled_by_addon, _active_handlers_info
    
    package_name = __package__ if __package__ else "blender_faststart" 
    print(f"Unregistering Fast Start Extension ({package_name})...")

    for handler_name_str, handler_list_obj, func_ref in reversed(_active_handlers_info): 
        if func_ref in handler_list_obj:
            try:
                handler_list_obj.remove(func_ref)
                print(f"  Removed handler: {func_ref.__name__} from bpy.app.handlers.{handler_name_str}.")
            except Exception as e_handler_rem:
                print(f"  ERROR removing handler {func_ref.__name__} from {handler_name_str}: {e_handler_rem}")
    _active_handlers_info.clear()

    try:
        panel_draw_funcs = getattr(bpy.types.RENDER_PT_encoding, "_dyn_ui_initialize", lambda: [])()
        if draw_faststart_checkbox_ui in panel_draw_funcs:
            bpy.types.RENDER_PT_encoding.remove(draw_faststart_checkbox_ui)
            print("  Checkbox UI removed from RENDER_PT_encoding panel.")
        else: 
            try:
                bpy.types.RENDER_PT_encoding.remove(draw_faststart_checkbox_ui)
                print("  Checkbox UI removed from RENDER_PT_encoding panel (fallback attempt).")
            except: pass 
    except Exception as e_ui_rem:
        print(f"  Error removing checkbox UI: {e_ui_rem}")
        pass

    try:
        if hasattr(bpy.types.Scene, 'fast_start_settings_prop'):
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
    print(f"Fast Start Extension ({package_name}) Unregistration COMPLETE.")