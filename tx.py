# -*- coding: utf-8 -*-
"""Altium stores strings as raw GBK bytes (or UTF-8 under %UTF8% keys); we read
them as latin-1. Recover the real text, then romanise the Chinese annotations."""
import re

def decode(s, is_utf8=False):
    if not isinstance(s, str): return s
    try: b = s.encode('latin-1')
    except Exception: return s
    for enc in (('utf-8', 'gbk') if is_utf8 else ('gbk', 'utf-8')):
        try: return b.decode(enc)
        except Exception: pass
    return s

def pick(rec, key):
    """Prefer the %UTF8% variant of a field when Altium wrote one."""
    u = '%UTF8%' + key
    if u in rec: return decode(rec[u], True)
    if key in rec: return decode(rec[key], False)
    return None

TRANS = {
    'Type-C USB2.0 母座': 'Type-C USB2.0 receptacle',
    'L1 C1 C11尽量靠近芯片放置': 'Place L1, C1, C11 as close to the chip as possible',
    'C1 C11 接地与芯片接地回路优先级最高': 'C1/C11 ground return to chip ground has top priority',
    'PB14 15一起框起来': 'Box PB14 and PB15 together',
    'PA14 PA15框起来': 'Box PA14 and PA15 together',
    'VCC +3V3 用竖线一起标记': 'Mark VCC and +3V3 together with a vertical line',
    '晶振选型需与芯片内置电容值匹配': "Crystal must match the chip's internal load capacitance",
    'NC(可用于ESD器件)': 'NC (may be fitted with an ESD device)',
    'NC(可用于ESD器件)': 'NC (may be fitted with an ESD device)',
    '沁恒微电子': 'WCH',
    '沁恒': 'WCH',
}
_CJK = re.compile(r'[一-鿿]')

def en(s):
    """Return an ASCII-only rendering of a decoded Altium string."""
    if not isinstance(s, str) or not s: return s
    t = s.strip()
    if t in TRANS: return TRANS[t]
    if not _CJK.search(s): return s
    out = s
    for k, v in sorted(TRANS.items(), key=lambda kv: -len(kv[0])):
        out = out.replace(k, v)
    if _CJK.search(out):                      # anything still un-translated
        out = _CJK.sub('', out)
        out = re.sub(r'\s{2,}', ' ', out).strip(' ()（）,，:：')
    return out

def clean(s, is_utf8=False):
    return en(decode(s, is_utf8))
