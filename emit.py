# -*- coding: utf-8 -*-
"""Emit the cross-linked EAGLE 9 .sch / .brd / .lbr set (paths in config.py)."""
import json, math, os
from collections import defaultdict
from xml.sax.saxutils import escape
import config as cfg

OUT = cfg.OUT_DIR
LIB = cfg.LIB
R = json.load(open('sch.json'))
PCB = json.load(open('pcb.json'))
BRD = json.load(open('brdparts.json'))
SCH = json.load(open('schparts.json'))
C = PCB['components']; NETS = PCB['nets']
U = 0.254
def q(v): return round(v * U, 6)

def f(d, k, dv=0.0):
    try: return float(d.get(k, dv))
    except: return dv
def I(d, k, dv=0):
    try: return int(float(d.get(k, dv)))
    except: return dv
def own(r): return I(r, 'OWNERINDEX', -2) + 1
def mode0(r): return r.get('OWNERPARTDISPLAYMODE') in (None, '0')

comps = {i: r for i, r in enumerate(R) if r.get('RECORD') == '1'}
des = {int(k): v for k, v in SCH['des'].items()}
comment = {int(k): v for k, v in SCH['comment'].items()}
symof = {int(k): v for k, v in SCH['symof'].items()}
devof = {int(k): v for k, v in SCH['devof'].items()}
pinname = {int(k): v for k, v in SCH['pinname'].items()}
compkg = {int(k): v for k, v in BRD['compkg'].items()}

# ---------------- schematic connectivity -------------------------------------
ORI = {0: (1, 0), 1: (0, 1), 2: (-1, 0), 3: (0, -1)}
pins = []
for r in R:
    if r.get('RECORD') != '2' or not mode0(r): continue
    o = own(r)
    if o not in comps: continue
    x, y = f(r, 'LOCATION.X'), f(r, 'LOCATION.Y'); L = f(r, 'PINLENGTH')
    dx, dy = ORI[I(r, 'PINCONGLOMERATE') & 3]
    pins.append(dict(ci=o, des=des.get(o, '?'), pin=r.get('DESIGNATOR', ''),
                     ox=x + dx * L, oy=y + dy * L))
wires = []
for r in R:
    if r.get('RECORD') != '27': continue
    n = I(r, 'LOCATIONCOUNT')
    pts = [(f(r, 'X%d' % k), f(r, 'Y%d' % k)) for k in range(1, n + 1)]
    wires += list(zip(pts, pts[1:]))
par = {}
def find(a):
    par.setdefault(a, a)
    while par[a] != a: par[a] = par[par[a]]; a = par[a]
    return a
def uni(a, b):
    ra, rb = find(a), find(b)
    if ra != rb: par[ra] = rb
for a, b in wires: uni(a, b)
def onseg(p, a, b, e=1e-6):
    (px, py), (ax, ay), (bx, by) = p, a, b
    if abs((bx - ax) * (py - ay) - (by - ay) * (px - ax)) > 1e-6: return False
    return min(ax, bx) - e <= px <= max(ax, bx) + e and min(ay, by) - e <= py <= max(ay, by) + e
labels = [(r.get('TEXT', ''), (f(r, 'LOCATION.X'), f(r, 'LOCATION.Y'))) for r in R if r.get('RECORD') == '25']
labrot = {(f(r, 'LOCATION.X'), f(r, 'LOCATION.Y')): I(r, 'ORIENTATION') * 90
          for r in R if r.get('RECORD') == '25'}
powers = [(r.get('TEXT', ''), (f(r, 'LOCATION.X'), f(r, 'LOCATION.Y'))) for r in R if r.get('RECORD') == '17']
# Altium power ports are symbols (GND bar, supply arrow) anchored at their
# connection point, not text. Keep style/orientation so they can be rebuilt as
# EAGLE supply symbols rather than a stray net-name string beside the wire.
powinfo = [(r.get('TEXT', ''), (f(r, 'LOCATION.X'), f(r, 'LOCATION.Y')),
            I(r, 'ORIENTATION'), I(r, 'STYLE'))
           for r in R if r.get('RECORD') == '17']
juncs = [(f(r, 'LOCATION.X'), f(r, 'LOCATION.Y')) for r in R if r.get('RECORD') == '29']
cand = {(p['ox'], p['oy']) for p in pins} | {p for _, p in labels + powers} | set(juncs)
for c in cand:
    for a, b in wires:
        if onseg(c, a, b): uni(c, a); uni(c, b)
# `find` above is purely geometric: one group per physically connected piece of
# wire. Same-named labels/power ports also join nets, but in EAGLE that must be
# expressed as several <segment>s sharing one <net name> -- putting unconnected
# wires in a single segment is what makes ERC report nets as broken apart. So
# keep the geometric groups for segments and merge them separately for naming.
par2 = {}
def find2(a):
    par2.setdefault(a, a)
    while par2[a] != a: par2[a] = par2[par2[a]]; a = par2[a]
    return a
def uni2(a, b):
    ra, rb = find2(a), find2(b)
    if ra != rb: par2[ra] = rb
byname = defaultdict(list)
for t, p in labels + powers: byname[t].append(p)
for t, pts in byname.items():
    for p2 in pts[1:]: uni2(find(pts[0]), find(p2))

grp = defaultdict(list)                    # geometric group -> pins (segments)
for p in pins: grp[find((p['ox'], p['oy']))].append(p)
mgrp = defaultdict(list)                   # name-merged group -> pins (naming)
for p in pins: mgrp[find2(find((p['ox'], p['oy'])))].append(p)
gnames = defaultdict(set)
for t, p in labels + powers: gnames[find2(find(p))].add(t)

pcbnet = defaultdict(set)
for p in PCB['pads']:
    if 0 <= p['comp'] < len(C) and 0 <= p['net'] < len(NETS):
        pcbnet[NETS[p['net']]].add((C[p['comp']]['des'], p['name']))
placed = {c['des'] for c in C}
gsets = {g: {(p['des'], p['pin']) for p in ps if p['des'] in placed} for g, ps in mgrp.items()}
pairs = []
for g, s_ in gsets.items():
    for n, cs in pcbnet.items():
        ov = len(s_ & cs)
        if ov: pairs.append((ov, -len(s_ ^ cs), repr(g), g, n))
pairs.sort(reverse=True)
netof = {}; used = set()
for ov, _, _, g, n in pairs:
    if g in netof or n in used: continue
    netof[g] = n; used.add(n)
auto = 0
allm = set(mgrp) | {find2(find(p)) for _, p in labels + powers} | {find2(find(a)) for a, b in wires}
for g in allm:
    if g in netof: continue
    nm = sorted(gnames.get(g, []))
    if nm: netof[g] = nm[0]
    else:
        auto += 1; netof[g] = 'N$%d' % auto
# every geometric group inherits the name of the merged group it belongs to
nameof = {}
for g in set(grp) | {find(p) for _, p in labels + powers} | {find(a) for a, b in wires}:
    nameof[g] = netof.get(find2(g))

# ---------------- schematic net XML -------------------------------------------
segs = defaultdict(list)          # net name -> list of segment xml
gwires = defaultdict(list)
for a, b in wires: gwires[find(a)].append((a, b))
gjunc = defaultdict(list)
for j in juncs: gjunc[find(j)].append(j)
glabel = defaultdict(list)
for t, p in labels: glabel[find(p)].append((t, p))   # power ports become symbols, not labels
for g in set(list(gwires) + list(grp)):
    n = nameof.get(g)
    if not n: continue
    s = []
    for (a, b) in gwires.get(g, []):
        s.append('<wire x1="%s" y1="%s" x2="%s" y2="%s" width="0.1524" layer="91"/>'
                 % (q(a[0]), q(a[1]), q(b[0]), q(b[1])))
    for p in grp.get(g, []):
        s.append('<pinref part="%s" gate="G$1" pin="%s"/>'
                 % (escape(p['des']), escape(pinname[p['ci']][p['pin']])))
    for j in gjunc.get(g, []):
        s.append('<junction x="%s" y="%s"/>' % (q(j[0]), q(j[1])))
    for t, p in glabel.get(g, []):
        rr = labrot.get(p, 0) % 360
        s.append('<label x="%s" y="%s" size="1.778" layer="95" rot="R%d"/>'
                 % (q(p[0]), q(p[1]), rr))
    if s: segs[n].append('<segment>%s</segment>' % ''.join(s))

# synthetic pins for board-only pads (shields / mounting), wired to their board net
netofpad = {}
for p in PCB['pads']:
    if 0 <= p['comp'] < len(C) and 0 <= p['net'] < len(NETS):
        netofpad[(C[p['comp']]['des'], p.get('base', p['name']))] = NETS[p['net']]
extrapins = SCH['extrapins']
for ci, sym in symof.items():
    for pad, epname, lx, ly in extrapins.get(sym, []):
        d = des.get(ci)
        n = netofpad.get((d, pad))
        if not n: continue
        c = comps[ci]
        ax = f(c, 'LOCATION.X') + lx; ay = f(c, 'LOCATION.Y') + ly
        segs[n].append('<segment><pinref part="%s" gate="G$1" pin="%s"/>'
                       '<wire x1="%s" y1="%s" x2="%s" y2="%s" width="0.1524" layer="91"/>'
                       '<label x="%s" y="%s" size="1.778" layer="95"/></segment>'
                       % (escape(d), escape(epname), q(ax), q(ay), q(ax - 10), q(ay),
                          q(ax - 10), q(ay)))

# ---------------- supply symbols (from Altium power ports) --------------------
# Drawn pointing down (Altium ORIENTATION 3) with the connection point at the
# symbol origin, so the EAGLE instance rotation maps straight from Altium's.
SUP_ROT = {3: 0, 0: 90, 1: 180, 2: 270}
supsym, supparts, supinst = {}, [], []
supref = defaultdict(list)                     # geometric group -> [(part, pin)]
_n = defaultdict(int)
for t, p, ori, style in powinfo:
    if not t: continue
    nm = ''.join(ch for ch in t if ch.isalnum() or ch in '._-+') or 'SUP'
    if nm not in supsym:
        if style == 4:                         # ground: stacked bars
            art = ('<wire x1="0" y1="0" x2="0" y2="-1.27" width="0.254" layer="94"/>'
                   '<wire x1="-1.27" y1="-1.27" x2="1.27" y2="-1.27" width="0.254" layer="94"/>'
                   '<wire x1="-0.762" y1="-1.778" x2="0.762" y2="-1.778" width="0.254" layer="94"/>'
                   '<wire x1="-0.254" y1="-2.286" x2="0.254" y2="-2.286" width="0.254" layer="94"/>')
            tx = '<text x="0" y="-3.302" size="1.778" layer="96" align="center">&gt;VALUE</text>'
        else:                                  # rail: single bar
            art = ('<wire x1="0" y1="0" x2="0" y2="-1.27" width="0.254" layer="94"/>'
                   '<wire x1="-1.27" y1="-1.27" x2="1.27" y2="-1.27" width="0.254" layer="94"/>')
            tx = '<text x="0" y="-2.54" size="1.778" layer="96" align="center">&gt;VALUE</text>'
        supsym[nm] = ('<symbol name="SUPPLY_%s">'
                      '<pin name="%s" x="0" y="0" visible="off" length="point" direction="sup"/>'
                      '%s%s</symbol>' % (escape(nm), escape(t), art, tx))
    _n[nm] += 1
    pname = '%s%d' % (nm, _n[nm])
    supparts.append('<part name="%s" library="%s" deviceset="SUPPLY_%s" device="" value="%s"/>'
                    % (escape(pname), LIB, escape(nm), escape(t)))
    supinst.append('<instance part="%s" gate="G$1" x="%s" y="%s" rot="R%d"/>'
                   % (escape(pname), q(p[0]), q(p[1]), SUP_ROT.get(ori, 0)))
    supref[find(p)].append((pname, t))
supdev = ''.join('<deviceset name="SUPPLY_%s" prefix="SUPPLY"><gates>'
                 '<gate name="G$1" symbol="SUPPLY_%s" x="0" y="0"/></gates>'
                 '<devices><device name=""><technologies><technology name=""/></technologies>'
                 '</device></devices></deviceset>' % (escape(k), escape(k)) for k in sorted(supsym))
# attach each supply pin to the net segment it sits on
for g, refs in supref.items():
    n = nameof.get(g)
    if not n: continue
    for pname, pin in refs:
        segs[n].append('<segment><pinref part="%s" gate="G$1" pin="%s"/></segment>'
                       % (escape(pname), escape(pin)))
print("supply symbols: %d types, %d placed" % (len(supsym), len(supparts)))

# ---------------- shared library ---------------------------------------------
packages = ''.join('<package name="%s">%s</package>' % (escape(k), ''.join(v))
                   for k, v in sorted(BRD['packages'].items()))
symbols = ''.join('<symbol name="%s">%s</symbol>' % (escape(k), ''.join(v))
                  for k, v in sorted(SCH['symbols'].items())) + ''.join(
                  supsym[k] for k in sorted(supsym))
dsets = []
for sym, devs in sorted(SCH['devsets'].items()):
    devxml = ''.join('<device name="%s"%s><connects>%s</connects>'
                     '<technologies><technology name=""/></technologies></device>'
                     % (escape(dn), (' package="%s"' % escape(pk)) if pk else '', ''.join(cs))
                     for dn, (pk, cs) in sorted(devs.items()))
    dsets.append('<deviceset name="%s" prefix="U"><gates>'
                 '<gate name="G$1" symbol="%s" x="0" y="0"/></gates>'
                 '<devices>%s</devices></deviceset>' % (escape(sym), escape(sym), devxml))
devicesets = ''.join(dsets) + supdev

LAYERS = """<layer number="1" name="Top" color="4" fill="1" visible="yes" active="yes"/>
<layer number="16" name="Bottom" color="1" fill="1" visible="yes" active="yes"/>
<layer number="17" name="Pads" color="2" fill="1" visible="yes" active="yes"/>
<layer number="18" name="Vias" color="2" fill="1" visible="yes" active="yes"/>
<layer number="19" name="Unrouted" color="6" fill="1" visible="yes" active="yes"/>
<layer number="20" name="Dimension" color="15" fill="1" visible="yes" active="yes"/>
<layer number="21" name="tPlace" color="7" fill="1" visible="yes" active="yes"/>
<layer number="22" name="bPlace" color="7" fill="1" visible="yes" active="yes"/>
<layer number="23" name="tOrigins" color="15" fill="1" visible="yes" active="yes"/>
<layer number="24" name="bOrigins" color="15" fill="1" visible="yes" active="yes"/>
<layer number="25" name="tNames" color="7" fill="1" visible="yes" active="yes"/>
<layer number="26" name="bNames" color="7" fill="1" visible="yes" active="yes"/>
<layer number="27" name="tValues" color="7" fill="1" visible="yes" active="yes"/>
<layer number="28" name="bValues" color="7" fill="1" visible="yes" active="yes"/>
<layer number="29" name="tStop" color="7" fill="3" visible="no" active="yes"/>
<layer number="30" name="bStop" color="7" fill="6" visible="no" active="yes"/>
<layer number="31" name="tCream" color="7" fill="4" visible="no" active="yes"/>
<layer number="32" name="bCream" color="7" fill="5" visible="no" active="yes"/>
<layer number="39" name="tKeepout" color="4" fill="11" visible="yes" active="yes"/>
<layer number="40" name="bKeepout" color="1" fill="11" visible="yes" active="yes"/>
<layer number="41" name="tRestrict" color="4" fill="10" visible="no" active="yes"/>
<layer number="42" name="bRestrict" color="1" fill="10" visible="no" active="yes"/>
<layer number="43" name="vRestrict" color="2" fill="10" visible="no" active="yes"/>
<layer number="44" name="Drills" color="7" fill="1" visible="no" active="yes"/>
<layer number="45" name="Holes" color="7" fill="1" visible="no" active="yes"/>
<layer number="46" name="Milling" color="3" fill="1" visible="no" active="yes"/>
<layer number="47" name="Measures" color="7" fill="1" visible="no" active="yes"/>
<layer number="48" name="Document" color="7" fill="1" visible="yes" active="yes"/>
<layer number="49" name="Reference" color="7" fill="1" visible="yes" active="yes"/>
<layer number="51" name="tDocu" color="7" fill="1" visible="yes" active="yes"/>
<layer number="52" name="bDocu" color="7" fill="1" visible="yes" active="yes"/>
<layer number="90" name="Modules" color="5" fill="1" visible="yes" active="yes"/>
<layer number="91" name="Nets" color="2" fill="1" visible="yes" active="yes"/>
<layer number="92" name="Busses" color="1" fill="1" visible="yes" active="yes"/>
<layer number="93" name="Pins" color="2" fill="1" visible="no" active="yes"/>
<layer number="94" name="Symbols" color="4" fill="1" visible="yes" active="yes"/>
<layer number="95" name="Names" color="7" fill="1" visible="yes" active="yes"/>
<layer number="96" name="Values" color="7" fill="1" visible="yes" active="yes"/>
<layer number="97" name="Info" color="7" fill="1" visible="yes" active="yes"/>
<layer number="98" name="Guide" color="6" fill="1" visible="yes" active="yes"/>"""

HDR = ('<?xml version="1.0" encoding="utf-8"?>\n'
       '<!DOCTYPE eagle SYSTEM "eagle.dtd">\n'
       '<eagle version="9.6.2">\n<drawing>\n'
       '<settings><setting alwaysvectorfont="no"/><setting verticaltext="up"/></settings>\n'
       '<grid distance="1.27" unitdist="mm" unit="mm" style="lines" multiple="1" display="yes" '
       'altdistance="0.254" altunitdist="mm" altunit="mm"/>\n<layers>\n' + LAYERS + '\n</layers>\n')

DRU = ('<designrules name="default">'
       '<param name="mdWireWire" value="0.1524mm"/><param name="mdWirePad" value="0.1524mm"/>'
       '<param name="mdWireVia" value="0.1524mm"/><param name="mdPadPad" value="0.1524mm"/>'
       '<param name="mdPadVia" value="0.1524mm"/><param name="mdViaVia" value="0.1524mm"/>'
       '<param name="rvPadTop" value="0.25"/><param name="rvPadInner" value="0.25"/>'
       '<param name="rvPadBottom" value="0.25"/><param name="rlMinPadTop" value="0.0635mm"/>'
       '<param name="rlMaxPadTop" value="0.508mm"/>'
       '<param name="rlMinPadInner" value="0.0635mm"/><param name="rlMaxPadInner" value="0.508mm"/>'
       '<param name="rlMinPadBottom" value="0.0635mm"/><param name="rlMaxPadBottom" value="0.508mm"/>'
       # Without these, EAGLE substitutes its defaults (min via ring 8 mil), which
       # are tighter than this board actually uses and make it resize / flag the
       # 24-12 mil vias. The real minimum ring here is 4 mil (the 20-12 vias).
       '<param name="rvViaOuter" value="0.25"/><param name="rvViaInner" value="0.25"/>'
       '<param name="rlMinViaOuter" value="0.1016mm"/><param name="rlMaxViaOuter" value="0.508mm"/>'
       '<param name="rlMinViaInner" value="0.1016mm"/><param name="rlMaxViaInner" value="0.508mm"/>'
       '<param name="mlMinCreamFrame" value="0mm"/>'
       '<param name="slThermalIsolate" value="0.2032mm"/>'
       '</designrules>')

# ---------------- board -------------------------------------------------------
# Altium leaves the PCB component COMMENT empty and draws the value as ordinary
# component-owned silkscreen. Take the value from the schematic (so sch and brd
# agree) and, where that silk text *is* the value, re-link it as a VALUE
# attribute at its exact Altium position instead of leaving it floating.
valof = {des[ci]: (comment.get(ci) or '') for ci in comps if des.get(ci)}
valattr = {}
plainOwn = []
for o in BRD.get('owntext', []):
    ci = o['ci']
    d = C[ci]['des']
    if o['text'] == valof.get(d) and ci not in valattr:
        valattr[ci] = o
    else:
        plainOwn.append('<text x="%s" y="%s" size="%s" layer="%d" ratio="10" rot="%sR%g">%s</text>'
                        % (o['x'], o['y'], o['size'], o['layer'],
                           'M' if o['mirror'] else '', o['rot'], escape(o['text'])))

elements = []
for ci, c in enumerate(C):
    rot = ('M' if c['layer'] == 'BOTTOM' else '') + 'R%g' % (c['rot'] % 360)
    val = valof.get(c['des'], '')
    attrs = ''
    na = BRD.get('nameattr', {}).get(str(ci))
    if na:
        # smashed: >NAME broken out of the package so it keeps Altium's placement
        attrs += ('<attribute name="NAME" x="%s" y="%s" size="%s" layer="%d" ratio="10" '
                  'rot="%sR%g" display="value"/>'
                  % (na['x'], na['y'], na['size'], na['layer'],
                     'M' if na['mirror'] else '', na['rot']))
    va = valattr.get(ci)
    if va:
        attrs += ('<attribute name="VALUE" x="%s" y="%s" size="%s" layer="%d" ratio="10" '
                  'rot="%sR%g" display="value"/>'
                  % (va['x'], va['y'], va['size'], 27 if va['layer'] == 21 else 28,
                     'M' if va['mirror'] else '', va['rot']))
    if attrs:
        elements.append('<element name="%s" library="%s" package="%s" value="%s" x="%s" y="%s" '
                        'rot="%s" smashed="yes">%s</element>'
                        % (escape(c['des']), LIB, escape(compkg[ci]), escape(val),
                           round(c['x'] * 0.0254, 6), round(c['y'] * 0.0254, 6), rot, attrs))
    else:
        elements.append('<element name="%s" library="%s" package="%s" value="%s" x="%s" y="%s" rot="%s"/>'
                        % (escape(c['des']), LIB, escape(compkg[ci]), escape(val),
                           round(c['x'] * 0.0254, 6), round(c['y'] * 0.0254, 6), rot))
signals = []
for n, v in sorted(BRD['signals'].items()):
    nm = 'N$NOCONN' if n == '__nonet' else n
    body = ''.join('<contactref element="%s" pad="%s"/>' % (escape(a), escape(b)) for a, b in v['contact'])
    body += ''.join(v['wire']) + ''.join(v['via'])
    signals.append('<signal name="%s">%s</signal>' % (escape(nm), body))
# Ground pours spanning the board, as in the source design. The NFC coil and
# 2.4 GHz antenna areas are held clear by the tRestrict/bRestrict keep-outs
# emitted from Altium's KIND=1 regions, which is what carves them at pour time.
out_x = [v for t in PCB['tracks'] if t['layer'] == 56 for v in (t['x1'], t['x2'])]
out_y = [v for t in PCB['tracks'] if t['layer'] == 56 for v in (t['y1'], t['y2'])]
x0, x1_, y0, y1_ = min(out_x), max(out_x), min(out_y), max(out_y)
pour = ''
for lay in (1, 16):
    pour += ('<polygon width="0.2032" layer="%d" pour="solid" isolate="0.2032" rank="3">'
             '<vertex x="%s" y="%s"/><vertex x="%s" y="%s"/>'
             '<vertex x="%s" y="%s"/><vertex x="%s" y="%s"/></polygon>'
             % (lay, round(x0 * 0.0254, 6), round(y0 * 0.0254, 6),
                round(x1_ * 0.0254, 6), round(y0 * 0.0254, 6),
                round(x1_ * 0.0254, 6), round(y1_ * 0.0254, 6),
                round(x0 * 0.0254, 6), round(y1_ * 0.0254, 6)))
signals = [s.replace('</signal>', pour + '</signal>') if s.startswith('<signal name="GND">') else s
           for s in signals]

print("  values linked as VALUE attributes: %d (%d stayed free silk)" % (len(valattr), len(plainOwn)))
brd = (HDR + '<board>\n<plain>' + ''.join(BRD['plain']) + ''.join(plainOwn) + '</plain>\n'
       + '<libraries><library name="%s"><packages>%s</packages></library></libraries>\n' % (LIB, packages)
       + '<attributes/><variantdefs/>\n'
       + '<classes><class number="0" name="default" width="0" drill="0"/></classes>\n'
       + DRU + '<autorouter/>\n'
       + '<elements>' + ''.join(elements) + '</elements>\n'
       + '<signals>' + ''.join(signals) + '</signals>\n'
       + '</board>\n</drawing>\n</eagle>\n')

# ---------------- schematic ---------------------------------------------------
parts = []
for ci in sorted(comps):
    parts.append('<part name="%s" library="%s" deviceset="%s" device="%s" value="%s"/>'
                 % (escape(des.get(ci, 'P%d' % ci)), LIB, escape(symof[ci]),
                    escape(devof.get(ci, '')), escape(comment.get(ci, '') or '')))
inst = []
for ci, c in comps.items():
    rot = ('M' if c.get('ISMIRRORED') == 'T' else '') + 'R%d' % (I(c, 'ORIENTATION') * 90)
    inst.append('<instance part="%s" gate="G$1" x="%s" y="%s" rot="%s"/>'
                % (escape(des.get(ci, '')), q(f(c, 'LOCATION.X')), q(f(c, 'LOCATION.Y')), rot))
splain = []
for r in R:
    if r.get('RECORD') == '4' and own(r) not in comps and r.get('TEXT'):
        splain.append('<text x="%s" y="%s" size="1.778" layer="97">%s</text>'
                      % (q(f(r, 'LOCATION.X')), q(f(r, 'LOCATION.Y')), escape(r['TEXT'])))
nets = ''.join('<net name="%s" class="0">%s</net>' % (escape(n), ''.join(s))
               for n, s in sorted(segs.items()) if s)

sch = (HDR + '<schematic xreflabel="%s" xrefpart="/%s.%s">\n' % ('%F%N/%S.%C%R', '%S', '%C')
       + '<libraries><library name="%s"><packages>%s</packages><symbols>%s</symbols>'
         '<devicesets>%s</devicesets></library></libraries>\n' % (LIB, packages, symbols, devicesets)
       + '<attributes/><variantdefs/>\n'
       + '<classes><class number="0" name="default" width="0" drill="0"/></classes>\n'
       + '<modules/>\n<parts>' + ''.join(parts) + ''.join(supparts) + '</parts>\n'
       + '<sheets><sheet><plain>' + ''.join(splain) + '</plain>'
       + '<instances>' + ''.join(inst) + ''.join(supinst) + '</instances><busses/>'
       + '<nets>' + nets + '</nets></sheet></sheets>\n'
       + '</schematic>\n</drawing>\n</eagle>\n')

# ---------------- standalone library ------------------------------------------
# EAGLE .sch/.brd always carry their own embedded copy of every package, symbol
# and deviceset they use -- the format has no "reference an external .lbr" mode.
# This file is the editable master of the same content, so the parts can be
# reused in other designs and pushed back into these two with Library > Update.
lbr = (HDR
       + '<library name="%s">\n' % LIB
       + '<description>%s parts, converted from Altium %s / %s</description>\n'
         % (escape(LIB), escape(os.path.basename(cfg.PCB_IN)), escape(os.path.basename(cfg.SCH_IN)))
       + '<packages>' + packages + '</packages>\n'
       + '<symbols>' + symbols + '</symbols>\n'
       + '<devicesets>' + devicesets + '</devicesets>\n'
       + '</library>\n</drawing>\n</eagle>\n')

os.makedirs(OUT, exist_ok=True)
open(cfg.LBR_OUT, 'w', encoding='utf-8').write(lbr)
open(cfg.BRD_OUT, 'w', encoding='utf-8').write(brd)
open(cfg.SCH_OUT, 'w', encoding='utf-8').write(sch)
print("wrote %s" % OUT)
print("  lbr: %s.lbr" % LIB)
print("  brd: %d elements, %d signals, %d packages" % (len(elements), len(signals), len(BRD['packages'])))
print("  sch: %d parts, %d nets, %d symbols" % (len(parts), len(segs), len(SCH['symbols'])))
