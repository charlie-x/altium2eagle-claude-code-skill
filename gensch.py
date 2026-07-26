# -*- coding: utf-8 -*-
"""Rebuild an Altium schematic as EAGLE 9 XML, cross-linked to the board."""
import json, math, hashlib
from collections import defaultdict
from xml.sax.saxutils import escape

R = json.load(open('sch.json'))
PCB = json.load(open('pcb.json'))
BRD = json.load(open('brdparts.json'))
C = PCB['components']; NETS = PCB['nets']
compkg = {int(k): v for k, v in BRD['compkg'].items()}
pkg_of_des = {C[i]['des']: compkg[i] for i in range(len(C))}
PKGPADS = BRD['pkgpads']; PAT2PKG = BRD['pat2pkg']

U = 0.254                                    # schematic unit (10 mil) -> mm
def nz(v):
    v = v + 0.0
    return 0.0 if v == 0 else v
def q(v): return nz(round(v * U, 6))
def r3(v): return nz(round(v, 3))

def f(d, k, dv=0.0):
    try: return float(d.get(k, dv))
    except: return dv
def I(d, k, dv=0):
    try: return int(float(d.get(k, dv)))
    except: return dv
def own(r): return I(r, 'OWNERINDEX', -2) + 1
def mode0(r): return r.get('OWNERPARTDISPLAYMODE') in (None, '0')

comps = {i: r for i, r in enumerate(R) if r.get('RECORD') == '1'}
des, comment = {}, {}
for r in R:
    o = own(r)
    if o not in comps: continue
    if r.get('RECORD') == '34': des[o] = r.get('TEXT', '')
    if r.get('RECORD') == '41' and r.get('NAME') == 'Comment': comment[o] = r.get('TEXT', '')

# PCBLIB implementation (record 45) -> the footprint Altium assigned each part
fpof = {}
for r in R:
    if r.get('RECORD') != '45' or r.get('MODELTYPE') != 'PCBLIB': continue
    if r.get('ISCURRENT') != 'T': continue
    o = own(r)                                  # owner is the implementation list (44)
    if 0 <= o < len(R) and R[o].get('RECORD') == '44':
        ci = I(R[o], 'OWNERINDEX', -2) + 1
        if ci in comps: fpof[ci] = r.get('MODELNAME', '')

ORI = {0: (1, 0), 1: (0, 1), 2: (-1, 0), 3: (0, -1)}
pins = defaultdict(list)
for r in R:
    if r.get('RECORD') != '2' or not mode0(r): continue
    o = own(r)
    if o not in comps: continue
    x, y = f(r, 'LOCATION.X'), f(r, 'LOCATION.Y'); L = f(r, 'PINLENGTH')
    ori = I(r, 'PINCONGLOMERATE') & 3
    dx, dy = ORI[ori]
    pins[o].append(dict(des=r.get('DESIGNATOR', ''), name=r.get('NAME', ''),
                        x=x, y=y, ox=x + dx * L, oy=y + dy * L, L=L, ori=ori,
                        elec=I(r, 'ELECTRICAL')))
GFXR = {'13', '14', '6', '7', '12', '11'}
gfx = defaultdict(list)
for r in R:
    if r.get('RECORD') in GFXR and mode0(r) and own(r) in comps:
        gfx[own(r)].append(r)

def rotpt(x, y, a):
    t = math.radians(a); c, s = math.cos(t), math.sin(t)
    return (x * c - y * s, x * s + y * c)
def local(ci, x, y):
    c = comps[ci]
    a = I(c, 'ORIENTATION') * 90
    lx, ly = rotpt(x - f(c, 'LOCATION.X'), y - f(c, 'LOCATION.Y'), -a)
    if c.get('ISMIRRORED') == 'T': lx = -lx
    return lx, ly

PLEN = [(0, 'point'), (10, 'short'), (20, 'middle'), (30, 'long')]
def plen(v):
    return min(PLEN, key=lambda t: abs(t[0] - v))[1]

# ---- symbols -----------------------------------------------------------------
# extra pads present on the board but absent from the schematic symbol
extra = defaultdict(set)
padnames = defaultdict(set)
padgroup = defaultdict(lambda: defaultdict(list))   # designator -> base -> [unique pad names]
SLOT_EXTRA = BRD.get('slot_extra', {})
for p in PCB['pads']:
    if 0 <= p['comp'] < len(C):
        d = C[p['comp']]['des']
        padnames[d].add(p['name'])
        padgroup[d][p.get('base', p['name'])].append(p['name'])
        # slot pads carry a second copper shape on the bottom layer
        for x in SLOT_EXTRA.get('%s %s' % (d, p['name']), []):
            padnames[d].add(x)
            padgroup[d][p.get('base', p['name'])].append(x)
for ci, c in comps.items():
    d = des.get(ci)
    if d not in padnames: continue
    have = {p['des'] for p in pins[ci]}
    for base in padgroup[d]:
        if base not in have:
            extra[c.get('LIBREFERENCE', '')].add(base)

symbols, symof = {}, {}
pinname = {}                       # ci -> {pad designator: unique EAGLE pin name}
for ci, c in comps.items():
    cnt = defaultdict(int)
    for p in pins[ci]: cnt[p['name'] or p['des']] += 1
    pinname[ci] = {p['des']: ((p['name'] or p['des']) if cnt[p['name'] or p['des']] == 1
                              else '%s@%s' % (p['name'] or p['des'], p['des']))
                   for p in pins[ci]}
for ci, c in comps.items():
    body, sg, extrapins = [], [], []
    for p in sorted(pins[ci], key=lambda p: p['des']):
        lx, ly = local(ci, p['ox'], p['oy'])
        rot = (p['ori'] * 90 + 180) % 360
        if c.get('ISMIRRORED') == 'T': rot = (180 - rot) % 360
        rot = (rot - I(c, 'ORIENTATION') * 90) % 360
        body.append('<pin name="%s" x="%s" y="%s" length="%s" rot="R%d" visible="both"/>'
                    % (escape(pinname[ci][p['des']]), q(lx), q(ly), plen(p['L']), rot))
        sg.append(('p', pinname[ci][p['des']], r3(lx), r3(ly), rot))
    ys = [local(ci, p['ox'], p['oy'])[1] for p in pins[ci]] or [0]
    y0 = min(ys) - 20
    for k, pad in enumerate(sorted(extra.get(c.get('LIBREFERENCE', ''), ()))):
        lx, ly = -10.0, y0 - 10 * k
        body.append('<pin name="P$%s" x="%s" y="%s" length="short" rot="R0" visible="both"/>'
                    % (escape(pad), q(lx), q(ly)))
        sg.append(('p', 'X' + pad, r3(lx), r3(ly), 0))
        extrapins.append((pad, 'P$' + pad, lx, ly))
    for r in gfx[ci]:
        t = r.get('RECORD')
        if t == '13':
            x1, y1 = local(ci, f(r, 'LOCATION.X'), f(r, 'LOCATION.Y'))
            x2, y2 = local(ci, f(r, 'CORNER.X'), f(r, 'CORNER.Y'))
            body.append('<wire x1="%s" y1="%s" x2="%s" y2="%s" width="0.254" layer="94"/>'
                        % (q(x1), q(y1), q(x2), q(y2)))
            sg.append(('l', r3(x1), r3(y1), r3(x2), r3(y2)))
        elif t == '14':
            x1, y1 = local(ci, f(r, 'LOCATION.X'), f(r, 'LOCATION.Y'))
            x2, y2 = local(ci, f(r, 'CORNER.X'), f(r, 'CORNER.Y'))
            # draw the component body as an outline, per EAGLE symbol convention
            ax, bx = min(x1, x2), max(x1, x2)
            ay, by = min(y1, y2), max(y1, y2)
            for (u1, v1), (u2, v2) in zip([(ax, ay), (bx, ay), (bx, by), (ax, by)],
                                          [(bx, ay), (bx, by), (ax, by), (ax, ay)]):
                body.append('<wire x1="%s" y1="%s" x2="%s" y2="%s" width="0.254" layer="94"/>'
                            % (q(u1), q(v1), q(u2), q(v2)))
            sg.append(('r', r3(min(x1, x2)), r3(min(y1, y2)), r3(max(x1, x2)), r3(max(y1, y2))))
        elif t in ('6', '7'):
            n = I(r, 'LOCATIONCOUNT')
            pts = [local(ci, f(r, 'X%d' % k), f(r, 'Y%d' % k)) for k in range(1, n + 1)]
            if len(pts) < 2: continue
            if t == '7':
                body.append('<polygon width="0.254" layer="94">%s</polygon>'
                            % ''.join('<vertex x="%s" y="%s"/>' % (q(a), q(b)) for a, b in pts))
            else:
                for a, b in zip(pts, pts[1:]):
                    body.append('<wire x1="%s" y1="%s" x2="%s" y2="%s" width="0.254" layer="94"/>'
                                % (q(a[0]), q(a[1]), q(b[0]), q(b[1])))
            sg.append((t, tuple((r3(a), r3(b)) for a, b in pts)))
        elif t in ('12', '11'):
            cx, cy = local(ci, f(r, 'LOCATION.X'), f(r, 'LOCATION.Y'))
            rad = f(r, 'RADIUS') or f(r, 'SECONDARYRADIUS') or 2.0
            body.append('<circle x="%s" y="%s" radius="%s" width="0.254" layer="94"/>'
                        % (q(cx), q(cy), q(rad)))
            sg.append(('e', r3(cx), r3(cy), r3(rad)))
    body.append('<text x="0" y="%s" size="1.778" layer="95">&gt;NAME</text>' % q(max(ys) + 5))
    body.append('<text x="0" y="%s" size="1.778" layer="96">&gt;VALUE</text>' % q(min(ys) - 8))
    key = hashlib.md5(repr(sorted(sg, key=repr)).encode()).hexdigest()[:6]
    base = ''.join(ch for ch in (c.get('LIBREFERENCE', '') or 'SYM') if ch.isalnum() or ch in '._-+') or 'SYM'
    nm = base
    if nm in symbols and symbols[nm][1] != key: nm = '%s_%s' % (base, key)
    symbols.setdefault(nm, (body, key, extrapins))
    symof[ci] = nm

# ---- devicesets --------------------------------------------------------------
devsets = defaultdict(dict)          # symbol -> {device name: (package, connects)}
devof = {}
for ci, c in comps.items():
    d = des.get(ci)
    sym = symof[ci]
    pk = pkg_of_des.get(d)
    conn = []
    groups = padgroup.get(d, {})
    if pk is None:
        # unfitted part: no board element, so take the footprint Altium recorded
        # for it and connect pins to that package's pads by designator
        pk = PAT2PKG.get(fpof.get(ci) or '')
        if pk:
            groups = {p: [p] for p in PKGPADS.get(pk, [])}
    for p in pins[ci]:
        pads = groups.get(p['des'])
        if pads:
            conn.append('<connect gate="G$1" pin="%s" pad="%s"/>'
                        % (escape(pinname[ci][p['des']]), escape(' '.join(sorted(pads)))))
    for base, epname, _, _ in symbols[sym][2]:
        pads = groups.get(base)
        if pads:
            conn.append('<connect gate="G$1" pin="%s" pad="%s"/>'
                        % (escape(epname), escape(' '.join(sorted(pads)))))
    # parts not placed on the board (unfitted) still need a package-less device
    dn = ('-' + pk) if pk else ''
    devsets[sym][dn] = (pk, conn)
    devof[ci] = dn

json.dump({'pinname': {str(k): v for k, v in pinname.items()},
           'symbols': {k: v[0] for k, v in symbols.items()},
           'extrapins': {k: v[2] for k, v in symbols.items()},
           'symof': {str(k): v for k, v in symof.items()},
           'devof': {str(k): v for k, v in devof.items()},
           'devsets': {k: {dn: [pk, cs] for dn, (pk, cs) in v.items()} for k, v in devsets.items()},
           'des': {str(k): v for k, v in des.items()},
           'comment': {str(k): v for k, v in comment.items()}},
          open('schparts.json', 'w'))
print("symbols: %d   devicesets: %d   parts: %d" % (len(symbols), len(devsets), len(comps)))
print("synthetic pins added for board-only pads: %s" % dict(extra))
