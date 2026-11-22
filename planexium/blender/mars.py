"""PLANEXIUM · Day 3 · MARS DIDN'T DIE. SOMETHING KILLED IT.

Fully procedural Blender scene (no textures to download). Renders the
30-second, 9:16 simulation with NO text. The meter and hook are added later by
render_short.py.

Timeline (30 fps, 900 frames) — matches the meter in shorts.json:
  0-3 s   ancient blue Mars: oceans, clouds, blue atmosphere, magnetic shield
  3-8 s   the magnetic shield flickers and collapses
  6-24 s  solar wind streams in from the Sun side; atmosphere, clouds and
          oceans fade; surface turns rust red
  24-30 s today's dead red Mars, slow push-in (reveal happens here)

Run (Blender 4.2 or newer, tested on 5.3):
  blender -b -P mars.py -- --out ./mars_frames/
  blender -b -P mars.py -- --preview            # 540x960, 1 frame in 10, fast check
  blender -b -P mars.py -- --engine EEVEE       # much faster, slightly less real
  blender -b -P mars.py -- --frames 1 900 --samples 128

Then:
  ffmpeg -framerate 30 -i mars_frames/%04d.png -c:v libx264 -crf 16 -pix_fmt yuv420p mars_clip.mp4
  python3 render_short.py mars --bg mars_clip.mp4 -o out/mars_final.mp4
"""
import argparse
import math
import os
import sys

import bpy

FPS = 30
TOTAL = 900


def sec(s):
    return int(round(s * FPS)) + 1


# ---------------------------------------------------------------- args
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--out", default="//mars_frames/")
ap.add_argument("--engine", default="CYCLES", choices=["CYCLES", "EEVEE"])
ap.add_argument("--samples", type=int, default=96)
ap.add_argument("--preview", action="store_true", help="540x960, every 10th frame")
ap.add_argument("--frames", type=int, nargs=2, default=[1, TOTAL])
ap.add_argument("--no-render", action="store_true", help="only build the scene (and save .blend)")
ap.add_argument("--save-blend", default="")
args = ap.parse_args(argv)

# ---------------------------------------------------------------- reset
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.frame_start, scene.frame_end = args.frames
scene.render.fps = FPS


def value_node(nt, name, pairs, loc=(-900, 0)):
    n = nt.nodes.new("ShaderNodeValue")
    n.label = name
    n.location = loc
    out = n.outputs[0]
    for s, v in pairs:
        out.default_value = v
        out.keyframe_insert("default_value", frame=sec(s))
    return out


def mix_rgb(nt, fac, a, b, loc=(0, 0)):
    m = nt.nodes.new("ShaderNodeMix")
    m.data_type = "RGBA"
    m.location = loc
    ins = [i for i in m.inputs if i.type == "RGBA"]
    fac_in = m.inputs["Factor"] if "Factor" in m.inputs else m.inputs[0]
    link_or_set(nt, fac_in, fac)
    link_or_set(nt, ins[0], a)
    link_or_set(nt, ins[1], b)
    out = [o for o in m.outputs if o.type == "RGBA"][0]
    return out


def link_or_set(nt, sock, v):
    if isinstance(v, bpy.types.NodeSocket):
        nt.links.new(v, sock)
    else:
        sock.default_value = v


def math_node(nt, op, a, b=None, loc=(0, 0), clamp=False):
    n = nt.nodes.new("ShaderNodeMath")
    n.operation = op
    n.use_clamp = clamp
    n.location = loc
    link_or_set(nt, n.inputs[0], a)
    if b is not None:
        link_or_set(nt, n.inputs[1], b)
    return n.outputs[0]


def principled_input(bsdf, *names):
    for nm in names:
        if nm in bsdf.inputs:
            return bsdf.inputs[nm]
    raise KeyError(names)


# ---------------------------------------------------------------- render settings
r = scene.render
if args.preview:
    r.resolution_x, r.resolution_y = 540, 960
    scene.frame_step = 10
else:
    r.resolution_x, r.resolution_y = 1080, 1920
r.resolution_percentage = 100
r.image_settings.file_format = "PNG"
r.filepath = args.out
r.film_transparent = False

if args.engine == "CYCLES":
    r.engine = "CYCLES"
    c = scene.cycles
    c.samples = 24 if args.preview else args.samples
    c.use_denoising = True
    c.max_bounces = 6
    c.volume_bounces = 1
    # use any GPU that is present (OptiX > CUDA > HIP > Metal > oneAPI), else CPU
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        for backend in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
            try:
                prefs.compute_device_type = backend
                prefs.get_devices()
                if any(d.type != "CPU" for d in prefs.devices):
                    for d in prefs.devices:
                        d.use = True
                    c.device = "GPU"
                    print(f"[planexium] Cycles on GPU via {backend}")
                    break
            except Exception:
                continue
    except Exception as e:  # pragma: no cover
        print("[planexium] GPU setup skipped:", e)
else:
    for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        try:
            r.engine = eng
            break
        except TypeError:
            continue
    try:
        scene.eevee.taa_render_samples = 16 if args.preview else 64
    except AttributeError:
        pass

# Filmic/AgX look, a touch of contrast for that NASA-render feel
try:
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Punchy"
except TypeError:
    scene.view_settings.view_transform = "Filmic"
scene.view_settings.exposure = 0.2

# direction TOWARD the sun: front-right-above the camera so ~3/4 of the disc is lit
from mathutils import Vector
SUN_DIR = Vector((1.0, -0.9, 0.45)).normalized()

# ---------------------------------------------------------------- world: deep space + stars
world = bpy.data.worlds.new("Space")
scene.world = world
world.use_nodes = True
wn = world.node_tree
wn.nodes.clear()
w_out = wn.nodes.new("ShaderNodeOutputWorld")
w_bg = wn.nodes.new("ShaderNodeBackground")
w_tc = wn.nodes.new("ShaderNodeTexCoord")
w_vor = wn.nodes.new("ShaderNodeTexVoronoi")
w_vor.feature = "F1"
w_vor.inputs["Scale"].default_value = 900
wn.links.new(w_tc.outputs["Generated"], w_vor.inputs["Vector"])
# star = tiny distance to cell point
star = math_node(wn, "LESS_THAN", w_vor.outputs["Distance"], 0.045)
w_noise = wn.nodes.new("ShaderNodeTexWhiteNoise")
w_noise.noise_dimensions = "3D"
wn.links.new(w_vor.outputs["Position"], w_noise.inputs["Vector"])
bright = math_node(wn, "POWER", w_noise.outputs["Value"], 6.0)
star_i = math_node(wn, "MULTIPLY", star, bright)
star_i = math_node(wn, "MULTIPLY", star_i, 6.0)
wn.links.new(star_i, w_bg.inputs["Strength"])
w_bg.inputs["Color"].default_value = (1.0, 0.97, 0.93, 1)
wn.links.new(w_bg.outputs[0], w_out.inputs[0])

# ---------------------------------------------------------------- the planet
bpy.ops.mesh.primitive_uv_sphere_add(segments=256, ring_count=128, radius=1.0, location=(0, 0, 0))
mars = bpy.context.active_object
mars.name = "Mars"
bpy.ops.object.shade_smooth()
mars.rotation_euler = (math.radians(25), 0, 0)
# axial spin over 30 s
mars.rotation_euler[2] = 0
mars.keyframe_insert("rotation_euler", index=2, frame=1)
mars.rotation_euler[2] = math.radians(55)
mars.keyframe_insert("rotation_euler", index=2, frame=TOTAL)

mat = bpy.data.materials.new("MarsSurface")
mat.use_nodes = True
nt = mat.node_tree
nt.nodes.clear()
out = nt.nodes.new("ShaderNodeOutputMaterial")
out.location = (1400, 0)
bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
bsdf.location = (1100, 0)
nt.links.new(bsdf.outputs[0], out.inputs["Surface"])

tc = nt.nodes.new("ShaderNodeTexCoord")
tc.location = (-1400, 0)

# "death" 0 -> 1: water/air loss. Matches AIR PRESSURE meter 6 s -> 24 s.
death = value_node(nt, "death", [(0, 0.0), (6, 0.0), (24, 1.0), (30, 1.0)])

# continents: big fractal noise = height
hn = nt.nodes.new("ShaderNodeTexNoise")
hn.location = (-1100, 200)
hn.inputs["Scale"].default_value = 1.6
hn.inputs["Detail"].default_value = 14
hn.inputs["Roughness"].default_value = 0.58
if "Lacunarity" in hn.inputs:
    hn.inputs["Lacunarity"].default_value = 2.2
nt.links.new(tc.outputs["Object"], hn.inputs["Vector"])
height = hn.outputs["Fac"]

# crater-ish detail
cr = nt.nodes.new("ShaderNodeTexVoronoi")
cr.location = (-1100, -200)
cr.inputs["Scale"].default_value = 22
nt.links.new(tc.outputs["Object"], cr.inputs["Vector"])

# sea level falls as death rises: 0.53 -> 0.30 (oceans retreat into basins, then vanish)
sea = math_node(nt, "MULTIPLY_ADD", death, -0.26, loc=(-800, 400))
sea_node = sea.node
sea_node.inputs[2].default_value = 0.5
is_water = math_node(nt, "LESS_THAN", height, sea, loc=(-600, 300))
# when death ~1 there is no liquid at all
alive = math_node(nt, "SUBTRACT", 1.0, death, loc=(-600, 500), clamp=True)
alive = math_node(nt, "POWER", alive, 0.6, loc=(-450, 500))
water = math_node(nt, "MULTIPLY", is_water, alive, loc=(-400, 300))
water = math_node(nt, "MINIMUM", water, 1.0, loc=(-300, 300))

# land colour: ochre/olive early -> rust today, varies with height
ramp_young = nt.nodes.new("ShaderNodeValToRGB")
ramp_young.location = (-700, 0)
cr_y = ramp_young.color_ramp
cr_y.elements[0].position, cr_y.elements[0].color = 0.35, (0.20, 0.16, 0.10, 1)
cr_y.elements[1].position, cr_y.elements[1].color = 0.75, (0.52, 0.40, 0.26, 1)
nt.links.new(height, ramp_young.inputs["Fac"])

ramp_dead = nt.nodes.new("ShaderNodeValToRGB")
ramp_dead.location = (-700, -250)
cr_d = ramp_dead.color_ramp
cr_d.elements[0].position, cr_d.elements[0].color = 0.25, (0.20, 0.045, 0.015, 1)
e = cr_d.elements.new(0.5)
e.color = (0.55, 0.15, 0.04, 1)
cr_d.elements[1].position, cr_d.elements[1].color = 0.8, (0.80, 0.38, 0.17, 1)
alb = nt.nodes.new("ShaderNodeTexNoise")
alb.inputs["Scale"].default_value = 4.0
alb.inputs["Detail"].default_value = 6
nt.links.new(tc.outputs["Object"], alb.inputs["Vector"])
dead_fac = math_node(nt, "MULTIPLY", alb.outputs["Fac"], 0.9)
dead_fac = math_node(nt, "ADD", dead_fac, height)
dead_fac = math_node(nt, "SUBTRACT", dead_fac, 0.45)
nt.links.new(dead_fac, ramp_dead.inputs["Fac"])

land = mix_rgb(nt, death, ramp_young.outputs["Color"], ramp_dead.outputs["Color"], loc=(-300, -100))
# ocean colour: deep -> shallow by depth
ocean_ramp = nt.nodes.new("ShaderNodeValToRGB")
ocean_ramp.location = (-700, 600)
o = ocean_ramp.color_ramp
o.elements[0].position, o.elements[0].color = 0.2, (0.005, 0.02, 0.08, 1)
o.elements[1].position, o.elements[1].color = 0.55, (0.02, 0.12, 0.25, 1)
nt.links.new(height, ocean_ramp.inputs["Fac"])
# polar ice caps
geo_z = nt.nodes.new("ShaderNodeSeparateXYZ")
geo_z.location = (-1100, -500)
nt.links.new(tc.outputs["Object"], geo_z.inputs[0])
absz = math_node(nt, "ABSOLUTE", geo_z.outputs["Z"], loc=(-900, -500))
ice_line = math_node(nt, "MULTIPLY_ADD", death, 0.04, loc=(-900, -650))
ice_line.node.inputs[2].default_value = 0.93
ice = math_node(nt, "SUBTRACT", math_node(nt, "ADD", absz, math_node(nt, "MULTIPLY", height, 0.12)), ice_line, loc=(-700, -500))
ice = math_node(nt, "MULTIPLY", ice, 40.0, clamp=True)  # soft edge

base = mix_rgb(nt, water, land, ocean_ramp.outputs["Color"], loc=(0, 100))
base = mix_rgb(nt, ice, base, (0.80, 0.80, 0.82, 1), loc=(250, 100))
nt.links.new(base, principled_input(bsdf, "Base Color"))

rough = math_node(nt, "MULTIPLY_ADD", water, -0.75, loc=(300, -200))
rough.node.inputs[2].default_value = 0.92
nt.links.new(rough, principled_input(bsdf, "Roughness"))

# relief
bump = nt.nodes.new("ShaderNodeBump")
bump.location = (800, -300)
bump.inputs["Strength"].default_value = 0.35
bump.inputs["Distance"].default_value = 0.02
relief = math_node(nt, "ADD", height, math_node(nt, "MULTIPLY", cr.outputs["Distance"], 0.25), loc=(600, -300))
relief = math_node(nt, "MULTIPLY", relief, math_node(nt, "SUBTRACT", 1.0, water), loc=(700, -300))
nt.links.new(relief, bump.inputs["Height"])
nt.links.new(bump.outputs["Normal"], principled_input(bsdf, "Normal"))
mars.data.materials.append(mat)

# ---------------------------------------------------------------- clouds
bpy.ops.mesh.primitive_uv_sphere_add(segments=128, ring_count=64, radius=1.012)
clouds = bpy.context.active_object
clouds.name = "Clouds"
bpy.ops.object.shade_smooth()
clouds.rotation_euler = (math.radians(25), 0, 0)
clouds.keyframe_insert("rotation_euler", index=2, frame=1)
clouds.rotation_euler[2] = math.radians(80)
clouds.keyframe_insert("rotation_euler", index=2, frame=TOTAL)
cm = bpy.data.materials.new("Clouds")
cm.use_nodes = True
cn = cm.node_tree
cn.nodes.clear()
c_out = cn.nodes.new("ShaderNodeOutputMaterial")
c_tc = cn.nodes.new("ShaderNodeTexCoord")
c_noise = cn.nodes.new("ShaderNodeTexNoise")
c_noise.inputs["Scale"].default_value = 3.5
c_noise.inputs["Detail"].default_value = 10
c_noise.inputs["Roughness"].default_value = 0.62
cn.links.new(c_tc.outputs["Object"], c_noise.inputs["Vector"])
c_amt = value_node(cn, "cloud_amount", [(0, 1.0), (6, 1.0), (17, 0.0), (30, 0.0)])
# threshold rises as clouds vanish
thr = math_node(cn, "MULTIPLY_ADD", c_amt, -0.22)
thr.node.inputs[2].default_value = 0.78
cov = math_node(cn, "SUBTRACT", c_noise.outputs["Fac"], thr)
cov = math_node(cn, "MULTIPLY", cov, 6.0, clamp=True)
cov = math_node(cn, "MULTIPLY", cov, c_amt)
c_white = cn.nodes.new("ShaderNodeBsdfDiffuse")
c_white.inputs["Color"].default_value = (0.95, 0.95, 0.97, 1)
c_tr = cn.nodes.new("ShaderNodeBsdfTransparent")
c_mix = cn.nodes.new("ShaderNodeMixShader")
cn.links.new(cov, c_mix.inputs[0])
cn.links.new(c_tr.outputs[0], c_mix.inputs[1])
cn.links.new(c_white.outputs[0], c_mix.inputs[2])
cn.links.new(c_mix.outputs[0], c_out.inputs["Surface"])
try:
    cm.blend_method = "HASHED"
except Exception:
    pass
clouds.data.materials.append(cm)

# ---------------------------------------------------------------- atmosphere rim
def rim_shell(name, radius, color_pairs, strength_pairs, power=4.0):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=128, ring_count=64, radius=radius)
    ob = bpy.context.active_object
    ob.name = name
    bpy.ops.object.shade_smooth()
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    t = m.node_tree
    t.nodes.clear()
    o = t.nodes.new("ShaderNodeOutputMaterial")
    lw = t.nodes.new("ShaderNodeLayerWeight")
    lw.inputs["Blend"].default_value = 0.5
    facing = math_node(t, "POWER", lw.outputs["Facing"], power)
    # glow only on the day side, fading across the terminator
    geo = t.nodes.new("ShaderNodeNewGeometry")
    dp = t.nodes.new("ShaderNodeVectorMath")
    dp.operation = "DOT_PRODUCT"
    t.links.new(geo.outputs["Normal"], dp.inputs[0])
    dp.inputs[1].default_value = SUN_DIR
    lit = math_node(t, "MULTIPLY_ADD", dp.outputs["Value"], 0.9)
    lit.node.inputs[2].default_value = 0.45
    lit.node.use_clamp = True
    facing = math_node(t, "MULTIPLY", facing, lit)
    em = t.nodes.new("ShaderNodeEmission")
    col = t.nodes.new("ShaderNodeRGB")
    for s, c in color_pairs:
        col.outputs[0].default_value = c
        col.outputs[0].keyframe_insert("default_value", frame=sec(s))
    t.links.new(col.outputs[0], em.inputs["Color"])
    stren = value_node(t, name + "_strength", strength_pairs)
    t.links.new(math_node(t, "MULTIPLY", facing, stren), em.inputs["Strength"])
    tr = t.nodes.new("ShaderNodeBsdfTransparent")
    add = t.nodes.new("ShaderNodeAddShader")
    t.links.new(tr.outputs[0], add.inputs[0])
    t.links.new(em.outputs[0], add.inputs[1])
    t.links.new(add.outputs[0], o.inputs["Surface"])
    try:
        m.blend_method = "BLEND"
    except Exception:
        pass
    ob.data.materials.append(m)
    if hasattr(ob, "visible_shadow"):
        ob.visible_shadow = False
    return ob


rim_shell("Atmosphere", 1.03,
          [(0, (0.25, 0.55, 1.0, 1)), (14, (0.45, 0.5, 0.75, 1)), (24, (0.9, 0.55, 0.35, 1))],
          [(0, 9.0), (6, 9.0), (24, 0.5), (30, 0.4)], power=7.0)

# magnetic shield: big faint cyan bubble that flickers and dies 3-8 s
shield = rim_shell("MagneticShield", 1.75,
                   [(0, (0.2, 0.9, 1.0, 1))],
                   [(0, 0.9), (3, 0.9), (3.6, 0.2), (4.1, 1.1), (4.8, 0.1), (5.4, 0.8), (6.3, 0.05), (7.2, 0.3), (8, 0.0), (30, 0.0)],
                   power=10.0)

# ---------------------------------------------------------------- sun + solar wind
sun = bpy.data.lights.new("Sun", type="SUN")
sun.energy = 4.5
sun.angle = math.radians(0.6)
sun.color = (1.0, 0.96, 0.9)
sun_ob = bpy.data.objects.new("Sun", sun)
scene.collection.objects.link(sun_ob)
sun_ob.rotation_euler = (-SUN_DIR).to_track_quat("-Z", "Y").to_euler()

# streak particle: a stretched glowing capsule
bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, radius=1, location=(0, 0, -50))
streak = bpy.context.active_object
streak.name = "WindStreak"
streak.scale = (0.5, 0.0035, 0.0035)
sm = bpy.data.materials.new("Wind")
sm.use_nodes = True
s_nt = sm.node_tree
s_nt.nodes.clear()
s_out = s_nt.nodes.new("ShaderNodeOutputMaterial")
s_em = s_nt.nodes.new("ShaderNodeEmission")
s_em.inputs["Color"].default_value = (1.0, 0.82, 0.55, 1)
wind_strength = value_node(s_nt, "wind", [(0, 0.0), (5, 0.0), (8, 2.2), (21, 2.2), (25, 0.0), (30, 0.0)])
s_nt.links.new(wind_strength, s_em.inputs["Strength"])
s_tr = s_nt.nodes.new("ShaderNodeBsdfTransparent")
s_add = s_nt.nodes.new("ShaderNodeAddShader")
s_nt.links.new(s_tr.outputs[0], s_add.inputs[0])
s_nt.links.new(s_em.outputs[0], s_add.inputs[1])
s_nt.links.new(s_add.outputs[0], s_out.inputs["Surface"])
streak.data.materials.append(sm)

# emitter plane far on the sun side, particles fly toward -X past the planet
bpy.ops.mesh.primitive_plane_add(size=1, location=tuple(SUN_DIR * 8))
emitter = bpy.context.active_object
emitter.rotation_euler = SUN_DIR.to_track_quat("Z", "Y").to_euler()  # plane normal faces the sun
emitter.name = "SolarWindEmitter"
emitter.scale = (4.5, 4.5, 1)
ps_mod = emitter.modifiers.new("wind", "PARTICLE_SYSTEM")
ps = ps_mod.particle_system.settings
ps.count = 3500
ps.frame_start = sec(4)
ps.frame_end = sec(23)
ps.lifetime = 75
ps.emit_from = "FACE"
ps.normal_factor = -7.0  # metres / second toward the planet
ps.factor_random = 0.01
ps.physics_type = "NEWTON"
ps.effector_weights.gravity = 0
ps.render_type = "OBJECT"
ps.instance_object = streak
ps.particle_size = 1.0
ps.size_random = 0.6
ps.use_rotations = True
ps.rotation_mode = "VEL"
ps.use_dynamic_rotation = False
emitter.show_instancer_for_render = False

# stripped atmosphere wisps: faint blue streaks leaving the night side 8-22 s
bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, radius=1, location=(0, 0, -50))
wisp = bpy.context.active_object
wisp.name = "Wisp"
wisp.scale = (0.25, 0.006, 0.006)
wm = bpy.data.materials.new("Wisp")
wm.use_nodes = True
w2 = wm.node_tree
w2.nodes.clear()
w2o = w2.nodes.new("ShaderNodeOutputMaterial")
w2e = w2.nodes.new("ShaderNodeEmission")
w2e.inputs["Color"].default_value = (0.35, 0.6, 1.0, 1)
w2s = value_node(w2, "wisp", [(0, 0.0), (8, 0.0), (11, 6.0), (20, 6.0), (24, 0.0), (30, 0.0)])
w2.links.new(w2s, w2e.inputs["Strength"])
w2t = w2.nodes.new("ShaderNodeBsdfTransparent")
w2a = w2.nodes.new("ShaderNodeAddShader")
w2.links.new(w2t.outputs[0], w2a.inputs[0])
w2.links.new(w2e.outputs[0], w2a.inputs[1])
w2.links.new(w2a.outputs[0], w2o.inputs["Surface"])
wisp.data.materials.append(wm)

bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1.05)
loss = bpy.context.active_object
loss.name = "AtmosphereLossEmitter"
lp_mod = loss.modifiers.new("loss", "PARTICLE_SYSTEM")
lp = lp_mod.particle_system.settings
lp.count = 4000
lp.frame_start = sec(8)
lp.frame_end = sec(22)
lp.lifetime = 60
lp.emit_from = "FACE"
lp.normal_factor = 0.35
lp.object_align_factor = tuple(-SUN_DIR * 1.8)  # swept away from the sun
lp.factor_random = 0.03
lp.physics_type = "NEWTON"
lp.effector_weights.gravity = 0
lp.render_type = "OBJECT"
lp.instance_object = wisp
lp.size_random = 0.5
lp.use_rotations = True
lp.rotation_mode = "VEL"
loss.show_instancer_for_render = False

# glowing streaks never cast shadows on the planet
for ob in (streak, wisp):
    ob.visible_shadow = False
    if hasattr(ob, "visible_diffuse"):
        ob.visible_diffuse = False
        ob.visible_glossy = False

# ---------------------------------------------------------------- camera: slow orbit + push-in
cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 50
cam_data.sensor_fit = "VERTICAL"
cam_data.sensor_height = 36
cam = bpy.data.objects.new("Cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam

target = bpy.data.objects.new("CamTarget", None)
scene.collection.objects.link(target)
target.location = (0, 0, -0.25)  # planet sits slightly above centre, below the hook text
track = cam.constraints.new("TRACK_TO")
track.target = target
track.track_axis = "TRACK_NEGATIVE_Z"
track.up_axis = "UP_Y"

for s, (dist, ang, z) in [(0, (7.6, -18, 0.6)), (12, (7.0, -10, 0.5)), (24, (6.2, -2, 0.4)), (30, (5.6, 2, 0.35))]:
    a = math.radians(ang)
    cam.location = (dist * math.sin(a), -dist * math.cos(a), z)
    cam.keyframe_insert("location", frame=sec(s))

# make every animation curve ease smoothly
for ob in list(bpy.data.objects) + list(bpy.data.materials) + list(bpy.data.worlds):
    ad = getattr(ob, "animation_data", None)
    nt_ = getattr(ob, "node_tree", None)
    for holder in (ad, getattr(nt_, "animation_data", None) if nt_ else None):
        if holder and holder.action and hasattr(holder.action, "fcurves"):
            for fc in holder.action.fcurves:
                for kp in fc.keyframe_points:
                    kp.interpolation = "BEZIER"
                    kp.easing = "EASE_IN_OUT"

# ---------------------------------------------------------------- go
os.makedirs(bpy.path.abspath(args.out) if args.out.startswith("//") else args.out, exist_ok=True)
if args.save_blend:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.save_blend))
# bake the particle sims so any frame range renders the same (e.g. split across machines)
try:
    for ob in (emitter, loss):
        cache = ob.particle_systems[0].point_cache
        cache.frame_start, cache.frame_end = 1, TOTAL
    with bpy.context.temp_override(scene=scene):
        bpy.ops.ptcache.bake_all(bake=True)
    print("[planexium] particles baked")
except Exception as e:
    print("[planexium] particle bake skipped (render the full range in one go):", e)

if not args.no_render:
    print(f"[planexium] rendering frames {scene.frame_start}-{scene.frame_end} -> {r.filepath}")
    bpy.ops.render.render(animation=True)
    print("[planexium] done")
