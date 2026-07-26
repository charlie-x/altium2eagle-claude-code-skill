# -*- coding: utf-8 -*-
"""Per-design settings for the Altium -> EAGLE pipeline.

Edit these four, or override from the environment:
    ALT2EAGLE_PCB, ALT2EAGLE_SCH, ALT2EAGLE_OUT, ALT2EAGLE_LIB
Every stage imports from here, so nothing else needs touching per design.
"""
import os

PCB_IN = os.environ.get('ALT2EAGLE_PCB', r"E:/downloads/CH585M-R1-1v1.PcbDoc")
SCH_IN = os.environ.get('ALT2EAGLE_SCH', r"E:/downloads/CH585M-R1.SchDoc")
OUT_DIR = os.environ.get('ALT2EAGLE_OUT', r"E:/downloads/CH585M-R1-fusion")

# Library name, and the base name for the emitted .sch/.brd pair.
LIB = os.environ.get('ALT2EAGLE_LIB', 'CH585M')
BASE = os.environ.get('ALT2EAGLE_BASE',
                      os.path.splitext(os.path.basename(SCH_IN))[0])

# Optional: EAGLE's DTD, used by check.py when present. Validation is skipped
# if this path does not exist.
DTD = os.environ.get('ALT2EAGLE_DTD', r"E:/eagle/doc/eagle.dtd")

SCH_OUT = os.path.join(OUT_DIR, BASE + '.sch')
BRD_OUT = os.path.join(OUT_DIR, BASE + '.brd')
LBR_OUT = os.path.join(OUT_DIR, LIB + '.lbr')
