# -*- coding: utf-8 -*-
"""
法线朝向检查（命令行运行）

判断方法：计算网格的「有符号体积」
    正值 -> 法线朝外（正常）
    负值 -> 法线朝内（反了，会导致覆盖率统计全部失真）

用法：
    blender --background --python check_normals.py
"""

import bpy
import bmesh
import sys

OBJ = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/F16XL.obj"

# 清空默认场景
bpy.ops.wm.read_factory_settings(use_empty=True)

print("=" * 72)
print("导入:", OBJ)
bpy.ops.wm.obj_import(filepath=OBJ)

meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
print("对象数:", len(meshes))
print("=" * 72)

n_out = n_in = n_bad = 0
rows = []

for obj in meshes:
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    try:
        vol = bm.calc_volume(signed=True)
    except Exception as e:
        vol = None
        n_bad += 1
    bm.free()

    if vol is None:
        tag = "无法计算"
    elif vol > 0:
        tag = "朝外 OK"
        n_out += 1
    else:
        tag = "朝内 !! 反了"
        n_in += 1
    rows.append((obj.name, len(me.polygons), vol, tag))

print("%-46s %8s %12s  %s" % ("对象", "面数", "有符号体积", "判定"))
print("-" * 72)
for name, npoly, vol, tag in sorted(rows, key=lambda r: (r[2] if r[2] is not None else 0)):
    vs = "%.4f" % vol if vol is not None else "n/a"
    print("%-46s %8d %12s  %s" % (name[:46], npoly, vs, tag))

print("-" * 72)
print("朝外: %d   朝内: %d   无法计算: %d" % (n_out, n_in, n_bad))
print()
if n_in:
    print("结论：有 %d 个对象的法线朝内，覆盖率统计会因此失真。" % n_in)
else:
    print("结论：全部对象的法线朝向正常。")
