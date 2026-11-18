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
- Let Blender's FBX exporter sample the evaluated armature pose, including dependency-graph evaluation of constraints.
- Export all armature bones, including non-deform bones.
- Keep the source rig, constraints, and actions unchanged.
- Use one-frame sampling with animation simplification disabled to avoid intentionally dropping motion.

## Unity FBX export

1. Open the **Animation Bridge** tab in the 3D Viewport sidebar (`N`).
2. Set the add-on's **Target** armature to the skeleton whose animation you want to export.
3. Set the scene frame range to the animation's intended start and end.
4. Make sure the animation plays correctly in Blender and set the scene frame range to cover it. For an R6IK-style setup, the control armature (for example, `__PrimaryArmature`) can carry the action while the export target (for example, `InternalArmature`) follows through constraints. Keep both rigs in the scene; choose only the seven-bone export armature as **Target**.
5. In the **Unity Export** section, choose **Export for Unity (.fbx)** and save the file.
6. In Unity, import the FBX and configure its Rig as **Generic**. Use the same bone hierarchy and bone names as the character model that will play the clip.

### Important notes

- This first Unity exporter is intentionally animation-only: it exports the armature, not the character mesh.
- The target armature must evaluate correctly in Blender before export. Driver rigs and constraint targets must remain available in the scene so Blender can evaluate the dependency graph; only the target armature is selected for FBX export.
- The exporter deliberately uses Blender's global scene animation bake (NLA-strip export off and all-actions export off). Blender samples the selected armature's evaluated pose over the scene frame range, so a separate control rig can drive it through constraints without being included in the FBX. This avoids destructive manual constraint clearing or baking on the original rig.
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
