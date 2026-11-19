# Blender Animation Bridge

A Blender add-on for working with character rigs and animation across **Roblox Studio** and **Unity**.

The project preserves the original Roblox animation workflow and adds a separate Unity FBX export path. The add-on package and internal Python module retain their existing identifiers for compatibility with existing installations and user files.

## Features

### Roblox workflow
- Import Roblox rigs and places.
- Work with IK/FK rigging and animation tools.
- Transfer animations between Blender and Roblox Studio through the existing sync workflow.
- Bake animation data to the existing Roblox clipboard and `.rbxanim` formats.
- Import FBX animation files for Roblox rigs.

### Unity workflow
- Export the target armature as an animation-only FBX.
- Sample the evaluated seven-bone armature pose from the dependency graph, including motion driven by a separate R6IK control rig, then bake it onto the Unity destination skeleton.
- Export all armature bones, including non-deform bones.
- Keep the source rig, constraints, and actions unchanged.
- Use one-frame sampling with animation simplification disabled to avoid intentionally dropping motion.

## Unity FBX export

1. Open the **Animation Bridge** tab in the 3D Viewport sidebar (`N`).
2. Set **Target R6 Rig** to the evaluated seven-bone skeleton whose motion should be exported. For the R6IK setup, choose `InternalArmature`, not the 40-bone `__PrimaryArmature` control rig.
3. Set the scene frame range to the animation's intended start and end.
4. Make sure the animation plays correctly in Blender. The control armature (for example, `__PrimaryArmature`) may carry the action while `InternalArmature` follows through constraints. Keep both rigs in the scene so Blender can evaluate those constraints.
5. Set **Unity Skeleton Template** to your seven-bone Unity character skeleton. It must use the custom Unity hierarchy documented below. The source and destination may have different parent structures: for example, R6IK's `InternalArmature` can keep both legs parented to `Torso`, while the Unity template has both legs parented directly to `HumanoidRootPart`. The exporter samples the evaluated source transforms and rebases them onto the destination hierarchy. Leave the template unset only when the source itself already uses the custom Unity hierarchy.
6. In the **Unity Export** section, choose **Export for Unity (.fbx)** and save the file.
7. In Unity, import the FBX and configure its Rig as **Generic**. Use the same bone hierarchy and bone names as the character model that will play the clip.

### Important notes

- This first Unity exporter is intentionally animation-only: it exports the armature, not the character mesh.
- The Unity destination skeleton must use this custom R6 hierarchy: `HumanoidRootPart` at the root; `Torso` parented to it; `Head` and both arms parented to `Torso`; and both legs parented directly to `HumanoidRootPart`. The evaluated source skeleton may use a different hierarchy (including the standard R6IK layout with both legs parented to `Torso`). The exporter rebases each evaluated bone transform onto the destination's parent structure; it does not reparent or modify the source rig.
- Separate rigid body-part meshes may be bone-parented to their matching bones; vertex groups and Armature modifiers are not required for that setup. This animation-only exporter writes the armature and animation, not those model meshes.
- The target armature must evaluate correctly in Blender before export. Driver rigs and constraint targets must remain available in the scene so Blender can evaluate the dependency graph; only the target armature is selected for FBX export.
- The target armature may live in a hidden internal collection. During export, the add-on temporarily reveals only the target's collection path and object in the active view layer, then restores their original viewport visibility even if export fails. Render visibility is left unchanged.
- The exporter samples the evaluated source pose over the scene frame range, transfers each bone's rest-relative motion in world space to the matching Unity rest bone, and keys a temporary destination armature. A separate control rig can therefore drive `InternalArmature` without being included in the FBX or having its original Action changed. The exporter verifies that both the source and temporary destination actually move before writing the FBX.
- The initial implementation is designed around Blender's built-in FBX exporter. Unity import settings, root motion, bone orientation, and rest-pose compatibility still need validation against real rigs.
- For the best result, the Unity character and animation FBXs should share a compatible skeleton hierarchy, root bone, rest pose, and bone names.
- If the exported animation looks exaggerated or offset in Unity, check the armature's rest pose, object transforms, FBX axis settings, and Unity's Generic rig mapping before changing animation curves.

## Installation

1. Download the add-on ZIP from the repository's **Releases** page, or package the `roblox_animations` directory as a Blender add-on.
2. In Blender, open **Edit → Preferences → Get Extensions / Add-ons** and install the ZIP.
3. Enable **Blender Animation Bridge**.
4. Open the 3D Viewport sidebar with `N` and select the **Animation Bridge** tab.

## Development

The Unity exporter lives in `roblox_animations/operators/unity_export_ops.py`. It is registered alongside the existing operators and exposed in the Animation panel. The Roblox serialization/export path remains separate.

Contributions and reproducible test files are welcome. When reporting an export issue, include:
- Blender version
- Unity version
- Rig hierarchy and bone names
- Scene frame range and which rig carries the active action
- Whether the target armature is driven by constraints, drivers, or an IK control rig
- A short description of the difference between Blender playback and Unity playback

## License

This project retains the upstream GNU General Public License, version 3 or later. See [LICENSE](LICENSE) for the full terms.

The original Roblox functionality and upstream project history remain credited to their respective contributors.
