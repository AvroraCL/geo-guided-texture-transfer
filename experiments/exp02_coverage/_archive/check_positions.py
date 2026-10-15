# -*- coding: utf-8 -*-
"""命令行运行：打印关键对象的世界坐标包围盒，检查它们是否在合理位置"""

import bpy
from mathutils import Vector

OBJ = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/F16XL.obj"

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=OBJ)

meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']


def world_bbox(obj):
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


# 全部对象的总包围盒
allpts = []
for o in meshes:
    for c in o.bound_box:
        allpts.append(o.matrix_world @ Vector(c))
glo = Vector((min(p.x for p in allpts), min(p.y for p in allpts), min(p.z for p in allpts)))
ghi = Vector((max(p.x for p in allpts), max(p.y for p in allpts), max(p.z for p in allpts)))
print("=" * 76)
print("全局包围盒  min=(%.2f, %.2f, %.2f)  max=(%.2f, %.2f, %.2f)"
      % (glo.x, glo.y, glo.z, ghi.x, ghi.y, ghi.z))
print("=" * 76)

# 关注对象
keys = ["aim_9l_sidewinder", "aim_120a_missile", "drop_tank",
        "pylon", "launcher_aim9", "fuse_109", "wing_l", "wing_r"]
print("%-40s %28s %28s" % ("对象", "min (x,y,z)", "max (x,y,z)"))
print("-" * 100)
shown = 0
for o in meshes:
    if any(k in o.name for k in keys):
        lo, hi = world_bbox(o)
        print("%-40s (%7.2f,%7.2f,%7.2f)   (%7.2f,%7.2f,%7.2f)"
              % (o.name[:40], lo.x, lo.y, lo.z, hi.x, hi.y, hi.z))
        shown += 1
        if shown > 14:
            break
print("-" * 100)
print("提示：导弹应贴在机翼下，其包围盒应与机翼范围重叠。")
