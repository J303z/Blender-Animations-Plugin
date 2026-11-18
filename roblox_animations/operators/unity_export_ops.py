"""
Unity FBX export operators.

The exporter delegates animation sampling to Blender's FBX exporter. This lets
Blender evaluate the selected armature's dependency-graph pose (including
constraints driven by other objects) without destructively baking or clearing
constraints on the user's source rig.
"""

import bpy
from bpy.types import Operator
from bpy.props import StringProperty
from bpy_extras.io_utils import ExportHelper


class OBJECT_OT_ExportUnityFBX(Operator, ExportHelper):
    """Export the target armature and its evaluated animation as an FBX for Unity"""

    bl_idname = "object.rbxanims_export_unity_fbx"
    bl_label = "Export for Unity (.fbx)"
    bl_description = (
        "Export the target armature's evaluated animation to an animation-only "
        "FBX. The source rig and its constraints are left unchanged."
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
        settings = getattr(context.scene, "rbx_anim_settings", None)
        armature_name = getattr(settings, "rbx_anim_armature", "") if settings else ""
        armature = bpy.data.objects.get(armature_name) if armature_name else None
        return armature is not None and armature.type == "ARMATURE"

    def execute(self, context):
        settings = getattr(context.scene, "rbx_anim_settings", None)
        armature_name = getattr(settings, "rbx_anim_armature", "") if settings else ""
        armature = bpy.data.objects.get(armature_name) if armature_name else None

        if armature is None or armature.type != "ARMATURE":
            self.report({"ERROR"}, "Choose a valid target armature first.")
            return {"CANCELLED"}

        if not self.filepath:
            self.report({"ERROR"}, "Choose an FBX output path.")
            return {"CANCELLED"}

        view_layer = context.view_layer
        scene = context.scene
        previous_active = view_layer.objects.active
        previous_selection = list(context.selected_objects)
        previous_mode = armature.mode
        previous_frame = scene.frame_current
        previous_subframe = scene.frame_subframe

        try:
            # FBX export requires Object Mode. Do not apply transforms, clear
            # constraints, alter actions, or change the source rig's hierarchy.
            if context.object and context.object.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")

            bpy.ops.object.select_all(action="DESELECT")
            armature.select_set(True)
            view_layer.objects.active = armature

            bpy.ops.export_scene.fbx(
                filepath=self.filepath,
                check_existing=False,
                use_selection=True,
                object_types={"ARMATURE"},
                apply_unit_scale=True,
                use_space_transform=True,
                bake_anim=True,
                bake_anim_use_all_bones=True,
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
        except Exception as exc:
            self.report({"ERROR"}, f"Unity FBX export failed: {exc}")
            return {"CANCELLED"}
        finally:
            # Restore the scene's selection, active object, frame and mode.
            try:
                if context.object and context.object.mode != "OBJECT":
                    bpy.ops.object.mode_set(mode="OBJECT")
                bpy.ops.object.select_all(action="DESELECT")
                for obj in previous_selection:
                    if obj.name in bpy.data.objects:
                        obj.select_set(True)
                if previous_active and previous_active.name in bpy.data.objects:
                    view_layer.objects.active = previous_active
                scene.frame_set(previous_frame, subframe=previous_subframe)
                if previous_mode != "OBJECT" and armature.name in bpy.data.objects:
                    view_layer.objects.active = armature
                    armature.select_set(True)
                    bpy.ops.object.mode_set(mode=previous_mode)
                    if previous_active and previous_active.name in bpy.data.objects:
                        view_layer.objects.active = previous_active
            except Exception:
                # Export success/failure should not be masked by a UI-state
                # restoration issue; Blender will still retain the source data.
                pass

        self.report(
            {"INFO"},
            "Exported animation-only FBX. Verify bone mapping and motion in Unity.",
        )
        return {"FINISHED"}
