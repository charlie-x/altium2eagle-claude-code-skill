# -*- coding: utf-8 -*-
"""Render the generated EAGLE .sch to check symbol placement and rotation."""
import math, os
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Polygon as MPoly
import config as cfg

D = cfg.OUT_DIR
r = ET.parse(cfg.SCH_OUT).getroot()

sym = {s.get('name'): s for s in r.iter('symbol')}
parts = {p.get('name'): (p.get('deviceset'), p.get('value')) for p in r.iter('part')}
gates = {}
for d in r.iter('deviceset'):
    for g in d.iter('gate'):
        gates[(d.get('name'), g.get('name'))] = g.get('symbol')

fig, ax = plt.subplots(figsize=(30, 19), facecolor='white')
ax.set_facecolor('white')

def tf(x, y, ox, oy, rot):
    mir = rot.startswith('M')
    a = math.radians(float(rot.lstrip('MR')))
    if mir: x = -x
    return (ox + x * math.cos(a) - y * math.sin(a), oy + x * math.sin(a) + y * math.cos(a))

# nets
for net in r.iter('net'):
    for seg in net.iter('segment'):
        for w in seg.iter('wire'):
            ax.plot([float(w.get('x1')), float(w.get('x2'))],
                    [float(w.get('y1')), float(w.get('y2'))],
                    color='#128012', lw=0.7, zorder=2)
        for j in seg.iter('junction'):
            ax.add_patch(Circle((float(j.get('x')), float(j.get('y'))), 0.4,
                                color='#128012', zorder=3))
        for l in seg.iter('label'):
            rr = float((l.get('rot') or 'R0').lstrip('MR'))
            ax.text(float(l.get('x')), float(l.get('y')), net.get('name'),
                    color='#128012', fontsize=3.5, rotation=rr,
                    ha='left', va='bottom', zorder=6)

# instances
for inst in r.iter('instance'):
    pn = inst.get('part')
    if pn not in parts: continue
    dset, val = parts[pn]
    sname = gates.get((dset, inst.get('gate')))
    s = sym.get(sname)
    if s is None: continue
    ox, oy = float(inst.get('x')), float(inst.get('y'))
    rot = inst.get('rot') or 'R0'
    supply = dset.startswith('SUPPLY_')
    col = '#b00000' if supply else '#0050b0'
    for e in s:
        if e.tag == 'wire':
            p1 = tf(float(e.get('x1')), float(e.get('y1')), ox, oy, rot)
            p2 = tf(float(e.get('x2')), float(e.get('y2')), ox, oy, rot)
            ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color=col, lw=0.8, zorder=4)
        elif e.tag == 'circle':
            c = tf(float(e.get('x')), float(e.get('y')), ox, oy, rot)
            ax.add_patch(Circle(c, float(e.get('radius')), fill=False, ec=col, lw=0.7, zorder=4))
        elif e.tag == 'rectangle':
            x1, y1, x2, y2 = (float(e.get(k)) for k in ('x1', 'y1', 'x2', 'y2'))
            pts = [tf(a, b, ox, oy, rot) for a, b in
                   ((x1, y1), (x2, y1), (x2, y2), (x1, y2))]
            ax.add_patch(MPoly(pts, closed=True, fill=False, ec=col, lw=0.7, zorder=4))
        elif e.tag == 'polygon':
            pts = [tf(float(v.get('x')), float(v.get('y')), ox, oy, rot) for v in e]
            ax.add_patch(MPoly(pts, closed=True, fc=col, alpha=.5, ec=col, lw=0.5, zorder=4))
        elif e.tag == 'pin':
            px, py = float(e.get('x')), float(e.get('y'))
            L = {'point': 0, 'short': 2.54, 'middle': 5.08, 'long': 7.62}[e.get('length', 'short')]
            pr = math.radians(float((e.get('rot') or 'R0').lstrip('MR')))
            p1 = tf(px, py, ox, oy, rot)
            p2 = tf(px + L * math.cos(pr), py + L * math.sin(pr), ox, oy, rot)
            ax.plot([p1[0], p2[0]], [p1[1], p2[1]], color='#808000', lw=0.5, zorder=3)
            ax.add_patch(Circle(p1, 0.35, color='#d00000', zorder=7))   # connection point
    # name / value
    ax.text(ox, oy + (2.5 if not supply else -4.5), pn, color=col, fontsize=3.2,
            ha='center', zorder=6)
    if supply:
        ax.text(ox, oy - 6.2, val or '', color='#b00000', fontsize=3.2, ha='center', zorder=6)

ax.set_aspect('equal'); ax.axis('off'); ax.autoscale_view()
plt.tight_layout()
out = os.path.join(D, 'sch_check.png')
plt.savefig(out, dpi=170, facecolor='white')
print("wrote", out)
