# -*- coding: utf-8 -*-
"""
OrthoTex 实验 02 可视化：把未覆盖区域染色后渲染

读取 coverage.json 中的逐面覆盖计数，按状态给面上色：
    灰色 = 被至少一个视图覆盖
    红色 = 三个视图都看不到（未覆盖）

注意：必须在与 coverage.py 相同的场景状态下运行
      （对象集合与遍历顺序必须一致，否则 covered_by 索引会错位）

产出：experiments/exp02_coverage/painted_{front,right,top}.png
"""

import bpy
import os
import json
import time
from mathutils import Vector

OUT = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/experiments/exp02_coverage"
JSON_PATH = os.path.join(OUT, "coverage.json")
RES = 1024

VIEWS = [
    ("front", Vector((0.0, -1.0, 0.0))),
    ("right", Vector((1.0, 0.0, 0.0))),
    ("top",   Vector((0.0, 0.0, 1.0))),
]

with open(JSON_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)
covered_by = data["covered_by"]

meshes = [o for o in bpy.context.scene.objects
          if o.type == 'MESH' and not o.hide_viewport and not o.hide_get()]

print("对象数: %d   记录的面数: %d" % (len(meshes), len(covered_by)))

# ---- 按与 coverage.py 相同的顺序遍历，写入顶点颜色 ----
COL_COVERED = (0.72, 0.72, 0.72, 1.0)   # 灰
COL_MISSING = (0.90, 0.15, 0.15, 1.0)   # 红

i = 0
n_missing = 0
for obj in meshes:
    me = obj.data
    if "Coverage" in me.color_attributes:
        me.color_attributes.remove(me.color_attributes["Coverage"])
    # 用 CORNER 域：每个面的每个角独立着色，不受相邻面影响。
    # （用 POINT 域时，一个顶点只要挨着一个已覆盖的面就会整体变灰，
    #   而本模型的未覆盖面大多紧贴已覆盖面，会导致整机看不到红色。）
    attr = me.color_attributes.new(name="Coverage", type='FLOAT_COLOR', domain='CORNER')

    for p in me.polygons:
        m = covered_by[i] if i < len(covered_by) else 0
        col = COL_COVERED if m else COL_MISSING
        if not m:
            n_missing += 1
        for li in p.loop_indices:
            attr.data[li].color = col
        i += 1

print("已写入面级颜色。未覆盖的面显示为红色。")
print("本次标红的面数: %d" % n_missing)

# ---- 渲染 ----
scene = bpy.context.scene
cam = scene.camera
if cam is None or cam.type != 'CAMERA':
    cam_data = bpy.data.cameras.new("PaintCam")
    cam_data.type = 'ORTHO'
    cam = bpy.data.objects.new("PaintCam", cam_data)
    bpy.context.collection.objects.link(cam)
    scene.camera = cam

# 用与 exp01 相同的包围盒逻辑（排除离群对象）
import statistics
centers = []
for o in meshes:
    cs = [o.matrix_world @ Vector(c) for c in o.bound_box]
    centers.append(sum(cs, Vector()) / 8.0)
med = Vector((statistics.median([c.x for c in centers]),
              statistics.median([c.y for c in centers]),
              statistics.median([c.z for c in centers])))
dists = [(c - med).length for c in centers]
thresh = max(statistics.median(dists) * 6.0, 1.0)
kept = [o for o, d in zip(meshes, dists) if d <= thresh]

pts = []
for o in kept:
    for c in o.bound_box:
        pts.append(o.matrix_world @ Vector(c))
xs = [p.x for p in pts]; ys = [p.y for p in pts]; zs = [p.z for p in pts]
lo = Vector((min(xs), min(ys), min(zs)))
hi = Vector((max(xs), max(ys), max(zs)))
center = (lo + hi) / 2
size = hi - lo

scene.render.resolution_x = RES
scene.render.resolution_y = RES
scene.render.image_settings.file_format = 'PNG'
try:
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'FLAT'
    scene.display.shading.color_type = 'VERTEX'
except Exception as e:
    print("渲染设置警告（可能影响显示效果）:", e)

dist = max(size.x, size.y, size.z) * 2.0
for name, d in VIEWS:
    cam.location = center + d * dist
    look = (center - cam.location).normalized()
    cam.rotation_euler = look.to_track_quat('-Z', 'Y').to_euler()
    if name == "top":
        span = max(size.x, size.y)
    elif name == "right":
        span = max(size.y, size.z)
    else:
        span = max(size.x, size.z)
    cam.data.ortho_scale = span * 1.05

    scene.render.filepath = os.path.join(OUT, "painted_%s.png" % name)
    bpy.ops.render.render(write_still=True)
    print("已渲染 painted_%s.png" % name)

print("完成。输出目录：", OUT)
