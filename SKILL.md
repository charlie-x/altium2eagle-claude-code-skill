---
name: altium-to-eagle
description: Convert legacy Altium .PcbDoc/.SchDoc binaries into an EAGLE 9 XML .sch/.brd/.lbr set that Fusion Electronics can open. Use when Fusion or EAGLE refuses an Altium file ("version is wrong", won't import), or when asked to recreate/rebuild/port an Altium board or schematic in Fusion/EAGLE. Also covers Altium OLE record parsing and the pad/pour/net gotchas that make a naive conversion look wrong.
---

# Altium → EAGLE / Fusion Electronics conversion

Classic Altium `.PcbDoc` / `.SchDoc` are **OLE compound files** (magic `D0 CF 11 E0`).
Fusion cannot read them. Fusion *can* open EAGLE 9 XML, so the route is:

    Altium OLE  →  parse binary records  →  emit EAGLE .sch + .brd + .lbr  →  open in Fusion

## Running it

Point `config.py` at the design (or set `ALT2EAGLE_PCB` / `ALT2EAGLE_SCH` /
`ALT2EAGLE_OUT` / `ALT2EAGLE_LIB` in the environment), then:

    bash build.sh

Nothing else is design-specific — every stage reads its paths from `config.py`.
Needs `olefile`; `lxml` and `matplotlib` are optional (DTD validation and the
renderers). `check.py` exits non-zero on any error, so it is safe in a loop.

Stages, in order — the intermediate `*.json` are just handoffs between them:

    sch.py      parse .SchDoc  -> sch.json
    extract.py  parse .PcbDoc  -> pcb.json
    genbrd.py   packages, signals, plain      -> brdparts.json
    gensch.py   symbols, devicesets           -> schparts.json
    emit.py     assemble .sch/.brd/.lbr
    check.py    referential + netlist + DTD verification (exit 1 on error)

`render.py` / `render_sch.py` draw the emitted XML with matplotlib — use them to
eyeball results, because EAGLE's own CLI is unreliable here (see Verification).

## Parsing the Altium container

Streams live under `<Name>/Data`. Two framings:

- **Text records**: `[u32 len][ASCII "|KEY=VAL|KEY=VAL"]`.
  Used by `Board6`, `Nets6`, `Components6`, `Classes6`, `Rules6`, `Polygons6`.
- **Binary records**: `[u8 type][u32 len][payload]`.
  Used by `Tracks6`(4), `Arcs6`(1), `Vias6`(3), `Pads6`(2), `Fills6`(6), `Texts6`(5),
  `Regions6`(11).

Coordinates are **int32 in 1/10000 mil**. `mm = value / 10000 * 0.0254`.

Common primitive header: `layer=u8@0`, `net=u16@3`, `component=u16@7`, then geometry
at 13. **These indices are raw — do not subtract 1.** Validate by checking that a
component's pad centroid lands on its origin, and that the GND net has a plausible
pad count.

Per-primitive offsets after the 13-byte header:

| record | fields |
|---|---|
| Track | x1@13 y1@17 x2@21 y2@25 width@29 |
| Arc | cx@13 cy@17 r@21 startAngle(f64)@25 endAngle(f64)@33 width@41 |
| Via | x@13 y@17 diameter@21 drill@25 |
| Pad | x@13 y@17 xsize@21 ysize@25 hole@45 shape@49 rotation(f64)@52 |
| Text | x@13 y@17 height@21 rotation(f64)@27 mirror@35 |
| Region | kind/params string then u32 count then count × (f64,f64) |

**Pads are framed differently**: `[u8 type][6 × (u32 len + block)]`. Block 0 is a
Pascal-string name, block 4 is the 194-byte main record. Parsing only 5 blocks
desynchronises and silently truncates the pad list — count pads per component and
sanity-check against the footprint (a QFN48 must yield 48 + paddle).

Region parsing: after the 13-byte header comes `u32`, **1 pad byte**, `u32 strlen`,
the param string, `u32 vertexCount`, then vertex pairs. Missing the pad byte yields
garbage vertex counts.

Schematic records are `[u32 len][params]`; `RECORD=` gives the type
(1 component, 2 pin, 4 text, 6 polyline, 13 line, 14 rectangle, 17 power port,
25 net label, 27 wire, 29 junction, 34 designator, 41 parameter, 45 implementation).
`OWNERINDEX` is **file record index − 1** (a header record precedes them). Filter
`OWNERPARTDISPLAYMODE` to mode 0 or you get every alternate display mode's pins.
Schematic units are 1/100 inch → mm = value × 0.254.

## Traps that make a conversion look wrong

Each of these produced a visible defect in a real conversion.

**Poured copper is stored as output, not source.** A hatched Altium polygon is saved
as thousands of net-less tracks at the hatch pitch (e.g. 3760 × 8 mil tracks on an
8 mil grid). Importing them gives "a ground pour made of horizontal lines" and dumps
them all into a bogus no-net signal. **Drop copper that is net-less, component-less
and on a copper layer**; emit an EAGLE `<polygon>` in the signal and let it re-pour.

**Polygon outlines may be absent.** `Polygons6` here stored all-zero vertices, so the
pour outline is unrecoverable — reconstruct as a board-extent polygon and rely on
keep-outs. Say so rather than implying the outline is exact.

**`KIND=1` regions are copper keep-outs.** Map to `tRestrict`(41)/`bRestrict`(42),
both layers when the region is on layer 74 (multi-layer). Missing these floods
antenna clearances. **Ship layers 41/42/43 as `visible="no"`** — they render with a
hatch fill that looks exactly like copper and will be reported as a flooded pour.

**Altium Fills are literal copper**, not pour outlines. Emit as `<rectangle>` on the
copper layer. As a `<polygon>` inside a signal they get re-poured and voided — that
is why an antenna "doesn't fill".

**Pad shape mapping is not symmetric.** Altium `shape 1` is the *round family*: a
circle when X==Y, an **oval** otherwise. `2` is a rectangle, `3` an octagon. EAGLE has
no arbitrary-aspect pad, so:
- rectangle → `square` (never `long`)
- oval, aspect ≥ 1.5 → `long` + `rot="R90"` when the major axis is Y
- oval, aspect < 1.5 → `round` (EAGLE's `long` is a fixed 2:1 stadium and would
  badly oversize a 1.15:1 pad, inflating the pour void)

**Slots are usually not in the file.** USB-C shield legs physically need slots, but
the source may store a plain round hole — verify before claiming either way (diff two
pads that differ only in length; check `PadViaLibrary`, `ExtendedPrimitiveInformation`).
To *build* a slot: plated `<pad>` with the drill **plus** stadium `<smd>` on both
copper layers **plus** a `<wire layer="46">` of the slot width. Omitting the pad
removes the drill from the NC file entirely.

**Altium marks the designator with a flag — use it, don't string-match.** Byte 41 of
the `Texts6` record is `1` for a component's designator text and `0` for ordinary
silkscreen (verified: 49/49 designators vs 52 other component-owned and 64 free texts).
That flag is the analogue of EAGLE's tNames. **tValues has no direct equivalent**: the
PCB `COMMENT` field may be empty on every component, with the value instead drawn as
ordinary component-owned silkscreen (flag `0`). Left alone that becomes floating text
in EAGLE — visibly not attached to any part — and every element ends up with an empty
value that disagrees with its schematic part.

The fix is to reunite them: take each element's value from the **schematic** part (so
board and schematic agree), then for each component-owned text whose content equals
that value, emit it as `<attribute name="VALUE" ... layer="27"/>` on the smashed
element at its exact Altium position. In one design that linked 46 of 52; the
remainder were genuinely not values (`+` polarity marks, and abbreviated silk like
`2Ω` where the schematic said `1Ω(4.7Ω)`) and correctly stayed as free silkscreen.
Only match on exact equality — do not "tidy" a mismatch, it is real source data.

**Designators are positioned per component, not per footprint.** Four 0402s in one
design had their `>NAME` at four different local offsets, so it cannot live in the
shared package. Take the flagged designator text and emit it as a **smashed element**: `<element ... smashed="yes"><attribute name="NAME"
x y size layer="25" rot display="value"/></element>`. Putting `>NAME` at the package
origin renders `[R13 ]` instead of `R13 [ ]`. Every *other* text a component owns
(values, `+` polarity marks) must go to `<plain>` at its absolute position for the
same reason — baking `2kΩ` into the 0402 package stamps it on every 0402.

**Watch for stray off-board silkscreen, but keep it 1:1.** One design had a
component's label parked ~22 in right of the board, which blows up the drawing extents
and looks exactly like a conversion bug. Bounds-check text against the board outline
and **report** every outlier — but reproduce it where the source put it. A converter
must not quietly move source geometry; the user needs a faithful copy they can then
fix deliberately. `genbrd.py` exposes `RELOCATE_STRAY_TEXT` (default `False`) if
pulling outliers back to their component is ever wanted. Sanity-check the final
`<plain>` extents against the board outline so a stray is noticed, not hidden.

This generalises: **when the source is odd, convert it faithfully and say so.** Do not
silently repair. The same applies to unfitted parts, duplicate pad names, and pour
outlines that were never stored.

**Emit the via design rules.** If `rvViaOuter` / `rlMinViaOuter` are absent EAGLE
substitutes defaults (8 mil min ring) that are tighter than many real boards, so
24/12 mil vias get flagged or resized and drills appear to change. Compute the real
minimum annular ring from the via table and set the rules to match.

## EAGLE format constraints

- **Pad/smd names may not contain `@`** (pin names may — `GND@A1` is the convention
  for duplicate pin names in a symbol). Altium allows repeated pad names such as `0`
  for a QFN paddle: uniquify (`0`, `0_2`, …), keep the original as `base`, and tie the
  whole group to one pin with `<connect pad="0 0_2 0_3"/>` — the pad attribute is a
  space-separated list.
- **Packages are always authored top-side.** A bottom element uses `rot="MR<a>"` and
  EAGLE remaps 1↔16 / 21↔22 itself. Baking layer 16 into the package forks a
  duplicate package for every bottom part.
- **Each `<segment>` must be one physically connected piece.** Altium joins nets by
  matching net-label text with no wire between them; collapsing those into a single
  segment is what makes ERC report nets "falling apart". Emit one segment per
  connected piece, all sharing one `<net name>`, each carrying a `<label>`.
- **Power ports are symbols, not text.** Convert Altium record 17 into EAGLE supply
  symbols with a `direction="sup"`, `length="point"` pin at the origin so the
  connection point is identical; map orientation 3/0/1/2 → R0/R90/R180/R270 for a
  symbol drawn pointing down. Emitting them as `<label>` puts the net name off to
  one side of the wire.
- **Net labels carry rotation** (`ORIENTATION`) — drop it and vertical labels go flat.
- **`.sch`/`.brd` always embed their libraries.** There is no external-reference mode;
  a `.lbr` is an editable master kept in sync via Library → Update. `<library>` needs
  a `name` attribute to satisfy `eagle.dtd` even though EAGLE omits it in real files.
- Only copper (1/16) may appear inside `<signal>`; silkscreen and mask belong in
  `<plain>`.
- `curve` must be non-zero and |curve| < 360; full circles use `<circle>`.
- Normalise `-0.0` to `0.0` before hashing geometry, or identical packages fork.

## Text encoding

Altium strings are GBK bytes, with UTF-8 copies under `%UTF8%`-prefixed keys. Read as
latin-1 then `.encode('latin-1').decode('gbk')` (or utf-8 for the `%UTF8%` variants).
`tx.py` does this and romanises the Chinese annotations. Symptom of getting it wrong:
`¾§ÕñÑiÐÍ` mojibake in silkscreen and comments.

## Verification

Do not trust "it parsed". Check, in order:

1. **Geometric round-trip** — re-read the *emitted XML*, resolve every element and
   package transform, and compare all pad coordinates against the Altium originals.
   Expect ~1 nm. This catches placement/mirror/rotation errors that look plausible.
2. **`check.py`** — replicates EAGLE's load-time referential checks (undefined
   library/deviceset/device/package/gate/pin/pad, duplicate names, part↔element
   package agreement) and compares the schematic and board netlists at pad level.
   Supply symbols and unfitted parts are reported separately, not as errors.
3. **DTD** — validate against `E:\eagle\doc\eagle.dtd` with lxml. Cheap and catches
   structural mistakes the referential checker won't.
4. **Render** — `render.py` / `render_sch.py`. Several defects (unfilled antenna,
   hatch-line pour, mis-rotated symbols) are only obvious visually.

`eaglecon.exe -C "EXPORT PARTLIST out.txt; QUIT" file.brd` is a real end-to-end load
test, but **EAGLE and Fusion raise invisible modal popups on load** — the process
hangs or exits 0 having produced nothing. Treat that as environment flakiness, not a
malformed file; retry or ask the user to dismiss the dialog. `WRITE rt.brd; QUIT`
round-trips the board and is the best way to see how EAGLE actually resolved
something (it is what exposed the no-net pour debris and the via rule defaults).

## Reporting

State plainly what is exact and what is approximated. On a real conversion the exact
set was: all track/arc/via/pad geometry, the netlist, and component placement. The
approximations were: re-poured ground planes (EAGLE cannot store literal pour copper),
EAGLE's fixed 2:1 `long` pad, and any synthesised slot lengths. RF boards care about
the difference — call it out before being asked.
