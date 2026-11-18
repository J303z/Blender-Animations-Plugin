"""Unity FBX export operators.

The exporter uses Blender's FBX global-scene animation bake. Blender evaluates
the dependency graph at each sampled frame, so a selected export armature can
receive animation from constraints driven by a separate control rig. Only the
export armature is written to the FBX; the control rig remains in the scene
for evaluation and is not included in the exported hierarchy.
"""

import os
import bpy
from bpy.types import Operator
from bpy.props import StringProperty
from bpy_extras.io_utils import ExportHelper


_R6_BONE_NAMES = {
    "HumanoidRootPart", "Torso", "Right Arm", "Left Arm",
    "Right Leg", "Left Leg", "Head",
}

def _sample_evaluated_motion(context, armature, scene):
    """Check whether the evaluated target pose changes across the scene range."""
    start, end = int(scene.frame_start), int(scene.frame_end)
    if end <= start:
        return False, "The scene frame range contains only one frame."
    frames = sorted({start, round(start + (end - start) * 0.25),
                     round(start + (end - start) * 0.5),
                     round(start + (end - start) * 0.75), end})
    depsgraph = context.evaluated_depsgraph_get()
    reference = None
    largest_delta = 0.0
    for frame in frames:
        scene.frame_set(frame)
        context.view_layer.update()
        evaluated = armature.evaluated_get(depsgraph)
        current = {pb.name: pb.matrix.copy() for pb in evaluated.pose.bones}
        if reference is None:
            reference = current
            continue
        for name, matrix in current.items():
            original = reference.get(name)
            if original is None:
                continue
            delta = max(abs(matrix[r][col] - original[r][col])
                        for r in range(4) for col in range(4))
            largest_delta = max(largest_delta, delta)
    return largest_delta > 1e-5, f'Maximum sampled pose-matrix difference: {largest_delta:.6g}'

class OBJECT_OT_ExportUnityFBX(Operator, ExportHelper):
    """Export the target armature's evaluated animation as a Unity FBX"""

    bl_idname = "object.rbxanims_export_unity_fbx"
    bl_label = "Export for Unity (.fbx)"
    bl_description = (
        "Export the target armature's evaluated animation to an animation-only "
        "FBX. Constraint drivers remain in the scene but are not exported."
    )
    bl_options = {"REGISTER"}

    filename_ext = ".fbx"
    filter_glob: StringProperty(
        default="*.fbx",
        options={"HIDDEN"},
        maxlen=255,
    )

    @classmethod
    def poll(cls, context):
        scene = getattr(context, "scene", None)
        settings = getattr(scene, "rbx_anim_settings", None) if scene else None
        armature_name = getattr(settings, "rbx_anim_armature", "") if settings else ""
        armature = bpy.data.objects.get(armature_name) if armature_name else None
        return armature is not None and armature.type == "ARMATURE"

    def execute(self, context):
        scene = context.scene
        settings = getattr(scene, "rbx_anim_settings", None)
        armature_name = getattr(settings, "rbx_anim_armature", "") if settings else ""
        armature = bpy.data.objects.get(armature_name) if armature_name else None

        if armature is None or armature.type != "ARMATURE":
            self.report({"ERROR"}, "Choose a valid target armature first.")
            return {"CANCELLED"}

        if not self.filepath:
            self.report({"ERROR"}, "Choose an FBX output path.")
            return {"CANCELLED"}

        if scene.frame_end <= scene.frame_start:
            self.report({"ERROR"}, "The scene frame range must contain at least two frames.")
            return {"CANCELLED"}
        if not armature.data.bones:
            self.report({"ERROR"}, "The target armature has no bones.")
            return {"CANCELLED"}
        actual_bones = {bone.name for bone in armature.data.bones}
        if actual_bones != _R6_BONE_NAMES:
            missing = sorted(_R6_BONE_NAMES - actual_bones)
            extra = sorted(actual_bones - _R6_BONE_NAMES)
            details = []
            if missing: details.append("missing: " + ", ".join(missing))
            if extra: details.append("additional: " + ", ".join(extra))
            self.report({"WARNING"}, "Target differs from the expected seven-bone R6 skeleton (" + "; ".join(details) + "). Export will continue.")

        view_layer = context.view_layer
        if view_layer.objects.get(armature.name) is None:
            self.report(
                {"ERROR"},
                "The target armature is not in the active view layer. Move it into "
                "an included collection before exporting.",
            )
            return {"CANCELLED"}
        if not armature.visible_get(view_layer=view_layer):
            self.report(
                {"ERROR"},
                "The target armature is hidden. Make it visible in the active view layer "
                "before exporting.",
            )
            return {"CANCELLED"}

        try:
            bpy.ops.export_scene.fbx.get_rna_type()
        except (AttributeError, RuntimeError):
            self.report(
                {"ERROR"},
                "Blender's FBX exporter is unavailable. Enable the FBX extension "
                "in Preferences, then try again.",
            )
            return {"CANCELLED"}

        previous_active = view_layer.objects.active
        previous_selection = list(context.selected_objects)
        previous_mode = previous_active.mode if previous_active else "OBJECT"
        previous_frame = scene.frame_current
        previous_subframe = scene.frame_subframe

        try:
            # Check that the constrained export armature actually receives motion.
            has_motion, motion_details = _sample_evaluated_motion(context, armature, scene)
            if not has_motion:
                self.report({"WARNING"}, "No evaluated pose change detected across the scene range. " + motion_details + ". Check constraints and frame range.")
            else:
                print("Unity FBX preflight: evaluated target motion detected. " + motion_details)
            scene.frame_set(previous_frame, subframe=previous_subframe)

            # FBX export requires Object Mode. Exit the mode of the currently
            # active object, not necessarily the selected export armature.
            if previous_active and previous_active.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")

            bpy.ops.object.select_all(action="DESELECT")
            armature.select_set(True)
            view_layer.objects.active = armature

            export_result = bpy.ops.export_scene.fbx(
                filepath=self.filepath,
                check_existing=False,
                use_selection=True,
                object_types={"ARMATURE"},
                apply_unit_scale=True,
                use_space_transform=True,
                bake_anim=True,
                bake_anim_use_all_bones=True,
                # False/False requests Blender's global scene animation stack.
                # This is important: the target pose is sampled over the scene
                # range even when its motion comes from another rig's constraints.
                bake_anim_use_nla_strips=False,
                bake_anim_use_all_actions=False,
                bake_anim_force_startend_keying=True,
                bake_anim_step=1.0,
                bake_anim_simplify_factor=0.0,
                add_leaf_bones=False,
                use_armature_deform_only=False,
                axis_forward="-Z",
                axis_up="Y",
            )
            if "FINISHED" not in export_result:
                self.report({"ERROR"}, "Blender's FBX exporter did not complete the export.")
                return {"CANCELLED"}
            output_path = bpy.path.abspath(self.filepath)
            if not os.path.isfile(output_path):
                self.report({"ERROR"}, "Blender reported success, but the FBX file was not found.")
                return {"CANCELLED"}
            if os.path.getsize(output_path) <= 0:
                self.report({"ERROR"}, "The exported FBX file is empty.")
                return {"CANCELLED"}
        except Exception as exc:
            self.report({"ERROR"}, f"Unity FBX export failed: {exc}")
            return {"CANCELLED"}
        finally:
            # Restore frame, selection, active object, and its original mode.
            # Do not leave the user's source scene in a different interaction mode.
            try:
                scene.frame_set(previous_frame, subframe=previous_subframe)

                active_now = view_layer.objects.active
                if active_now and active_now.mode != "OBJECT":
                    bpy.ops.object.mode_set(mode="OBJECT")

                bpy.ops.object.select_all(action="DESELECT")
                for obj in previous_selection:
                    if view_layer.objects.get(obj.name) is not None:
                        obj.select_set(True)

                if (
                    previous_active
                    and view_layer.objects.get(previous_active.name) is not None
                ):
                    previous_active.select_set(True)
                    view_layer.objects.active = previous_active
                    if previous_mode != "OBJECT":
                        bpy.ops.object.mode_set(mode=previous_mode)
            except Exception as restore_exc:
                print(f"Unity FBX export: could not fully restore Blender context: {restore_exc}")

        self.report(
            {"INFO"},
            "Exported animation-only FBX. Verify bone mapping and motion in Unity.",
        )
        return {"FINISHED"}
