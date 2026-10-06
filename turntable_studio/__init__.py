"""Turntable Studio: one-click turntable render setup for Blender."""

import math

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from mathutils import Vector

RIG_COLLECTION = "Turntable Studio"
RIG_TAG = "turntable_studio"
BOUNDS_TYPES = {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "VOLUME"}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _is_rig(obj):
    return bool(obj.get(RIG_TAG))


def _target_objects(context):
    objs = [o for o in context.selected_objects
            if o.type in BOUNDS_TYPES and not _is_rig(o)]
    return objs


def _world_bounds(context, objs):
    """Return (center, radius) of the combined world-space bounding box."""
    depsgraph = context.evaluated_depsgraph_get()
    corners = []
    for obj in objs:
        ev = obj.evaluated_get(depsgraph)
        corners.extend(ev.matrix_world @ Vector(c) for c in ev.bound_box)
    lo = Vector((min(c[i] for c in corners) for i in range(3)))
    hi = Vector((max(c[i] for c in corners) for i in range(3)))
    center = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 0.01)
    return center, radius


def _remove_rig():
    for obj in [o for o in bpy.data.objects if _is_rig(o)]:
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if data is not None and data.users == 0:
            if isinstance(data, bpy.types.Camera):
                bpy.data.cameras.remove(data)
            elif isinstance(data, bpy.types.Light):
                bpy.data.lights.remove(data)
    coll = bpy.data.collections.get(RIG_COLLECTION)
    if coll is not None and not coll.objects:
        bpy.data.collections.remove(coll)


def _new_object(name, data, collection, parent=None):
    obj = bpy.data.objects.new(name, data)
    obj[RIG_TAG] = True
    collection.objects.link(obj)
    if parent is not None:
        obj.parent = parent
    return obj


def _track_to(obj, target):
    con = obj.constraints.new("TRACK_TO")
    con.target = target
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"


def _add_light(name, collection, pivot, pos, energy, size, color=(1, 1, 1)):
    light = bpy.data.lights.new(name, "AREA")
    light.energy = energy
    light.size = size
    light.color = color
    obj = _new_object(name, light, collection, pivot)
    obj.location = pos
    _track_to(obj, pivot)
    return obj


def _fcurves(action):
    """All F-curves of an action, for both legacy and slotted (4.4+) actions."""
    if hasattr(action, "layers"):
        return [fc for layer in action.layers for strip in layer.strips
                for bag in strip.channelbags for fc in bag.fcurves]
    return list(action.fcurves)


def _find_engine(prefix):
    items = bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items
    for item in items:
        if item.identifier.startswith(prefix):
            return item.identifier
    return None


def _set_video_output(render):
    """Switch to MP4/H.264; returns False if this build lacks FFMPEG."""
    try:
        render.image_settings.file_format = "FFMPEG"
    except TypeError:
        return False
    render.ffmpeg.format = "MPEG4"
    render.ffmpeg.codec = "H264"
    render.ffmpeg.constant_rate_factor = "HIGH"
    return True


def _apply_render_settings(scene, s):
    """Apply output settings. Returns a warning string, or None."""
    warning = None
    r = scene.render
    r.resolution_x, r.resolution_y = s.resolution_x, s.resolution_y
    r.resolution_percentage = 100

    if s.engine == "CYCLES":
        r.engine = "CYCLES"
        scene.cycles.samples = s.samples
    elif s.engine == "EEVEE":
        eevee = _find_engine("BLENDER_EEVEE")
        if eevee:
            r.engine = eevee
            scene.eevee.taa_render_samples = s.samples

    r.filepath = s.output_path
    if s.output_format == "MP4" and not _set_video_output(r):
        warning = "This Blender build has no FFMPEG support; using PNG sequence"
    if r.image_settings.file_format != "FFMPEG":
        r.image_settings.file_format = "PNG"
        r.image_settings.color_mode = "RGBA" if s.transparent else "RGB"
    r.film_transparent = s.transparent
    return warning


def _apply_background(scene, color):
    world = scene.world or bpy.data.worlds.new("Turntable World")
    scene.world = world
    try:
        world.use_nodes = True
    except Exception:
        pass
    bg = world.node_tree.nodes.get("Background") if world.node_tree else None
    if bg is not None:
        bg.inputs[0].default_value = (*color, 1.0)


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

class TurntableSettings(bpy.types.PropertyGroup):
    frames: IntProperty(
        name="Frames", default=120, min=8, soft_max=600,
        description="Length of one full rotation")
    margin: FloatProperty(
        name="Margin", default=1.15, min=1.0, soft_max=2.5,
        description="Extra room around the subject (1.0 = tight fit)")
    elevation: FloatProperty(
        name="Elevation", default=math.radians(20), min=math.radians(-80),
        max=math.radians(80), subtype="ANGLE",
        description="Camera height angle above the subject")
    focal_length: FloatProperty(
        name="Focal Length", default=70.0, min=10.0, max=300.0, unit="CAMERA")
    add_lights: BoolProperty(
        name="Three-Point Lights", default=True,
        description="Add key, fill and rim area lights that orbit with the camera")
    set_background: BoolProperty(name="Set Background", default=True)
    background: FloatVectorProperty(
        name="Color", subtype="COLOR", size=3, min=0.0, max=1.0,
        default=(0.04, 0.04, 0.05))
    engine: EnumProperty(
        name="Engine", default="KEEP",
        items=[
            ("KEEP", "Keep Current", ""),
            ("EEVEE", "EEVEE", "Fast"),
            ("CYCLES", "Cycles", "Path traced"),
        ])
    samples: IntProperty(name="Samples", default=64, min=1, soft_max=4096)
    resolution_x: IntProperty(name="X", default=1920, min=16, soft_max=8192)
    resolution_y: IntProperty(name="Y", default=1080, min=16, soft_max=8192)
    transparent: BoolProperty(
        name="Transparent Background", default=False,
        description="Render with alpha (PNG sequence only)")
    output_format: EnumProperty(
        name="Format", default="MP4",
        items=[("MP4", "MP4 Video", ""), ("PNG", "PNG Sequence", "")])
    output_path: StringProperty(
        name="Output", default="//turntable/turntable_", subtype="FILE_PATH")


# --------------------------------------------------------------------------
# Operators
# --------------------------------------------------------------------------

class TURNTABLE_OT_create(bpy.types.Operator):
    bl_idname = "turntable.create"
    bl_label = "Create Turntable"
    bl_description = "Build a camera, lights and rotation around the selected objects"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return context.mode == "OBJECT"

    def execute(self, context):
        objs = _target_objects(context)
        if not objs:
            self.report({"ERROR"}, "Select at least one mesh/curve/text object")
            return {"CANCELLED"}

        scene = context.scene
        s = scene.turntable_studio
        center, radius = _world_bounds(context, objs)

        _remove_rig()
        coll = bpy.data.collections.new(RIG_COLLECTION)
        scene.collection.children.link(coll)

        pivot = _new_object("Turntable Pivot", None, coll)
        pivot.empty_display_type = "PLAIN_AXES"
        pivot.empty_display_size = radius * 0.5
        pivot.location = center

        # Camera distance so the bounding sphere fits the frame.
        cam_data = bpy.data.cameras.new("Turntable Camera")
        cam_data.lens = s.focal_length
        cam_data.clip_end = max(1000.0, radius * 100)
        # Sensor width spans the larger image dimension (AUTO fit), so the
        # smaller dimension has a proportionally narrower field of view.
        ratio = min(s.resolution_x, s.resolution_y) / max(s.resolution_x, s.resolution_y)
        half_fov = math.atan(cam_data.sensor_width / 2 / s.focal_length * ratio)
        dist = radius * s.margin / math.sin(half_fov)

        cam = _new_object("Turntable Camera", cam_data, coll, pivot)
        cam.location = (0, -dist * math.cos(s.elevation),
                        dist * math.sin(s.elevation))
        _track_to(cam, pivot)
        scene.camera = cam

        if s.add_lights:
            _add_light("Turntable Key", coll, pivot,
                       (-0.8 * dist, -0.7 * dist, 0.9 * dist),
                       40 * dist ** 2, dist * 0.6, (1.0, 0.96, 0.9))
            _add_light("Turntable Fill", coll, pivot,
                       (0.9 * dist, -0.5 * dist, 0.3 * dist),
                       15 * dist ** 2, dist * 0.9, (0.85, 0.92, 1.0))
            _add_light("Turntable Rim", coll, pivot,
                       (0.2 * dist, 0.9 * dist, 0.8 * dist),
                       30 * dist ** 2, dist * 0.4)

        # One full turn, linear, looping seamlessly (frame N+1 == frame 1).
        scene.frame_start, scene.frame_end = 1, s.frames
        pivot.rotation_euler = (0, 0, 0)
        pivot.keyframe_insert("rotation_euler", index=2, frame=1)
        pivot.rotation_euler = (0, 0, math.tau)
        pivot.keyframe_insert("rotation_euler", index=2, frame=s.frames + 1)
        for fcurve in _fcurves(pivot.animation_data.action):
            for key in fcurve.keyframe_points:
                key.interpolation = "LINEAR"
        pivot.rotation_euler = (0, 0, 0)

        warning = _apply_render_settings(scene, s)
        if warning:
            self.report({"WARNING"}, warning)
        if s.set_background:
            _apply_background(scene, s.background)

        context.view_layer.update()
        self.report({"INFO"}, f"Turntable ready: {s.frames} frames")
        return {"FINISHED"}


class TURNTABLE_OT_remove(bpy.types.Operator):
    bl_idname = "turntable.remove"
    bl_label = "Remove Turntable"
    bl_description = "Delete the turntable camera, lights and pivot"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(_is_rig(o) for o in bpy.data.objects)

    def execute(self, context):
        _remove_rig()
        return {"FINISHED"}


class TURNTABLE_OT_render(bpy.types.Operator):
    bl_idname = "turntable.render"
    bl_label = "Render Turntable"
    bl_description = "Render the turntable animation"

    @classmethod
    def poll(cls, context):
        return any(_is_rig(o) for o in bpy.data.objects)

    def execute(self, context):
        return bpy.ops.render.render("INVOKE_DEFAULT", animation=True)


# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

class VIEW3D_PT_turntable(bpy.types.Panel):
    bl_label = "Turntable Studio"
    bl_idname = "VIEW3D_PT_turntable_studio"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Turntable"

    def draw(self, context):
        layout = self.layout
        s = context.scene.turntable_studio
        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column(align=True)
        col.operator("turntable.create", icon="CAMERA_DATA")
        row = col.row(align=True)
        row.operator("turntable.render", icon="RENDER_ANIMATION")
        row.operator("turntable.remove", text="", icon="TRASH")

        box = layout.box()
        box.label(text="Camera", icon="VIEW_CAMERA")
        box.prop(s, "frames")
        box.prop(s, "margin")
        box.prop(s, "elevation")
        box.prop(s, "focal_length")

        box = layout.box()
        box.label(text="Look", icon="LIGHT")
        box.prop(s, "add_lights")
        box.prop(s, "set_background")
        if s.set_background:
            box.prop(s, "background")

        box = layout.box()
        box.label(text="Output", icon="OUTPUT")
        box.prop(s, "engine")
        if s.engine != "KEEP":
            box.prop(s, "samples")
        row = box.row(align=True)
        row.prop(s, "resolution_x")
        row.prop(s, "resolution_y")
        box.prop(s, "output_format")
        if s.output_format == "PNG":
            box.prop(s, "transparent")
        box.prop(s, "output_path", text="Path")


classes = (
    TurntableSettings,
    TURNTABLE_OT_create,
    TURNTABLE_OT_remove,
    TURNTABLE_OT_render,
    VIEW3D_PT_turntable,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.turntable_studio = PointerProperty(type=TurntableSettings)


def unregister():
    del bpy.types.Scene.turntable_studio
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
