# -*- coding: utf-8 -*-
"""Rebuild an Altium PCB as EAGLE 9 XML (Fusion Electronics interchange format)."""
import json, math, hashlib, re
from collections import defaultdict
from xml.sax.saxutils import escape

P = json.load(open('pcb.json'))
C = P['components']; NETS = P['nets']
MM = 0.0254                                   # mil -> mm
def nz(v):                                    # collapse -0.0 so it hashes/prints as 0.0
    v = v + 0.0
    return 0.0 if v == 0 else v
def q(v): return nz(round(v * MM, 6))
def r4(v): return nz(round(v, 4))
def r3(v): return nz(round(v, 3))

RELOCATE_STRAY_TEXT = False   # keep off-board source silkscreen 1:1; only report it

LMAP = {1: 1, 32: 16, 33: 21, 34: 22, 35: 31, 36: 32, 37: 29, 38: 30, 74: 1}
FLIP = {1: 16, 16: 1, 21: 22, 22: 21, 29: 30, 30: 29, 31: 32, 32: 31}
SHAPE = {1: 'round', 2: 'square', 3: 'octagon'}

def bot(ci): return C[ci]['layer'] == 'BOTTOM'
def rotpt(x, y, a):
    r = math.radians(a); c, s = math.cos(r), math.sin(r)
    return (x * c - y * s, x * s + y * c)

def to_local(ci, x, y):
    c = C[ci]
    lx, ly = rotpt(x - c['x'], y - c['y'], -c['rot'])
    if bot(ci): lx = -lx                      # EAGLE MR<a> mirrors package x, then rotates
    return lx, ly

def to_abs(ci, lx, ly):
    c = C[ci]
    if bot(ci): lx = -lx
    x, y = rotpt(lx, ly, c['rot'])
    return x + c['x'], y + c['y']

padsby, trkby, arcby, txtby = (defaultdict(list) for _ in range(4))
for p in P['pads']:
    if 0 <= p['comp'] < len(C): padsby[p['comp']].append(p)
for t in P['tracks']:
    if 0 <= t['comp'] < len(C): trkby[t['comp']].append(t)
for a in P['arcs']:
    if 0 <= a['comp'] < len(C): arcby[a['comp']].append(a)
for t in P['texts']:
    if 0 <= t['comp'] < len(C): txtby[t['comp']].append(t)
def free(o): return not (0 <= o['comp'] < len(C))

def arc_ends(cx, cy, r, a1, a2):
    return ((cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1))),
            (cx + r * math.cos(math.radians(a2)), cy + r * math.sin(math.radians(a2))))

# Altium permits several mechanical pads to share a name (e.g. "0" for a QFN
# thermal paddle); EAGLE requires unique pad names inside a package. Rename
# duplicates deterministically by package-local position and keep the original
# as 'base' so the schematic can tie the whole group to one pin.
for ci in list(padsby):
    seen = defaultdict(list)
    for p in padsby[ci]:
        p['base'] = p.get('base') or p['name']   # idempotent across re-runs
        p['name'] = p['base']
        seen[p['name']].append(p)
    for nm, ps in seen.items():
        if len(ps) == 1: continue
        for k, p in enumerate(sorted(ps, key=lambda p: tuple(r4(v) for v in to_local(ci, p['x'], p['y'])))):
            if k: p['name'] = '%s_%d' % (nm, k + 1)

# ---- packages ---------------------------------------------------------------
packages = {}
compkg = {}
maxerr = 0.0
slot_extra = defaultdict(list)   # (designator, pad) -> extra pad names in the package
for ci, c in enumerate(C):
    body, sg = [], []
    for p in sorted(padsby[ci], key=lambda p: (p['name'], p['x'], p['y'])):
        lx, ly = to_local(ci, p['x'], p['y'])
        lr = round((p['rot'] - c['rot']) % 360)
        sx, sy = (p['sy'], p['sx']) if lr in (90, 270) else (p['sx'], p['sy'])
        nm = escape(p['name'] or '?')
        aspect = max(sx, sy) / max(min(sx, sy), 1e-9)
        oval_th = (p['hole'] > 0 and p['shape'] == 1 and aspect >= 1.5)
        if oval_th:
            # USB-C shield/body legs: oblong copper with an oblong hole (a slot).
            # EAGLE's "long" pad is locked to a 2:1 stadium, which oversized the
            # 1.6 mm legs to 2.0 mm and blew out the pour void, so build the pad
            # explicitly: exact stadium copper on both sides plus a milling slot.
            ring = (min(sx, sy) - p['hole']) / 2.0
            slotw = p['hole']
            slotl = max(sx, sy) - 2 * ring
            half = max((slotl - slotw) / 2.0, 0.0)
            dxs, dys = (0.0, half) if sy > sx else (half, 0.0)
            # A real plated hole (so the drill survives into the NC-drill file),
            # the exact stadium copper on both sides, and the milling path that
            # stretches the round hole into the slot.
            body.append('<pad name="%s" x="%s" y="%s" drill="%s" diameter="%s" shape="round"/>'
                        % (nm, q(lx), q(ly), q(p['hole']), q(min(sx, sy))))
            body.append('<smd name="%sT" x="%s" y="%s" dx="%s" dy="%s" layer="1" roundness="100"/>'
                        % (nm, q(lx), q(ly), q(sx), q(sy)))
            body.append('<smd name="%sB" x="%s" y="%s" dx="%s" dy="%s" layer="16" roundness="100"/>'
                        % (nm, q(lx), q(ly), q(sx), q(sy)))
            body.append('<wire x1="%s" y1="%s" x2="%s" y2="%s" width="%s" layer="46"/>'
                        % (q(lx - dxs), q(ly - dys), q(lx + dxs), q(ly + dys), q(slotw)))
            sg.append(('slot', r4(lx), r4(ly), r4(sx), r4(sy), r4(slotw), r4(slotl)))
            slot_extra['%s %s' % (c['des'], p['name'])] += ['%sT' % p['name'], '%sB' % p['name']]
            ax, ay = to_abs(ci, lx, ly)
            maxerr = max(maxerr, math.hypot(ax - p['x'], ay - p['y']))
        elif p['hole'] > 0 or p['layer'] == 74:
            # Altium shape 1 is the round family: a circle when X==Y, an oval
            # otherwise. Shape 2 is a rectangle, 3 an octagon. EAGLE has no
            # arbitrary-aspect pad, so an oval maps to "long" (a fixed 2:1
            # stadium) oriented along its major axis, and a rectangle to
            # "square" -- never the other way round.
            prot = ''
            if p['shape'] == 2:
                shp, dia = 'square', max(sx, sy)
            elif p['shape'] == 3:
                shp, dia = 'octagon', max(sx, sy)
            elif aspect < 1.5:
                # near-circular: EAGLE's "long" is a fixed 2:1 stadium and would
                # be far worse than a circle at these aspect ratios
                shp, dia = 'round', max(sx, sy)
            else:
                shp, dia = 'long', min(sx, sy)
                if sy > sx: prot = ' rot="R90"'
            body.append('<pad name="%s" x="%s" y="%s" drill="%s" diameter="%s" shape="%s"%s/>'
                        % (nm, q(lx), q(ly), q(p['hole']), q(dia), shp, prot))
        else:
            body.append('<smd name="%s" x="%s" y="%s" dx="%s" dy="%s" layer="1" roundness="%d"/>'
                        % (nm, q(lx), q(ly), q(sx), q(sy), 100 if p['shape'] == 1 else 0))
        sg.append((nm, r4(lx), r4(ly), r4(sx), r4(sy), p['shape'], r4(p['hole'])))
        ax, ay = to_abs(ci, lx, ly)
        maxerr = max(maxerr, math.hypot(ax - p['x'], ay - p['y']))

    for t in trkby[ci]:
        L = LMAP.get(t['layer']) or (20 if t['layer'] in (56, 57) else None)
        if L is None: continue
        if bot(ci): L = FLIP.get(L, L)
        x1, y1 = to_local(ci, t['x1'], t['y1']); x2, y2 = to_local(ci, t['x2'], t['y2'])
        body.append('<wire x1="%s" y1="%s" x2="%s" y2="%s" width="%s" layer="%d"/>'
                    % (q(x1), q(y1), q(x2), q(y2), q(max(t['w'], 0.1)), L))
        sg.append(('w',) + tuple(sorted([(r4(x1), r4(y1)), (r4(x2), r4(y2))])) + (r4(t['w']), L))

    for a in arcby[ci]:
        L = LMAP.get(a['layer']) or (20 if a['layer'] in (56, 57) else None)
        if L is None: continue
        if bot(ci): L = FLIP.get(L, L)
        cx, cy = to_local(ci, a['cx'], a['cy'])
        sweep = a['a2'] - a['a1']
        if abs(abs(sweep) - 360) < 1e-6 or abs(sweep) < 1e-9:
            body.append('<circle x="%s" y="%s" radius="%s" width="%s" layer="%d"/>'
                        % (q(cx), q(cy), q(a['r']), q(max(a['w'], 0.1)), L))
            sg.append(('c', r4(cx), r4(cy), r4(a['r']), L))
        else:
            a1, a2 = a['a1'], a['a2']
            if bot(ci): a1, a2 = 180 - a['a2'], 180 - a['a1']
            a1 -= c['rot']; a2 -= c['rot']
            p1, p2 = arc_ends(cx, cy, a['r'], a1, a2)
            body.append('<wire x1="%s" y1="%s" x2="%s" y2="%s" width="%s" layer="%d" curve="%s"/>'
                        % (q(p1[0]), q(p1[1]), q(p2[0]), q(p2[1]), q(max(a['w'], 0.1)), L,
                           round((a2 - a1) % 360, 4)))
            sg.append(('a', r4(cx), r4(cy), r4(a['r']), r3(a1), r3(a2), L))

    body.append('<text x="0" y="0" size="0.6096" layer="25" ratio="10" align="center">&gt;NAME</text>')
    key = hashlib.md5(repr(sorted(sg, key=repr)).encode()).hexdigest()[:6]
    base = ''.join(ch for ch in (c['pat'] or 'PKG') if ch.isalnum() or ch in '._-+') or 'PKG'
    name = base
    if name in packages and packages[name][1] != key:
        name = '%s_%s' % (base, key)
    packages.setdefault(name, (body, key))
    compkg[ci] = name

print("packages: %d   max pad round-trip error: %.6g mil" % (len(packages), maxerr))
assert maxerr < 0.01, "element placement transform does not reproduce Altium pad coordinates"

# ---- signals (free routing) --------------------------------------------------
sig = defaultdict(lambda: {'contact': [], 'wire': [], 'via': []})
for ci, ps in padsby.items():
    for p in ps:
        if 0 <= p['net'] < len(NETS):
            n = NETS[p['net']]
            sig[n]['contact'].append((C[ci]['des'], p['name']))
            for x in slot_extra.get('%s %s' % (C[ci]['des'], p['name']), []):
                sig[n]['contact'].append((C[ci]['des'], x))
NON = '__nonet'
CU = {1: 1, 32: 16, 74: 1}                    # only copper may live inside <signal>

# Altium saves the *rendered result* of a hatched polygon pour as thousands of
# net-less 8 mil tracks on an 8 mil grid. They are output, not source geometry:
# importing them yields a "ground pour made of horizontal lines" and dumps every
# one of them into a bogus no-net signal. Drop them and let the <polygon> in the
# GND signal regenerate the fill instead.
def is_pour_fill(o):
    return o['layer'] in CU and free(o) and not (0 <= o['net'] < len(NETS))
dropped = sum(1 for t in P['tracks'] if is_pour_fill(t)) + \
          sum(1 for a in P['arcs'] if is_pour_fill(a))

for t in P['tracks']:
    if t['layer'] not in CU or not free(t) or is_pour_fill(t): continue
    n = NETS[t['net']] if 0 <= t['net'] < len(NETS) else NON
    sig[n]['wire'].append('<wire x1="%s" y1="%s" x2="%s" y2="%s" width="%s" layer="%d"/>'
                          % (q(t['x1']), q(t['y1']), q(t['x2']), q(t['y2']), q(t['w']), CU[t['layer']]))
for a in P['arcs']:
    if a['layer'] not in CU or not free(a) or is_pour_fill(a): continue
    n = NETS[a['net']] if 0 <= a['net'] < len(NETS) else NON
    sweep = a['a2'] - a['a1']
    if abs(abs(sweep) - 360) < 1e-6: continue
    p1, p2 = arc_ends(a['cx'], a['cy'], a['r'], a['a1'], a['a2'])
    sig[n]['wire'].append('<wire x1="%s" y1="%s" x2="%s" y2="%s" width="%s" layer="%d" curve="%s"/>'
                          % (q(p1[0]), q(p1[1]), q(p2[0]), q(p2[1]), q(a['w']), CU[a['layer']],
                             round(sweep % 360, 4)))
for v in P['vias']:
    n = NETS[v['net']] if 0 <= v['net'] < len(NETS) else NON
    sig[n]['via'].append('<via x="%s" y="%s" extent="1-16" drill="%s" diameter="%s"/>'
                         % (q(v['x']), q(v['y']), q(v['hole']), q(v['dia'])))
# Altium Fills are literal solid copper, not pour outlines. Emitting them as
# <polygon> inside a signal makes them subject to re-pour (and to keep-out
# voiding), which is what made the 2.4 GHz antenna arms come out unfilled.
# <rectangle> on a copper layer is unconditional copper, so use that.
extraPlain = []
for f in P['fills']:
    if f['layer'] not in LMAP: continue
    x1, x2 = sorted((f['x1'], f['x2'])); y1, y2 = sorted((f['y1'], f['y2']))
    extraPlain.append('<rectangle x1="%s" y1="%s" x2="%s" y2="%s" layer="%d"/>'
                      % (q(x1), q(y1), q(x2), q(y2), LMAP[f['layer']]))

# KIND=1 regions are copper keep-outs (the NFC coil area and the 2.4 GHz antenna
# clearance). EAGLE pours respect tRestrict/bRestrict, so map them there.
for r in P.get('regions', []):
    if not r['verts']: continue
    verts = ''.join('<vertex x="%s" y="%s"/>' % (q(a), q(b)) for a, b in r['verts'])
    if r['kind'] == '1':
        lays = (41, 42) if r['layer'] == 74 else ((41,) if r['layer'] == 1 else
                                                 ((42,) if r['layer'] == 32 else ()))
        for L in lays:
            extraPlain.append('<polygon width="0" layer="%d">%s</polygon>' % (L, verts))
    elif r['kind'] == '0' and r['layer'] in LMAP:
        extraPlain.append('<polygon width="0" layer="%d">%s</polygon>' % (LMAP[r['layer']], verts))

# ---- component silkscreen text ----------------------------------------------
# Altium positions each designator per component (R13's sits 128 mil left of the
# part, R15's 128 mil above), so it cannot live in the shared package. EAGLE's
# equivalent is a smashed element: >NAME broken out as an <attribute> on the
# element itself. Any other text a component owns (values, polarity marks) is
# kept verbatim as free silkscreen.
_bx = [v for t in P['tracks'] if t['layer'] == 56 for v in (t['x1'], t['x2'])]
_by = [v for t in P['tracks'] if t['layer'] == 56 for v in (t['y1'], t['y2'])]
BB = (min(_bx) - 500, min(_by) - 500, max(_bx) + 500, max(_by) + 500)
strays = []

nameattr = {}
owntext = []
for ci, ts in txtby.items():
    des = C[ci]['des']
    for t in ts:
        if t['layer'] not in LMAP or not t['text'].strip(): continue
        L = LMAP[t['layer']]
        # The source can contain silkscreen parked far off the board (this design
        # has one: E1's "ANTENNA" sits ~22 in to the right). Default is to keep it
        # 1:1 and just report it -- the conversion should not quietly move source
        # geometry. Set RELOCATE_STRAY_TEXT to pull outliers back to their part.
        if not (BB[0] <= t['x'] <= BB[2] and BB[1] <= t['y'] <= BB[3]):
            strays.append((des, t['text'], t['x'], t['y']))
            if RELOCATE_STRAY_TEXT:
                t = dict(t, x=C[ci]['x'], y=C[ci]['y'])
        if t.get('kind') == 1 and ci not in nameattr:
            nameattr[ci] = dict(x=q(t['x']), y=q(t['y']), size=q(max(t['h'], 20)),
                                rot=t.get('rot', 0) % 360, layer=25 if L == 21 else 26,
                                mirror=bool(t.get('mirror')))
        else:
            owntext.append(dict(ci=ci, text=t['text'], x=q(t['x']), y=q(t['y']),
                                size=q(max(t['h'], 20)), rot=t.get('rot', 0) % 360,
                                layer=L, mirror=bool(t.get('mirror'))))

# ---- plain (outline + free silkscreen) --------------------------------------
plain = list(extraPlain)
for t in P['tracks']:
    if t['layer'] == 56 and free(t):
        plain.append('<wire x1="%s" y1="%s" x2="%s" y2="%s" width="0.2032" layer="20"/>'
                     % (q(t['x1']), q(t['y1']), q(t['x2']), q(t['y2'])))
for a in P['arcs']:
    if a['layer'] != 56 or not free(a): continue
    sweep = a['a2'] - a['a1']
    p1, p2 = arc_ends(a['cx'], a['cy'], a['r'], a['a1'], a['a2'])
    if abs(abs(sweep) - 360) < 1e-6:
        plain.append('<circle x="%s" y="%s" radius="%s" width="0.2032" layer="20"/>'
                     % (q(a['cx']), q(a['cy']), q(a['r'])))
    else:
        plain.append('<wire x1="%s" y1="%s" x2="%s" y2="%s" width="0.2032" layer="20" curve="%s"/>'
                     % (q(p1[0]), q(p1[1]), q(p2[0]), q(p2[1]), round(sweep % 360, 4)))
for t in P['tracks']:
    if t['layer'] in (33, 34) and free(t):
        plain.append('<wire x1="%s" y1="%s" x2="%s" y2="%s" width="%s" layer="%d"/>'
                     % (q(t['x1']), q(t['y1']), q(t['x2']), q(t['y2']), q(max(t['w'], 0.1)), LMAP[t['layer']]))
for a in P['arcs']:
    if a['layer'] not in (33, 34) or not free(a): continue
    sweep = a['a2'] - a['a1']
    p1, p2 = arc_ends(a['cx'], a['cy'], a['r'], a['a1'], a['a2'])
    if abs(abs(sweep) - 360) < 1e-6:
        plain.append('<circle x="%s" y="%s" radius="%s" width="%s" layer="%d"/>'
                     % (q(a['cx']), q(a['cy']), q(a['r']), q(max(a['w'], 0.1)), LMAP[a['layer']]))
    else:
        plain.append('<wire x1="%s" y1="%s" x2="%s" y2="%s" width="%s" layer="%d" curve="%s"/>'
                     % (q(p1[0]), q(p1[1]), q(p2[0]), q(p2[1]), q(max(a['w'], 0.1)),
                        LMAP[a['layer']], round(sweep % 360, 4)))
for t in P['texts']:
    if t['layer'] not in (33, 34) or not free(t) or not t['text'].strip(): continue
    plain.append('<text x="%s" y="%s" size="%s" layer="%d" ratio="10" rot="%sR%g">%s</text>'
                 % (q(t['x']), q(t['y']), q(max(t['h'], 20)), LMAP[t['layer']],
                    'M' if t.get('mirror') else '', t.get('rot', 0) % 360, escape(t['text'])))

json.dump(P, open('pcb.json', 'w'))          # persist the uniquified pad names
pkgpads = {n: re.findall(r'<(?:pad|smd) name="([^"]+)"', ''.join(v[0]))
           for n, v in packages.items()}
pat2pkg = {}
for ci, c in enumerate(C):
    pat2pkg.setdefault(c['pat'], compkg[ci])
json.dump({'compkg': {str(k): v for k, v in compkg.items()},
           'pkgpads': pkgpads, 'pat2pkg': pat2pkg, 'slot_extra': dict(slot_extra),
           'packages': {k: v[0] for k, v in packages.items()},
           'signals': dict(sig), 'plain': plain,
           'nameattr': {str(k): v for k, v in nameattr.items()},
           'owntext': owntext}, open('brdparts.json', 'w'))
print("dropped %d poured-hatch fill primitives (regenerated by the GND polygon)" % dropped)
for d,txt,x,y in strays:
    print("  %s off-board silkscreen %r of %s at (%.0f, %.0f) mil"
          % ("RELOCATED" if RELOCATE_STRAY_TEXT else "kept 1:1:", txt, d, x, y))
print("plain primitives: %d   signals: %d   copper-bearing: %d"
      % (len(plain), len(sig), sum(1 for v in sig.values() if v['wire'] or v['via'])))
