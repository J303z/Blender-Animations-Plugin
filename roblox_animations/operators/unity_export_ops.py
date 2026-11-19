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
from bpy.props import StringProperty, BoolProperty
from mathutils import Matrix
from bpy_extras.io_utils import ExportHelper


_R6_BONE_NAMES = {
    "HumanoidRootPart", "Torso", "Right Arm", "Left Arm",
    "Right Leg", "Left Leg", "Head",
}

_R6_EXPECTED_PARENTS = {
    # Custom R6 hierarchy: the torso bends independently while the
    # legs remain rooted to HumanoidRootPart and do not follow torso pitch.
    "HumanoidRootPart": None,
    "Torso": "HumanoidRootPart",
    "Head": "Torso",
    "Left Arm": "Torso",
    "Right Arm": "Torso",
    "Left Leg": "HumanoidRootPart",
    "Right Leg": "HumanoidRootPart",
}


def _validate_r6_armature(
    armature, label, expected_parents=_R6_EXPECTED_PARENTS
):
    """Validate the seven-bone R6 skeleton and optionally its hierarchy.

    The source and destination skeletons may intentionally have different
    parent structures. The source is sampled in evaluated armature space;
    the destination hierarchy determines how those transforms are rebased.
    Pass expected_parents=None for a source skeleton whose hierarchy is allowed
    to differ. Destination/template skeletons must use the custom Unity layout.
    """
    if armature is None or armature.type != "ARMATURE":
        raise RuntimeError(f"{label} is not a valid armature.")

    actual = {bone.name for bone in armature.data.bones}
    if actual != _R6_BONE_NAMES:
        missing = sorted(_R6_BONE_NAMES - actual)
        extra = sorted(actual - _R6_BONE_NAMES)
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if extra:
            details.append("unexpected: " + ", ".join(extra))
        raise RuntimeError(
            f"{label} must contain exactly the seven R6 bones "
            f"({'; '.join(details)}). Select the seven-bone InternalArmature, "
            "not the R6IK control armature."
        )

    root = armature.data.bones["HumanoidRootPart"]
    if root.parent is not None:
        raise RuntimeError(
            f"{label} must have HumanoidRootPart as its root bone."
        )

    if expected_parents is not None:
        for bone_name, expected_parent in expected_parents.items():
            bone = armature.data.bones[bone_name]
            actual_parent = bone.parent.name if bone.parent else None
            if actual_parent != expected_parent:
                expected_text = expected_parent if expected_parent else "no parent"
                actual_text = actual_parent if actual_parent else "no parent"
                raise RuntimeError(
                    f"{label} hierarchy mismatch for '{bone_name}': "
                    f"expected {expected_text}, got {actual_text}."
                )


def _find_layer_collection_path(layer_collection, target_collection):
    """Return the active view-layer path to a collection, or None."""
    if layer_collection.collection == target_collection:
        return [layer_collection]

    for child in layer_collection.children:
        child_path = _find_layer_collection_path(child, target_collection)
        if child_path is not None:
            return [layer_collection] + child_path

    return None


def _restore_armature_visibility(armature, view_layer, state):
    """Restore object and collection visibility captured for an export."""
    if state is None:
        return

    # Restore object-level visibility while its collection path is still
    # available in the view layer.
    armature.hide_viewport = state["object_hide_viewport"]
    armature.hide_set(state["object_hide_set"], view_layer=view_layer)

    # Restore per-view-layer flags, then the collection-wide viewport flags.
    for layer_collection, was_excluded, was_hidden in reversed(
        state["layer_collections"]
    ):
        layer_collection.exclude = was_excluded
        layer_collection.hide_viewport = was_hidden

    for collection, was_hidden in reversed(state["collections"]):
        collection.hide_viewport = was_hidden

    view_layer.update()


def _temporarily_reveal_armature(armature, view_layer):
    """Temporarily reveal a hidden target and return its restoration state.

    Blender's FBX exporter operates on the active view layer and selected
    objects. A target inside a hidden collection can evaluate correctly but
    still be omitted from export. Reveal only the target's collection paths
    and restore every changed visibility flag after export.
    """
    layer_paths = []
    for collection in armature.users_collection:
        path = _find_layer_collection_path(
            view_layer.layer_collection, collection
        )
        if path is not None:
            layer_paths.append(path)

    if not layer_paths:
        raise RuntimeError(
            "Could not locate the target armature's collection in the active "
            "view layer."
        )

    state = {
        "object_hide_viewport": armature.hide_viewport,
        "object_hide_set": armature.hide_get(view_layer=view_layer),
        "collections": [],
        "layer_collections": [],
    }

    for path in layer_paths:
        for layer_collection in path:
            if not any(
                existing is layer_collection
                for existing, _excluded, _hidden in state["layer_collections"]
            ):
                state["layer_collections"].append(
                    (
                        layer_collection,
                        layer_collection.exclude,
                        layer_collection.hide_viewport,
                    )
                )

            collection = layer_collection.collection
            if not any(
                existing is collection
                for existing, _hidden in state["collections"]
            ):
                state["collections"].append(
                    (collection, collection.hide_viewport)
                )

    try:
        # Unhide only the collection paths that contain the target armature.
        for collection, _was_hidden in state["collections"]:
            collection.hide_viewport = False

        for layer_collection, _was_excluded, _was_hidden in state[
            "layer_collections"
        ]:
            layer_collection.exclude = False
            layer_collection.hide_viewport = False

        armature.hide_viewport = False
        armature.hide_set(False, view_layer=view_layer)
        view_layer.update()

        if not armature.visible_get(view_layer=view_layer):
            raise RuntimeError(
                "The target armature remains hidden after temporarily "
                "revealing its collection."
            )
    except Exception:
        try:
            _restore_armature_visibility(armature, view_layer, state)
        except Exception as restore_exc:
            print(
                "Unity FBX export: visibility rollback failed: "
                f"{restore_exc}"
            )
        raise

    return state

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


def _build_unity_export_armature(
    context, source_armature, template_armature, apply_limb_z180=False
):
    """Bake evaluated source motion onto a duplicate of the Unity template.

    For each matching bone, transfer its evaluated transform relative to its
    source rest pose onto the destination rest pose in world space. This avoids
    relying on matching parent trees and supports R6IK-to-Unity hierarchy changes.

    The source/control rig is never modified. The temporary destination has no
    constraints; it receives only baked animation keys.
    """
    # The source is the evaluated seven-bone deform/export rig. In an
    # R6IK scene this is normally InternalArmature, driven by __PrimaryArmature.
    # The template may be the same object; the exporter always bakes to a
    # temporary duplicate, so the user's rig is never modified.
    _validate_r6_armature(
        source_armature, "Source armature", expected_parents=None
    )
    _validate_r6_armature(template_armature, "Unity skeleton template")

    scene = context.scene
    source_frame = scene.frame_current
    source_subframe = scene.frame_subframe
    duplicate = bpy.data.objects.new(
        "__Unity_R6_Export_Temporary",
        template_armature.data.copy(),
    )
    duplicate.matrix_world = template_armature.matrix_world.copy()
    scene.collection.objects.link(duplicate)

    try:
        # Keep the template hierarchy and bone rest axes exactly as authored.
        # The duplicate is the only object modified; the source/template rig
        # remains untouched, including when both settings reference one object.
        bpy.ops.object.select_all(action="DESELECT")
        duplicate.hide_viewport = False
        duplicate.hide_set(False)
        duplicate.select_set(True)
        context.view_layer.objects.active = duplicate

        # The duplicate must contain no constraints: its motion is baked below.
        for pose_bone in duplicate.pose.bones:
            for constraint in list(pose_bone.constraints):
                pose_bone.constraints.remove(constraint)
            pose_bone.rotation_mode = "QUATERNION"

        # Bake each source bone's motion relative to its own rest pose.
        # Work in world space so differing armature object transforms are handled,
        # then express the result in the Unity template's armature space. Assigning
        # pose_bone.matrix lets Blender derive the correct local channels for the
        # destination hierarchy (including legs reparented from Torso to HRP).
        ordered_bones = sorted(
            duplicate.data.bones,
            key=lambda bone: _bone_depth(bone),
        )
        target_object_world_inverse = duplicate.matrix_world.inverted_safe()

        for frame in range(int(scene.frame_start), int(scene.frame_end) + 1):
            scene.frame_set(frame)
            context.view_layer.update()
            depsgraph = context.evaluated_depsgraph_get()
            evaluated_source = source_armature.evaluated_get(depsgraph)
            source_object_world = evaluated_source.matrix_world.copy()

            for bone in ordered_bones:
                source_pose_bone = evaluated_source.pose.bones.get(bone.name)
                target_pose_bone = duplicate.pose.bones.get(bone.name)
                if source_pose_bone is None or target_pose_bone is None:
                    raise RuntimeError(
                        f"Could not sample evaluated bone '{bone.name}'."
                    )

                source_rest_world = (
                    source_object_world
                    @ source_armature.data.bones[bone.name].matrix_local
                )
                source_pose_world = (
                    source_object_world @ source_pose_bone.matrix
                )
                target_rest_world = (
                    template_armature.matrix_world
                    @ duplicate.data.bones[bone.name].matrix_local
                )

                # Transfer the source bone's rest-relative motion onto the
                # matching destination rest bone, independent of parent trees.
                source_rest_delta = (
                    source_rest_world.inverted_safe() @ source_pose_world
                )
                target_pose_world = target_rest_world @ source_rest_delta
                target_pose_armature = (
                    target_object_world_inverse @ target_pose_world
                )

                # Optional, reversible orientation test: rotate every R6 bone
                # except HumanoidRootPart and Torso by 180 degrees around its
                # own local Blender Z axis. Post-multiplication changes the
                # bone orientation without changing its joint position.
                if apply_limb_z180 and bone.name not in {
                    "HumanoidRootPart", "Torso"
                }:
                    target_pose_armature = (
                        target_pose_armature
                        @ Matrix.Rotation(3.141592653589793, 4, "Z")
                    )

                target_pose_bone.matrix = target_pose_armature
                context.view_layer.update()
                target_pose_bone.keyframe_insert(
                    data_path="location", frame=frame, group=bone.name
                )
                target_pose_bone.keyframe_insert(
                    data_path="rotation_quaternion", frame=frame,
                    group=bone.name
                )
                target_pose_bone.keyframe_insert(
                    data_path="scale", frame=frame, group=bone.name
                )

        if duplicate.animation_data is None or duplicate.animation_data.action is None:
            raise RuntimeError("The temporary Unity armature received no animation action.")

        duplicate.animation_data.action.name = "ECHO_Unity_Baked"

        # Verify that the keyed destination actually moves before exporting.
        baked_motion, baked_details = _sample_evaluated_motion(
            context, duplicate, scene
        )
        if not baked_motion:
            raise RuntimeError(
                "The temporary Unity skeleton did not retain the sampled motion. "
                + baked_details
            )

        # Confirm that the temporary skeleton retained the user's exact
        # custom R6 hierarchy, including legs parented to HumanoidRootPart.
        _validate_r6_armature(
            duplicate, "Temporary Unity export armature"
        )

        return duplicate
    except Exception:
        bpy.data.objects.remove(duplicate, do_unlink=True)
        if duplicate.data.users == 0:
            bpy.data.armatures.remove(duplicate.data)
        raise
    finally:
        scene.frame_set(source_frame, subframe=source_subframe)


def _bone_depth(bone):
    """Return a bone's hierarchy depth for parent-first pose assignment."""
    depth = 0
    parent = bone.parent
    while parent is not None:
        depth += 1
        parent = parent.parent
    return depth


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
    apply_limb_z180: BoolProperty(
        name="Apply 180° local Z correction to limbs",
        description=(
            "Test a 180-degree local Blender Z orientation correction on Head, "
            "both arms and both legs; disable to revert to the original orientation"
        ),
        default=True,
    )
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
        template_name = (
            getattr(settings, "rbx_unity_template_armature", "") if settings else ""
        )
        # A separate rest-pose template is optional. If none is selected,
        # preserve the target rig's own rest pose by using it as the template.
        template_armature = (
            bpy.data.objects.get(template_name) if template_name else armature
        )

        if armature is None or armature.type != "ARMATURE":
            self.report({"ERROR"}, "Choose a valid source armature first.")
            return {"CANCELLED"}
        if template_armature is None or template_armature.type != "ARMATURE":
            self.report(
                {"ERROR"},
                "Choose your custom player armature in Unity Skeleton Template.",
            )
            return {"CANCELLED"}
        # Source and template may intentionally be the same armature. The
        # bake always runs on a temporary duplicate, leaving the original safe.

        if not self.filepath:
            self.report({"ERROR"}, "Choose an FBX output path.")
            return {"CANCELLED"}

        if scene.frame_end <= scene.frame_start:
            self.report({"ERROR"}, "The scene frame range must contain at least two frames.")
            return {"CANCELLED"}
        if not armature.data.bones:
            self.report({"ERROR"}, "The target armature has no bones.")
            return {"CANCELLED"}
        try:
            _validate_r6_armature(
                armature, "Target armature", expected_parents=None
            )
            _validate_r6_armature(template_armature, "Unity skeleton template")
        except RuntimeError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        view_layer = context.view_layer
        if view_layer.objects.get(armature.name) is None:
            self.report(
                {"ERROR"},
                "The target armature is not in the active view layer. Move it into "
                "an included collection before exporting.",
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
        visibility_state = None
        export_armature = None

        try:
            # Blender's FBX exporter needs the selected target to be visible.
            # Temporarily reveal hidden collection paths without changing the
            # user's saved rig visibility.
            visibility_state = _temporarily_reveal_armature(armature, view_layer)

            # Check that the constrained export armature actually receives motion.
            has_motion, motion_details = _sample_evaluated_motion(context, armature, scene)
            if not has_motion:
                self.report(
                    {"ERROR"},
                    "The selected evaluated R6 armature is not moving. "
                    + motion_details
                    + ". Keep the R6IK control rig and its constraints enabled, "
                    "and check the scene frame range."
                )
                return {"CANCELLED"}
            print(
                "Unity FBX preflight: evaluated source motion detected. "
                + motion_details
            )
            scene.frame_set(previous_frame, subframe=previous_subframe)

            # FBX export requires Object Mode. Exit the mode of the currently
            # active object, not necessarily the selected export armature.
            if previous_active and previous_active.mode != "OBJECT":
                bpy.ops.object.mode_set(mode="OBJECT")

            # Build a temporary baked skeleton using the selected template's
            # R6 hierarchy and rest axes. The original armature and constraints
            # remain untouched, even when source and template are the same object.
            export_armature = _build_unity_export_armature(
                context, armature, template_armature,
                apply_limb_z180=self.apply_limb_z180,
            )

            bpy.ops.object.select_all(action="DESELECT")
            export_armature.select_set(True)
            view_layer.objects.active = export_armature

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

                # Remove the temporary baked export armature; never leave it
                # in the user's Blender scene.
                if export_armature is not None:
                    temporary_data = export_armature.data
                    bpy.data.objects.remove(export_armature, do_unlink=True)
                    if temporary_data.users == 0:
                        bpy.data.armatures.remove(temporary_data)

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
            finally:
                # Visibility restoration must run even if context restoration fails.
                if visibility_state is not None:
                    try:
                        _restore_armature_visibility(
                            armature, view_layer, visibility_state
                        )
                    except Exception as visibility_restore_exc:
                        print(
                            "Unity FBX export: could not restore original "
                            f"visibility state: {visibility_restore_exc}"
                        )

        self.report(
            {"INFO"},
            "Exported animation-only FBX. Verify bone mapping and motion in Unity.",
        )
        return {"FINISHED"}
