# -*- coding: utf-8 -*-
"""Replicate EAGLE's load-time referential checks on the generated .sch/.brd pair."""
import os, sys
from collections import defaultdict, Counter
import xml.etree.ElementTree as ET
import config as cfg

D = cfg.OUT_DIR
err = []
def E(msg): err.append(msg)

sch = ET.parse(cfg.SCH_OUT).getroot()
brd = ET.parse(cfg.BRD_OUT).getroot()

def dup(names, what, where):
    for k, v in Counter(names).items():
        if v > 1: E("duplicate %s %r in %s" % (what, k, where))

# ---- libraries ---------------------------------------------------------------
def libs(root):
    out = {}
    for lb in root.iter('library'):
        pk = {p.get('name'): {e.get('name') for e in list(p) if e.tag in ('pad', 'smd')}
              for p in lb.iter('package')}
        for p in lb.iter('package'):
            dup([e.get('name') for e in list(p) if e.tag in ('pad', 'smd')], 'pad', 'package ' + p.get('name'))
        sy = {s.get('name'): {q.get('name') for q in s.iter('pin')} for s in lb.iter('symbol')}
        for s in lb.iter('symbol'):
            dup([q.get('name') for q in s.iter('pin')], 'pin', 'symbol ' + s.get('name'))
        ds = {}
        for d in lb.iter('deviceset'):
            gates = {g.get('name'): g.get('symbol') for g in d.iter('gate')}
            devs = {}
            for dv in d.iter('device'):
                devs[dv.get('name')] = (dv.get('package'),
                                        [(c.get('gate'), c.get('pin'), c.get('pad')) for c in dv.iter('connect')])
            dup([dv.get('name') for dv in d.iter('device')], 'device', 'deviceset ' + d.get('name'))
            ds[d.get('name')] = (gates, devs)
        dup(list(pk), 'package', 'library ' + lb.get('name'))
        dup(list(sy), 'symbol', 'library ' + lb.get('name'))
        dup(list(ds), 'deviceset', 'library ' + lb.get('name'))
        out[lb.get('name')] = (pk, sy, ds)
    return out

SL, BL = libs(sch), libs(brd)

# packages must be byte-identical in both files for sch/brd consistency
for ln, (pk, _, _) in SL.items():
    if ln not in BL: E("library %r missing from board" % ln); continue
    bpk = BL[ln][0]
    if set(pk) != set(bpk):
        E("package set differs: sch-only=%s brd-only=%s" % (sorted(set(pk) - set(bpk)), sorted(set(bpk) - set(pk))))
    for p in pk:
        if p in bpk and pk[p] != bpk[p]:
            E("package %r pad set differs between sch and brd" % p)

# ---- deviceset internals -----------------------------------------------------
for ln, (pk, sy, ds) in SL.items():
    for dn, (gates, devs) in ds.items():
        for gn, gsym in gates.items():
            if gsym not in sy: E("deviceset %s gate %s -> undefined symbol %s" % (dn, gn, gsym))
        for dvn, (pkg, conns) in devs.items():
            if pkg is not None and pkg not in pk:
                E("deviceset %s device %r -> undefined package %r" % (dn, dvn, pkg))
            for g, pin, pad in conns:
                if g not in gates: E("connect in %s/%s -> undefined gate %s" % (dn, dvn, g))
                elif pin not in sy.get(gates[g], set()):
                    E("connect in %s/%s -> undefined pin %r" % (dn, dvn, pin))
                for one in (pad or '').split():
                    if pkg and one not in pk.get(pkg, set()):
                        E("connect in %s/%s -> undefined pad %r in package %s" % (dn, dvn, one, pkg))

# ---- parts / instances -------------------------------------------------------
parts = {}
for p in sch.iter('part'):
    parts[p.get('name')] = (p.get('library'), p.get('deviceset'), p.get('device'))
dup([p.get('name') for p in sch.iter('part')], 'part', 'schematic')
for n, (ln, dn, dvn) in parts.items():
    if ln not in SL: E("part %s -> undefined library %r" % (n, ln)); continue
    ds = SL[ln][2]
    if dn not in ds: E("part %s -> undefined deviceset %r" % (n, dn)); continue
    if dvn not in ds[dn][1]:
        E("part %s -> undefined device %r in deviceset %s" % (n, dvn, dn))
for i in sch.iter('instance'):
    pn = i.get('part')
    if pn not in parts: E("instance -> undefined part %r" % pn); continue
    ln, dn, _ = parts[pn]
    if i.get('gate') not in SL[ln][2][dn][0]:
        E("instance %s -> undefined gate %r" % (pn, i.get('gate')))
for net in sch.iter('net'):
    for pr in net.iter('pinref'):
        pn = pr.get('part')
        if pn not in parts: E("pinref -> undefined part %r" % pn); continue
        ln, dn, _ = parts[pn]
        gates = SL[ln][2][dn][0]
        g = pr.get('gate')
        if g not in gates: E("pinref %s -> undefined gate %r" % (pn, g)); continue
        if pr.get('pin') not in SL[ln][1].get(gates[g], set()):
            E("pinref %s.%s -> undefined pin %r" % (pn, g, pr.get('pin')))
dup([n.get('name') for n in sch.iter('net')], 'net', 'sheet')

# ---- elements / signals ------------------------------------------------------
elems = {}
for e in brd.iter('element'):
    elems[e.get('name')] = (e.get('library'), e.get('package'))
dup([e.get('name') for e in brd.iter('element')], 'element', 'board')
for n, (ln, pkn) in elems.items():
    if ln not in BL: E("element %s -> undefined library %r" % (n, ln)); continue
    if pkn not in BL[ln][0]: E("element %s -> undefined package %r" % (n, pkn))
dup([s.get('name') for s in brd.iter('signal')], 'signal', 'board')
for s in brd.iter('signal'):
    for cr in s.iter('contactref'):
        en = cr.get('element')
        if en not in elems: E("contactref -> undefined element %r" % en); continue
        ln, pkn = elems[en]
        if cr.get('pad') not in BL[ln][0].get(pkn, set()):
            E("contactref %s -> undefined pad %r in package %s" % (en, cr.get('pad'), pkn))

# ---- sch/brd consistency -----------------------------------------------------
for n in elems:
    if n not in parts: E("board element %s has no schematic part" % n)
    else:
        ln, dn, dvn = parts[n]
        pkg = SL[ln][2][dn][1][dvn][0]
        if pkg != elems[n][1]:
            E("part/element %s package mismatch: sch=%r brd=%r" % (n, pkg, elems[n][1]))

conn = {}
for ln, (_, _, ds) in SL.items():
    for dn, (_, devs) in ds.items():
        for dvn, (pkg, cs) in devs.items():
            conn[(ln, dn, dvn)] = {(g, pin): (pad or '').split() for g, pin, pad in cs}
schnet = defaultdict(set)
for net in sch.iter('net'):
    for pr in net.iter('pinref'):
        key = parts.get(pr.get('part'))
        if not key: continue
        for pad in conn.get(key, {}).get((pr.get('gate'), pr.get('pin')), []):
            schnet[net.get('name')].add((pr.get('part'), pad))
brdnet = defaultdict(set)
for s in brd.iter('signal'):
    for cr in s.iter('contactref'):
        brdnet[s.get('name')].add((cr.get('element'), cr.get('pad')))
# Parts with no board element are unfitted in the source design (Altium never
# placed them); their pins legitimately appear only on the schematic side.
unfitted = set(parts) - set(elems)
supply = {n for n in unfitted if parts[n][1].startswith('SUPPLY_')}
unfitted -= supply
for n, cs in brdnet.items():
    s = {c for c in schnet.get(n, set()) if c[0] not in unfitted}
    if s != cs:
        E("net %s differs: brd-only=%s sch-only=%s" % (n, sorted(cs - s)[:5], sorted(s - cs)[:5]))
if supply:
    print("supply symbols (no package, never on the board): %d" % len(supply))
if unfitted:
    print("unfitted (schematic-only, not placed in the source PCB): %s" % sorted(unfitted))

# ---- DTD validation (skipped when eagle.dtd is not available) ----------------
if os.path.exists(cfg.DTD):
    try:
        from lxml import etree
        dtd = etree.DTD(open(cfg.DTD, 'rb'))
        for p in (cfg.SCH_OUT, cfg.BRD_OUT, cfg.LBR_OUT):
            if not os.path.exists(p): continue
            if not dtd.validate(etree.parse(p)):
                first = list(dtd.error_log.filter_from_errors())[:1]
                E("DTD invalid: %s%s" % (os.path.basename(p),
                                         (" -- " + first[0].message[:120]) if first else ""))
    except ImportError:
        print("note: lxml not installed, DTD validation skipped")
else:
    print("note: %s not found, DTD validation skipped" % cfg.DTD)

print("schematic: %d parts, %d nets | board: %d elements, %d signals"
      % (len(parts), len(list(sch.iter('net'))), len(elems), len(list(brd.iter('signal')))))
print("errors: %d" % len(err))
for m in err[:40]: print("  -", m)
sys.exit(1 if err else 0)
