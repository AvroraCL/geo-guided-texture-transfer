# -*- coding: utf-8 -*-
"""
OrthoTex 实验 01：渲染 6 张基准正交视图

用法（Blender 内）：
    1. 先 File > Import > Wavefront (.obj) 导入 F16XL.obj
    2. 切到 Scripting 工作区
    3. 在 Text Editor 中 Open 本文件，或直接 Run Script

产出：
    experiments/exp01_views/{front,back,left,right,top,bottom}.png
    experiments/exp01_views/cameras.json    相机参数（A1 投影要用）

注意：
    - 不改动模型、不新建 UV、不修改任何材质
    - 只用世界坐标包围盒自动适配相机
"""

import bpy
import os
import json
from mathutils import Vector

SCRIPT_VERSION = "v2 / 2026-10-16 05:11 —— 含隐藏对象过滤 + 离群对象过滤"
print("=" * 56)
print("render_views.py  版本:", SCRIPT_VERSION)
print("=" * 56)

OUT = os.path.join(os.path.dirname(bpy.data.filepath) if bpy.data.filepath else
                   r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译", "..")
# 若上面推导不对，直接写死路径：
OUT = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/experiments/exp01_views"
os.makedirs(OUT, exist_ok=True)

# ---------- 1. 收集场景中的网格 ----------
all_meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
# 排除隐藏对象：Blender 里按 H 隐藏、或关掉 collection 的可见性，
# 对象仍留在 scene.objects 中，必须显式过滤，否则包围盒照旧被撑大。
objs = [o for o in all_meshes if not o.hide_viewport and not o.hide_get()]

hidden = len(all_meshes) - len(objs)
if not objs:
    raise RuntimeError("场景里没有可见的网格对象。请先导入 F16XL.obj，并确认对象未被隐藏。")

print("场景网格对象总数: %d   其中隐藏: %d   参与计算: %d"
      % (len(all_meshes), hidden, len(objs)))

# ---------- 2. 排除离群对象，再算包围盒 ----------
# 原因：F16XL.obj 中有 23 个 vehicle#gear_c* 小零件位于 y≈-28.3，
# 而机身主体在 y≈0，相距 28 单位。若用全局包围盒，相机会被拉远 3 倍。
import statistics

centers = []
for o in objs:
    cs = [o.matrix_world @ Vector(c) for c in o.bound_box]
    centers.append(sum(cs, Vector()) / 8.0)

med = Vector((
    statistics.median([c.x for c in centers]),
    statistics.median([c.y for c in centers]),
    statistics.median([c.z for c in centers]),
))
dists = [(c - med).length for c in centers]
dmed = statistics.median(dists)
thresh = max(dmed * 6.0, 1.0)

kept, dropped = [], []
for o, d in zip(objs, dists):
    (kept if d <= thresh else dropped).append((o, d))

print("参考中心 (中位数): (%.3f, %.3f, %.3f)" % (med.x, med.y, med.z))
print("距离中位数: %.3f   阈值: %.3f" % (dmed, thresh))
print("参与包围盒的对象: %d   排除: %d" % (len(kept), len(dropped)))
for o, d in sorted(dropped, key=lambda t: -t[1])[:12]:
    c = sum([o.matrix_world @ Vector(x) for x in o.bound_box], Vector()) / 8.0
    print("   排除 %-38s 距中心 %.2f  位置(%.2f, %.2f, %.2f)" % (o.name[:38], d, c.x, c.y, c.z))

pts = []
for o, _ in kept:
    for c in o.bound_box:
        pts.append(o.matrix_world @ Vector(c))

xs = [p.x for p in pts]
ys = [p.y for p in pts]
zs = [p.z for p in pts]
lo = Vector((min(xs), min(ys), min(zs)))
hi = Vector((max(xs), max(ys), max(zs)))
center = (lo + hi) / 2.0
size = hi - lo

print("包围盒 min = (%.3f, %.3f, %.3f)" % (lo.x, lo.y, lo.z))
print("包围盒 max = (%.3f, %.3f, %.3f)" % (hi.x, hi.y, hi.z))
print("尺寸     = (%.3f, %.3f, %.3f)" % (size.x, size.y, size.z))

# ---------- 3. 正交相机 ----------
cam_data = bpy.data.cameras.new("OrthoCam")
cam_data.type = 'ORTHO'
cam = bpy.data.objects.new("OrthoCam", cam_data)
bpy.context.collection.objects.link(cam)
bpy.context.scene.camera = cam

# ---------- 4. 渲染设置 ----------
scene = bpy.context.scene
RES = 1024
scene.render.resolution_x = RES
scene.render.resolution_y = RES
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.image_settings.color_mode = 'RGB'
try:
    scene.render.engine = 'BLENDER_WORKBENCH'
except Exception as e:
    print("设置渲染引擎失败（可忽略）:", e)

# ---------- 5. 六个正交方向 ----------
views = {
    "front":  Vector((0.0, -1.0, 0.0)),
    "back":   Vector((0.0, 1.0, 0.0)),
    "right":  Vector((1.0, 0.0, 0.0)),
    "left":   Vector((-1.0, 0.0, 0.0)),
    "top":    Vector((0.0, 0.0, 1.0)),
    "bottom": Vector((0.0, 0.0, -1.0)),
}

dist = max(size.x, size.y, size.z) * 2.0
records = []

for name, d in views.items():
    cam.location = center + d * dist
    look = (center - cam.location).normalized()
    cam.rotation_euler = look.to_track_quat('-Z', 'Y').to_euler()

    if name in ("front", "back"):
        span = max(size.x, size.z)
    elif name in ("right", "left"):
        span = max(size.y, size.z)
    else:
        span = max(size.x, size.y)
    cam_data.ortho_scale = span * 1.05

    scene.render.filepath = os.path.join(OUT, name + ".png")
    bpy.ops.render.render(write_still=True)

    records.append({
        "name": name,
        "direction": [d.x, d.y, d.z],
        "location": [cam.location.x, cam.location.y, cam.location.z],
        "rotation_euler": [cam.rotation_euler.x, cam.rotation_euler.y, cam.rotation_euler.z],
        "ortho_scale": cam_data.ortho_scale,
        "resolution": RES,
    })
    print("已渲染: %s  (ortho_scale=%.4f)" % (name, cam_data.ortho_scale))

# ---------- 6. 记录相机参数 ----------
meta = {
    "experiment": "exp01_views",
    "blender": bpy.app.version_string,
    "model_objects": [o.name for o in objs],
    "bbox_min": [lo.x, lo.y, lo.z],
    "bbox_max": [hi.x, hi.y, hi.z],
    "center": [center.x, center.y, center.z],
    "size": [size.x, size.y, size.z],
    "resolution": RES,
    "views": records,
}

with open(os.path.join(OUT, "cameras.json"), "w", encoding="utf-8") as f:
    json.dump(meta, f, indent=2, ensure_ascii=False)

print("")
print("=" * 50)
print("完成。输出目录：")
print(OUT)
print("=" * 50)
