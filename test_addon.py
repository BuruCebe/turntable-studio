"""Smoke test: blender --background --factory-startup --python test_addon.py"""
import math, os, sys
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import turntable_studio

turntable_studio.register()
bpy.ops.mesh.primitive_monkey_add(location=(3, 2, 1))
bpy.ops.mesh.primitive_cube_add(location=(3, 2, 4))
for o in bpy.data.objects:
    o.select_set(True)

for engine, fmt in (("EEVEE", "MP4"), ("CYCLES", "PNG")):
    s = bpy.context.scene.turntable_studio
    s.engine, s.output_format = engine, fmt
    assert bpy.ops.turntable.create() == {"FINISHED"}
    sc = bpy.context.scene
    pivot = bpy.data.objects["Turntable Pivot"]
    assert sc.camera and sc.camera.parent == pivot
    pts = [(k.co[0], k.co[1], k.interpolation) for c in turntable_studio._fcurves(pivot.animation_data.action) for k in c.keyframe_points]
    assert [p[2] for p in pts] == ["LINEAR", "LINEAR"], pts
    assert abs(pts[1][1] - math.tau) < 1e-6
    assert fmt == "PNG" or sc.render.image_settings.file_format in ("FFMPEG", "PNG")
    print(engine, fmt, sc.render.engine, sc.render.image_settings.file_format, pts)
    assert sum(1 for o in bpy.data.objects if o.get("turntable_studio")) == 5

assert bpy.ops.turntable.remove() == {"FINISHED"}
assert not any(o.get("turntable_studio") for o in bpy.data.objects)
assert "Turntable Studio" not in bpy.data.collections
turntable_studio.unregister()
print("ALL OK")
