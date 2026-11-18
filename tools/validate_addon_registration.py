import sys,importlib,bpy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
addon=importlib.import_module('roblox_animations')
addon.register()
assert hasattr(bpy.context.scene,'rbx_anim_settings')
for cls in addon.CLASSES:
 assert getattr(bpy.types,cls.__name__,None) is not None or getattr(cls,'is_registered',False),cls.__name__
assert hasattr(bpy.ops.object,'rbxanims_attach_to_bone')
assert hasattr(bpy.ops.object,'rbxanims_import_and_attach')
assert hasattr(bpy.ops.object,'rbxanims_export_unity_fbx')

# Validate that the installed Blender FBX exporter exposes every option used
# by the Unity export operator. This catches API/version mismatches early.
fbx_rna = bpy.ops.export_scene.fbx.get_rna_type()
fbx_properties = {prop.identifier for prop in fbx_rna.properties}
required_fbx_properties = {
 'filepath', 'check_existing', 'use_selection', 'object_types',
 'apply_unit_scale', 'use_space_transform', 'bake_anim',
 'bake_anim_use_all_bones', 'bake_anim_use_nla_strips',
 'bake_anim_use_all_actions', 'bake_anim_force_startend_keying',
 'bake_anim_step', 'bake_anim_simplify_factor', 'add_leaf_bones',
 'use_armature_deform_only', 'axis_forward', 'axis_up',
}
missing_fbx_properties = required_fbx_properties - fbx_properties
assert not missing_fbx_properties, f'Missing FBX exporter properties: {sorted(missing_fbx_properties)}'
from roblox_animations.rig import avatar_scale
assert callable(avatar_scale.entry_limb_scale)
print('REGISTER_OK',len(addon.CLASSES),'classes')
addon.unregister()
assert not hasattr(bpy.types.Scene,'rbx_anim_settings')
addon.register()
assert hasattr(bpy.context.scene,'rbx_anim_settings')
print('REREGISTER_OK')
addon.unregister()
