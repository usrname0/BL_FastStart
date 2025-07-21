# filename: extension_logic.py
# Main logic for the Fast Start Blender Extension, using bundled qtfaststart.

import bpy
import os
import re
from bpy.props import BoolProperty, StringProperty
from bpy.types import PropertyGroup, AddonPreferences
from bpy.app.handlers import persistent

# Imports for bundled qtfaststart using relative import
from pathlib import Path
from .qtfaststart_lib import process as qtfaststart_process
from .qtfaststart_lib import FastStartSetupError, MalformedFileError, UnsupportedFormatError, FastStartException

# --- Module-level globals ---
_render_job_cancelled_by_addon = False
_active_handlers_info = []

# --- Add-on Preferences ---
class FastStartAddonPreferences(AddonPreferences):
    bl_idname = __package__

    faststart_suffix_prop: StringProperty(
        name="Fast Start Suffix",
        description="Suffix for the fast start file (e.g., '-faststart', '_optimized'). Applied globally. Invalid characters will be replaced. If blank, defaults to '-faststart'.",
        default="-faststart",
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
    addon_settings = scene.fast_start_settings_prop

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
        if addon_settings:
            row = layout.row(align=True)
            if hasattr(addon_settings, "use_faststart_prop"):
                checkbox_text = "Fast Start (moov atom to front)"
                can_enable_faststart = True

                if multiview_enabled:
                    can_enable_faststart = False
                    checkbox_text = "Fast Start (disabled due to Stereoscopy/Multiview)"
                elif autosplit_enabled:
                    can_enable_faststart = False
                    checkbox_text = "Fast Start (disabled due to Autosplit)"

                row.enabled = can_enable_faststart
                row.prop(addon_settings, "use_faststart_prop", text=checkbox_text)
            else:
                row.label(text="Fast Start Prop Missing!", icon='ERROR')

# --- Helper Function for Filename Construction ---
def _construct_video_filename(base_name_part, suffix_after_frame_numbers, start_frame, end_frame, frame_padding_digits, output_extension_with_dot):
    """
    Constructs a filename string based on Blender's naming patterns.
    If frame_padding_digits > 0, always uses start-end frame format (e.g., 0001-0001 for single frame).
    """
    frame_str_component = ""

    if frame_padding_digits > 0:
        start_frame_str = f"{start_frame:0{frame_padding_digits}d}"
        end_frame_str = f"{end_frame:0{frame_padding_digits}d}"
        frame_str_component = f"{start_frame_str}-{end_frame_str}"

    return f"{base_name_part}{frame_str_component}{suffix_after_frame_numbers}{output_extension_with_dot}"

# --- QTFASTSTART Processing Logic ---
def run_qtfaststart_processing(input_path_str, output_path_str):
    """Process video file with qtfaststart, creating fast-start version."""
    if not os.path.exists(input_path_str):
        print(f"Fast Start ERROR: Input file not found: {input_path_str}")
        return False
    
    if os.path.isdir(input_path_str):
        print(f"Fast Start ERROR: Input path is a directory: {input_path_str}")
        return False

    # Create output directory if needed
    output_dir = os.path.dirname(output_path_str)
    if output_dir and not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir, exist_ok=True)
        except Exception as e:
            print(f"Fast Start ERROR: Could not create output directory '{output_dir}': {e}")
            return False

    try:
        qtfaststart_process(input_path_str, output_path_str)
        
        if os.path.exists(output_path_str) and os.path.getsize(output_path_str) > 0:
            print(f"Fast Start: Created optimized file: {os.path.basename(output_path_str)}")
            return True
        else:
            print(f"Fast Start ERROR: Output file not created or empty")
            return False
            
    except FastStartSetupError:
        print("Fast Start: File already optimized, skipping")
        return False
    except (MalformedFileError, UnsupportedFormatError, FileNotFoundError) as e:
        print(f"Fast Start ERROR: {e}")
        return False
    except Exception as e:
        print(f"Fast Start ERROR: Unexpected error during processing: {e}")
        return False

# --- Application Handlers ---
@persistent
def on_render_init_faststart(scene, depsgraph=None):
    """Called when render job is initialized - validate settings."""
    global _render_job_cancelled_by_addon
    _render_job_cancelled_by_addon = False

    addon_settings = scene.fast_start_settings_prop
    if not addon_settings or not addon_settings.use_faststart_prop:
        return

    # Skip if not FFMPEG MP4/MOV
    if not (scene.render.image_settings.file_format == 'FFMPEG' and \
            scene.render.ffmpeg.format in {'MPEG4', 'QUICKTIME'}):
        return

    # Skip if incompatible features enabled
    if scene.render.use_multiview or \
       (hasattr(scene.render.ffmpeg, "use_autosplit") and scene.render.ffmpeg.use_autosplit):
        return

    # Validate output path
    if not scene.render.filepath.strip():
        _render_job_cancelled_by_addon = True
        error_message = ("Fast Start: Output path is empty. Please specify an output path in "
                         "Properties > Output Properties > Output.")
        print(f"ERROR - {error_message}")
        raise RuntimeError(error_message)

@persistent
def check_output_path_pre_render_faststart(scene, depsgraph=None):
    """Pre-render check for cancellation flag."""
    if _render_job_cancelled_by_addon:
        raise RuntimeError("Render job cancelled by Fast Start extension due to empty output path.")

@persistent
def post_render_faststart_handler(scene, depsgraph=None):
    """Main post-render handler - creates fast-start version of rendered file."""
    global _render_job_cancelled_by_addon
    
    if _render_job_cancelled_by_addon:
        return

    # Check if Fast Start is enabled and applicable
    scene_specific_settings = scene.fast_start_settings_prop
    if not scene_specific_settings or not scene_specific_settings.use_faststart_prop:
        return
        
    if not (scene.render.image_settings.file_format == 'FFMPEG' and \
            scene.render.ffmpeg.format in {'MPEG4', 'QUICKTIME'}):
        return

    # Skip if incompatible features enabled
    if scene.render.use_multiview or \
       (hasattr(scene.render.ffmpeg, "use_autosplit") and scene.render.ffmpeg.use_autosplit):
        return

    # Get and validate suffix
    addon_package_name = __package__ or "blender_faststart"
    addon_prefs = None
    try:
        addon_prefs = bpy.context.preferences.addons[addon_package_name].preferences
    except KeyError:
        print(f"Fast Start WARNING: Could not retrieve add-on preferences")

    default_suffix_value = "-faststart"
    custom_suffix = default_suffix_value
    if addon_prefs and hasattr(addon_prefs, 'faststart_suffix_prop'):
        user_suffix = addon_prefs.faststart_suffix_prop.strip() if addon_prefs.faststart_suffix_prop else ""
        if user_suffix:
            custom_suffix = user_suffix

    # Sanitize suffix
    suffix_before_sanitize = custom_suffix
    custom_suffix = custom_suffix.replace("..", "")
    custom_suffix = re.sub(r'[<>:"/\\|?*]', '_', custom_suffix)
    custom_suffix = re.sub(r'[\x00-\x1F]', '', custom_suffix)
    
    if not custom_suffix.strip():
        custom_suffix = default_suffix_value
    elif custom_suffix != suffix_before_sanitize:
        print(f"Fast Start: Suffix sanitized from '{suffix_before_sanitize}' to '{custom_suffix}'")

    # Parse file paths and settings
    original_filepath_setting_raw = scene.render.filepath
    abs_filepath_setting = bpy.path.abspath(original_filepath_setting_raw)
    container_type = scene.render.ffmpeg.format
    start_frame = scene.frame_start
    end_frame = scene.frame_end

    # Determine output directory and user basename
    if os.path.isdir(abs_filepath_setting):
        blender_output_dir = abs_filepath_setting
        user_setting_basename = ""
    else:
        blender_output_dir = os.path.dirname(abs_filepath_setting)
        user_setting_basename = os.path.basename(abs_filepath_setting)

    # Parse filename construction parameters based on Blender's complex naming logic
    base_for_construction, frame_padding_final, suffix_for_constructor, final_extension_for_constructor = \
        _parse_blender_filename_logic(user_setting_basename, container_type, scene.render.use_file_extension)

    # Predict rendered filename
    predicted_blender_filename = _construct_video_filename(
        base_for_construction,
        suffix_for_constructor,
        start_frame,
        end_frame,
        frame_padding_final,
        final_extension_for_constructor
    )

    potential_final_path = os.path.join(blender_output_dir, predicted_blender_filename)

    # Find the actual rendered file
    original_rendered_file = None
    if os.path.exists(potential_final_path) and not os.path.isdir(potential_final_path):
        original_rendered_file = potential_final_path
    else:
        # Fallback for directory output
        if os.path.isdir(abs_filepath_setting):
            alt_filename = _construct_video_filename("", "", start_frame, end_frame, 4, final_extension_for_constructor)
            alt_path = os.path.join(blender_output_dir, alt_filename)
            if os.path.exists(alt_path) and not os.path.isdir(alt_path):
                original_rendered_file = alt_path

    if not original_rendered_file:
        print(f"Fast Start ERROR: Could not find rendered file. Expected: {potential_final_path}")
        return

    if os.path.isdir(original_rendered_file):
        print(f"Fast Start ERROR: Resolved path is a directory: {original_rendered_file}")
        return

    # Create fast-start version
    try:
        source_dir, source_basename = os.path.split(original_rendered_file)
        source_name, source_ext = os.path.splitext(source_basename)
        fast_start_name = f"{source_name}{custom_suffix}"
        fast_start_output_path = os.path.join(source_dir, fast_start_name + source_ext)
        
        success = run_qtfaststart_processing(original_rendered_file, fast_start_output_path)
        
        if not success and os.path.exists(fast_start_output_path) and os.path.getsize(fast_start_output_path) == 0:
            try:
                os.remove(fast_start_output_path)
            except:
                pass
                
    except Exception as e:
        print(f"Fast Start ERROR: {e}")

def _parse_blender_filename_logic(user_setting_basename, container_type, use_file_extension):
    """
    Parse Blender's complex filename logic to determine construction parameters.
    Returns: (base_for_construction, frame_padding_final, suffix_for_constructor, final_extension_for_constructor)
    """
    # Find rightmost hash sequence in full basename
    text_before_rightmost_hashes = user_setting_basename
    padding_from_rightmost_hashes = 0
    text_after_rightmost_hashes = ""

    last_hash_match = None
    for match in re.finditer(r'(#+)', user_setting_basename):
        last_hash_match = match

    if last_hash_match:
        text_before_rightmost_hashes = user_setting_basename[:last_hash_match.start()]
        padding_from_rightmost_hashes = len(last_hash_match.group(1))
        text_after_rightmost_hashes = user_setting_basename[last_hash_match.end():]

    if use_file_extension:  # "File Extension" CHECKED
        actual_correct_ext_lower = (".mp4" if container_type == 'MPEG4' else ".mov")
        final_extension_for_constructor = actual_correct_ext_lower

        user_input_name_part, user_input_ext_part = os.path.splitext(user_setting_basename)

        # Rule 2b: "NAME###.CORRECT_EXT" -> "NAME###.correct_ext"
        if user_input_ext_part.lower() == actual_correct_ext_lower and re.search(r'#+', user_input_name_part):
            return user_input_name_part, 0, "", final_extension_for_constructor

        # Rule 2a: "NAME.CORRECT_EXT" -> "NAME.correct_ext"
        elif user_input_ext_part.lower() == actual_correct_ext_lower and not re.search(r'#+', user_input_name_part):
            return user_input_name_part, 0, "", final_extension_for_constructor

        # Rule 3: Hashes present
        elif padding_from_rightmost_hashes > 0:
            return text_before_rightmost_hashes, padding_from_rightmost_hashes, text_after_rightmost_hashes, final_extension_for_constructor

        # Rule 4: Default frame append
        else:
            return user_setting_basename, 4, "", final_extension_for_constructor

    else:  # "File Extension" UNCHECKED
        if padding_from_rightmost_hashes > 0:
            return text_before_rightmost_hashes, padding_from_rightmost_hashes, "", text_after_rightmost_hashes
        else:
            base_for_construction, final_extension_for_constructor = os.path.splitext(user_setting_basename)
            if not user_setting_basename.endswith(final_extension_for_constructor) and final_extension_for_constructor == "":
                base_for_construction = user_setting_basename
            return base_for_construction, 0, "", final_extension_for_constructor

# --- Registration ---
classes_to_register = (
    FastStartAddonPreferences,
    FastStartSettingsGroup,
)

def register():
    """Register the addon classes and handlers."""
    global _active_handlers_info
    _active_handlers_info.clear()
    
    package_name = __package__ or Path(__file__).stem
    FastStartAddonPreferences.bl_idname = package_name
    
    # Register classes
    for cls in classes_to_register:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            # Already registered, try to re-register
            try:
                bpy.utils.unregister_class(cls)
                bpy.utils.register_class(cls)
            except Exception as e:
                print(f"Fast Start: Could not re-register {cls.__name__}: {e}")
        except Exception as e:
            print(f"Fast Start: Error registering {cls.__name__}: {e}")

    # Add property group to Scene
    try:
        bpy.types.Scene.fast_start_settings_prop = bpy.props.PointerProperty(type=FastStartSettingsGroup)
    except Exception as e:
        print(f"Fast Start: Error adding PropertyGroup: {e}")

    # Add UI to render panel
    try:
        if hasattr(bpy.types, "RENDER_PT_encoding"):
            try:
                bpy.types.RENDER_PT_encoding.remove(draw_faststart_checkbox_ui)
            except:
                pass
            bpy.types.RENDER_PT_encoding.append(draw_faststart_checkbox_ui)
    except Exception as e:
        print(f"Fast Start: Error adding UI: {e}")

    # Register handlers
    handler_definitions = [
        ("render_init", bpy.app.handlers.render_init, on_render_init_faststart),
        ("render_pre", bpy.app.handlers.render_pre, check_output_path_pre_render_faststart),
        ("render_complete", bpy.app.handlers.render_complete, post_render_faststart_handler)
    ]
    
    for name, handler_list, func in handler_definitions:
        if func not in handler_list:
            try:
                handler_list.append(func)
            except Exception as e:
                print(f"Fast Start: Error adding handler {func.__name__}: {e}")
        _active_handlers_info.append((name, handler_list, func))

def unregister():
    """Unregister the addon classes and handlers."""
    global _render_job_cancelled_by_addon, _active_handlers_info
    
    package_name = __package__ or Path(__file__).stem
    
    # Remove handlers
    for name, handler_list, func in reversed(_active_handlers_info):
        if func in handler_list:
            try:
                handler_list.remove(func)
            except Exception as e:
                print(f"Fast Start: Error removing handler {func.__name__}: {e}")
    _active_handlers_info.clear()

    # Remove UI
    try:
        if hasattr(bpy.types, "RENDER_PT_encoding"):
            bpy.types.RENDER_PT_encoding.remove(draw_faststart_checkbox_ui)
    except:
        pass

    # Remove property group
    if hasattr(bpy.types.Scene, 'fast_start_settings_prop'):
        try:
            del bpy.types.Scene.fast_start_settings_prop
        except Exception as e:
            print(f"Fast Start: Error removing PropertyGroup: {e}")

    # Unregister classes
    for cls in reversed(classes_to_register):
        try:
            bpy.utils.unregister_class(cls)
        except:
            pass

    _render_job_cancelled_by_addon = False