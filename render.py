# -*- coding: utf-8 -*-
"""Render the generated EAGLE .brd by resolving element/package transforms."""
import math, os, sys
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle, Polygon as MPoly
import config as cfg

D = cfg.OUT_DIR
r = ET.parse(cfg.BRD_OUT).getroot()
pk = {p.get('name'): p for p in r.iter('package')}

COL = {'1': '#c0392b', '16': '#2471a3', '21': '#e8e8e8', '22': '#909090',
       '20': '#f1c40f', '29': None, '30': None, '31': None, '32': None}

fig, ax = plt.subplots(figsize=(22, 13), facecolor='#101418')
ax.set_facecolor('#101418')

def arcpts(x1, y1, x2, y2, curve):
    a = math.radians(curve)
    dx, dy = x2 - x1, y2 - y1
    d = math.hypot(dx, dy)
    if d < 1e-12 or abs(a) < 1e-12: return [(x1, y1), (x2, y2)]
    rr = d / (2 * math.sin(abs(a) / 2))
    h = math.sqrt(max(rr * rr - d * d / 4, 0))
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    ux, uy = -dy / d, dx / d
    s = 1 if curve > 0 else -1
    if abs(curve) > 180: h = -h
    cx, cy = mx + s * ux * h, my + s * uy * h
    t1 = math.atan2(y1 - cy, x1 - cx); t2 = math.atan2(y2 - cy, x2 - cx)
    if s > 0 and t2 < t1: t2 += 2 * math.pi
    if s < 0 and t2 > t1: t2 -= 2 * math.pi
    n = max(8, int(abs(curve) / 5))
    return [(cx + rr * math.cos(t1 + (t2 - t1) * i / n), cy + rr * math.sin(t1 + (t2 - t1) * i / n))
            for i in range(n + 1)]

def draw_wire(e, tf, layer=None):
    L = layer or e.get('layer')
    c = COL.get(L)
    if not c: return
    x1, y1 = tf(float(e.get('x1')), float(e.get('y1')))
    x2, y2 = tf(float(e.get('x2')), float(e.get('y2')))
    w = float(e.get('width')) or 0.05
    cur = e.get('curve')
    if cur:
        p0 = (float(e.get('x1')), float(e.get('y1'))); p1 = (float(e.get('x2')), float(e.get('y2')))
        pts = [tf(a, b) for a, b in arcpts(p0[0], p0[1], p1[0], p1[1], float(cur))]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], color=c, lw=max(w * 3, 0.3),
                solid_capstyle='round', zorder=2)
    else:
        ax.plot([x1, x2], [y1, y2], color=c, lw=max(w * 3, 0.3), solid_capstyle='round', zorder=2)

def ident(x, y): return (x, y)

# ---- ground pour (drawn first, then keep-outs masked over it) ----
for sg in r.iter('signal'):
    for e in sg:
        if e.tag == 'polygon' and e.get('layer') in ('1', '16'):
            pts = [(float(v.get('x')), float(v.get('y'))) for v in e]
            ax.add_patch(MPoly(pts, closed=True, fc='#c0392b' if e.get('layer')=='1' else '#2471a3',
                               alpha=0.18, ec='none', zorder=0.5))
for e in r.find('drawing/board/plain'):
    if e.get('layer') in ('41', '42'):      # tRestrict / bRestrict: pour keep-out
        pts = [(float(v.get('x')), float(v.get('y'))) for v in e]
        ax.add_patch(MPoly(pts, closed=True, fc='#101418', ec='#f39c12', lw=.8,
                           ls='--', zorder=1.0))

# ---- board plain ----
for e in r.find('drawing/board/plain'):
    if e.tag == 'rectangle':
        c = COL.get(e.get('layer'))
        if c:
            x1,y1,x2,y2 = (float(e.get(k)) for k in ('x1','y1','x2','y2'))
            ax.add_patch(Rectangle((x1,y1), x2-x1, y2-y1, fc=c, ec='none', zorder=4))
    elif e.tag == 'polygon' and e.get('layer') in COL and COL[e.get('layer')]:
        pts = [(float(v.get('x')), float(v.get('y'))) for v in e]
        ax.add_patch(MPoly(pts, closed=True, fc=COL[e.get('layer')], ec='none', alpha=.9, zorder=3))
    elif e.tag == 'wire': draw_wire(e, ident)
    elif e.tag == 'circle':
        c = COL.get(e.get('layer'))
        if c: ax.add_patch(Circle((float(e.get('x')), float(e.get('y'))), float(e.get('radius')),
                                  fill=False, ec=c, lw=max(float(e.get('width')) * 3, .3), zorder=2))

# ---- signals ----
for s in r.iter('signal'):
    for e in s:
        if e.tag == 'wire': draw_wire(e, ident)
        elif e.tag == 'via':
            ax.add_patch(Circle((float(e.get('x')), float(e.get('y'))), float(e.get('diameter')) / 2,
                                color='#7f8c8d', zorder=3))
            ax.add_patch(Circle((float(e.get('x')), float(e.get('y'))), float(e.get('drill')) / 2,
                                color='#101418', zorder=4))


# ---- elements ----
for el in r.iter('element'):
    ox, oy = float(el.get('x')), float(el.get('y'))
    rot = el.get('rot') or 'R0'
    mir = rot.startswith('M')
    ang = math.radians(float(rot.lstrip('MR')))
    ca, sa = math.cos(ang), math.sin(ang)
    def tf(lx, ly, ox=ox, oy=oy, ca=ca, sa=sa, mir=mir):
        if mir: lx = -lx
        return (ox + lx * ca - ly * sa, oy + lx * sa + ly * ca)
    p = pk.get(el.get('package'))
    if p is None: continue
    for e in p:
        if e.tag == 'wire': draw_wire(e, tf)
        elif e.tag == 'circle':
            c = COL.get(e.get('layer'))
            if c:
                cx, cy = tf(float(e.get('x')), float(e.get('y')))
                ax.add_patch(Circle((cx, cy), float(e.get('radius')), fill=False, ec=c,
                                    lw=max(float(e.get('width')) * 3, .3), zorder=2))
        elif e.tag in ('smd', 'pad'):
            lx, ly = float(e.get('x')), float(e.get('y'))
            cx, cy = tf(lx, ly)
            if e.tag == 'smd':
                dx, dy = float(e.get('dx')), float(e.get('dy'))
                col = '#e67e22' if e.get('layer') == '1' else '#5dade2'
                pts = []
                for sx, sy in ((-dx/2,-dy/2),(dx/2,-dy/2),(dx/2,dy/2),(-dx/2,dy/2)):
                    rx, ry = (sx*ca - sy*sa, sx*sa + sy*ca)
                    pts.append((cx+rx, cy+ry))
                ax.add_patch(MPoly(pts, closed=True, color=col, zorder=5))
            else:
                d = float(e.get('diameter', 0.6))
                ax.add_patch(Circle((cx, cy), d/2, color='#f39c12', zorder=5))
                ax.add_patch(Circle((cx, cy), float(e.get('drill'))/2, color='#101418', zorder=6))

ax.set_aspect('equal'); ax.axis('off')
ax.autoscale_view()
plt.tight_layout()
out = os.path.join(D, 'board_check.png')
plt.savefig(out, dpi=110, facecolor='#101418')
print("wrote", out)
