# -*- coding: utf-8 -*-
"""快速诊断 v2：unwrap/pack 在"有旧 UV"与"空 UV"下的行为差异 + 重叠检测（用后即删）"""
import bpy
import bmesh
import math

OBJ = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/F16XL.obj"
EXCLUDE_KEYS = ["aim_9l_sidewinder", "aim_120a_missile", "drop_tank",
                "pylon", "launcher_aim9", "gear_", "wheel_"]
TEX = 1024


def build_base(ratio):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.obj_import(filepath=OBJ)
    SCENE = bpy.context.scene
    for obj in SCENE.objects:
        if obj.type != 'MESH':
            continue
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        try:
            v = bm.calc_volume(signed=True)
        except Exception:
            v = 0
        if v < 0:
            bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
            bm.to_mesh(obj.data)
            obj.data.update()
        bm.free()
    keep = [o for o in SCENE.objects if o.type == 'MESH'
            and not any(k in o.name for k in EXCLUDE_KEYS)]
    for obj in list(SCENE.objects):
        if obj.type == 'MESH' and obj not in keep:
            bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.object.select_all(action='DESELECT')
    for o in keep:
        o.select_set(True)
    bpy.context.view_layer.objects.active = keep[0]
    bpy.ops.object.join()
    body = bpy.context.view_layer.objects.active
    mod = body.modifiers.new(name="dec", type='DECIMATE')
    mod.ratio = ratio
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.modifier_apply(modifier="dec")
    return body


def uv_area_of(obj):
    me = obj.data
    uvl = me.uv_layers.active
    if uvl is None or len(uvl.data) == 0:
        return -1.0
    tot = 0.0
    for p in me.polygons:
        pts = [uvl.data[li].uv for li in p.loop_indices]
        a = 0.0
        for i in range(len(pts)):
            x1, y1 = pts[i].x, pts[i].y
            x2, y2 = pts[(i + 1) % len(pts)].x, pts[(i + 1) % len(pts)].y
            a += x1 * y2 - x2 * y1
        tot += abs(a) / 2.0
    return tot


def overlap_check(obj):
    """光栅化 UV 三角形，统计 总覆盖次数 / 唯一纹素数（比值 > 1.02 即有重叠）"""
    me = obj.data
    uvl = me.uv_layers.active
    cover = bytearray(TEX * TEX)
    total = 0
    for p in me.polygons:
        li = list(p.loop_indices)
        if len(li) != 3:
            continue
        pts = [uvl.data[i].uv for i in li]
        xs = [u.x for u in pts]
        ys = [u.y for u in pts]
        x0 = max(0, int(min(xs) * (TEX - 1)))
        x1 = min(TEX - 1, int(max(xs) * (TEX - 1)) + 1)
        y0 = max(0, int(min(ys) * (TEX - 1)))
        y1 = min(TEX - 1, int(max(ys) * (TEX - 1)) + 1)
        au, av = pts[0].x, pts[0].y
        bu, bv = pts[1].x, pts[1].y
        cu, cv = pts[2].x, pts[2].y
        d = (bv - cv) * (au - cu) + (cu - bu) * (av - cv)
        if abs(d) < 1e-12:
            continue
        for y in range(y0, y1 + 1):
            py = y / (TEX - 1.0)
            row = y * TEX
            for x in range(x0, x1 + 1):
                px = x / (TEX - 1.0)
                a = ((bv - cv) * (px - cu) + (cu - bu) * (py - cv)) / d
                b = ((cv - av) * (px - cu) + (au - cu) * (py - cv)) / d
                g = 1.0 - a - b
                if a < -0.002 or b < -0.002 or g < -0.002:
                    continue
                k = row + x
                if cover[k] < 255:
                    cover[k] += 1
                total += 1
    unique = sum(1 for c in cover if c)
    return total, unique


def unwrap_pack(obj, clear, pack):
    me = obj.data
    if clear:
        while len(me.uv_layers) > 0:
            me.uv_layers.remove(me.uv_layers[0])
        me.uv_layers.new(name="UVMap")
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='DESELECT')
    bpy.ops.mesh.select_mode(type='EDGE')
    bpy.ops.mesh.mark_seam(clear=True)
    bpy.ops.mesh.edges_select_sharp(sharpness=math.radians(60))
    bpy.ops.mesh.mark_seam(clear=False)
    bpy.ops.mesh.select_mode(type='FACE')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=0.001)
    bpy.ops.object.mode_set(mode='OBJECT')
    a_unwrap = uv_area_of(obj)
    a_pack = None
    if pack:
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.uv.select_all(action='SELECT')
        bpy.ops.uv.pack_islands(margin=0.001)
        bpy.ops.object.mode_set(mode='OBJECT')
        a_pack = uv_area_of(obj)
    return a_unwrap, a_pack


print("=" * 60)
for clear, pack in [(False, False), (False, True), (True, False), (True, True)]:
    body = build_base(0.05)
    label = "clear=%-5s pack=%-5s" % (clear, pack)
    au, ap = unwrap_pack(body, clear, pack)
    msg = "%s  unwrap后=%.4f" % (label, au)
    if ap is not None:
        msg += " → pack后=%.4f" % ap
    tot, uniq = overlap_check(body)
    msg += "   重叠比=%.3f (%d/%d)" % (tot / max(1, uniq), tot, uniq)
    print(msg)
    bpy.data.objects.remove(body, do_unlink=True)
print("=" * 60)
