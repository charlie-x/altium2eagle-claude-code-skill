import olefile, struct, json, re, sys
from tx import clean
import config as cfg
F=cfg.PCB_IN
ole=olefile.OleFileIO(F)
def rd(p): return ole.openstream(p).read()
def parm(s):
    d={}
    for kv in s.split('|'):
        if '=' in kv:
            k,v=kv.split('=',1); d[k.upper()]=v
    return d
def textrecs(name):
    b=rd(name+'/Data'); i=0; out=[]
    while i+4<=len(b):
        n=struct.unpack('<I',b[i:i+4])[0]; i+=4
        out.append(parm(b[i:i+n].decode('latin-1'))); i+=n
    return out
def binrecs(name):
    b=rd(name+'/Data'); i=0; out=[]
    while i+5<=len(b):
        t=b[i]; n=struct.unpack('<I',b[i+1:i+5])[0]; i+=5
        out.append((t,b[i:i+n])); i+=n
    return out
K=10000.0  # internal units per mil
def mil(v): return v/K
def i32(b,o): return struct.unpack('<i',b[o:o+4])[0]
def u16(b,o): return struct.unpack('<H',b[o:o+2])[0]

out={}
# --- layers from Board6
b=rd('Board6/Data'); n=struct.unpack('<I',b[0:4])[0]
board=parm(b[4:4+n].decode('latin-1'))
layers={}
for i in range(1,83):
    nm=board.get('LAYER%dNAME'%i)
    if nm: layers[i]={'name':nm,'used':board.get('LAYER%dUSED'%i),
                      'cu':board.get('LAYER%dCOPTHICK'%i),'diel':board.get('LAYER%dDIELTYPE'%i),
                      'dielh':board.get('LAYER%dDIELHEIGHT'%i),'dielc':board.get('LAYER%dDIELCONST'%i)}
out['layers']=layers
out['board_meta']={k:board[k] for k in ('DATE','TIME','FILENAME','SHEETWIDTH','SHEETHEIGHT','LAYERSTACK_TYPE') if k in board}

# --- nets
nets=[n_.get('NAME','') for n_ in textrecs('Nets6')]
out['nets']=nets
# --- components
comps=[]
for c in textrecs('Components6'):
    comps.append(dict(des=c.get('SOURCEDESIGNATOR',''), pat=c.get('PATTERN',''),
        comment=clean(c.get('COMMENT','')), lib=c.get('SOURCELIBREFERENCE',''),
        fp=c.get('FOOTPRINTDESCRIPTION',''),
        x=mil(int(c.get('X','0').replace('mil','').split('.')[0])*1) if False else float(c.get('X','0mil').replace('mil','')),
        y=float(c.get('Y','0mil').replace('mil','')),
        rot=float(c.get('ROTATION','0')), layer=c.get('LAYER',''),
        uid=c.get('UNIQUEID','')))
out['components']=comps
# --- tracks
tr=[]
for t,d in binrecs('Tracks6'):
    if t!=4 or len(d)<33: continue
    tr.append(dict(layer=d[0],net=u16(d,3),comp=u16(d,7),
        x1=mil(i32(d,13)),y1=mil(i32(d,17)),x2=mil(i32(d,21)),y2=mil(i32(d,25)),w=mil(i32(d,29))))
out['tracks']=tr
# --- arcs
ar=[]
for t,d in binrecs('Arcs6'):
    if t!=1 or len(d)<45: continue
    ar.append(dict(layer=d[0],net=u16(d,3),comp=u16(d,7),
        cx=mil(i32(d,13)),cy=mil(i32(d,17)),r=mil(i32(d,21)),
        a1=struct.unpack('<d',d[25:33])[0],a2=struct.unpack('<d',d[33:41])[0],w=mil(i32(d,41))))
out['arcs']=ar
# --- vias
vi=[]
for t,d in binrecs('Vias6'):
    if t!=3 or len(d)<29: continue
    vi.append(dict(net=u16(d,3),x=mil(i32(d,13)),y=mil(i32(d,17)),dia=mil(i32(d,21)),hole=mil(i32(d,25)),
                   fromL=d[0] if False else d[1] if False else None, l0=d[1],l1=d[2]))
out['vias']=vi
# --- pads
pd=[]
b=rd('Pads6/Data'); i=0
while i+5<=len(b):
    t=b[i]; i+=1
    blocks=[]; short=False
    for bi in range(6):                      # 6 blocks: name,?,?,?,main,extra
        if i+4>len(b): short=True; break
        n=struct.unpack('<I',b[i:i+4])[0]; i+=4
        if i+n>len(b): short=True; break
        blocks.append(b[i:i+n]); i+=n
    if short or len(blocks)<6: break
    nm=blocks[0][1:1+blocks[0][0]].decode('latin-1') if blocks[0] else ''
    d=blocks[4]
    if len(d)<60: continue
    pd.append(dict(name=nm,layer=d[0],net=u16(d,3),comp=u16(d,7),
        x=mil(i32(d,13)),y=mil(i32(d,17)),
        sx=mil(i32(d,21)),sy=mil(i32(d,25)),
        hole=mil(i32(d,45)),shape=d[49],
        rot=struct.unpack('<d',d[52:60])[0],plated=d[60] if len(d)>60 else 1))
out['pads']=pd
# --- fills
fl=[]
for t,d in binrecs('Fills6'):
    if t!=6 or len(d)<29: continue
    fl.append(dict(layer=d[0],net=u16(d,3),x1=mil(i32(d,13)),y1=mil(i32(d,17)),x2=mil(i32(d,21)),y2=mil(i32(d,25))))
out['fills']=fl
# --- texts
tx=[]
b=rd('Texts6/Data'); i=0
while i+5<=len(b):
    t=b[i]; i+=1
    if i+4>len(b): break
    n=struct.unpack('<I',b[i:i+4])[0]; i+=4; d=b[i:i+n]; i+=n
    if i+4>len(b): break
    n2=struct.unpack('<I',b[i:i+4])[0]; i+=4; s=b[i:i+n2]; i+=n2
    if len(d)<27: continue
    tx.append(dict(layer=d[0],comp=u16(d,7),x=mil(i32(d,13)),y=mil(i32(d,17)),h=mil(i32(d,21)),
        rot=struct.unpack('<d',d[27:35])[0] if len(d)>=35 else 0.0,
        kind=d[41] if len(d)>41 else 0,   # 1 = designator (EAGLE tNames), 0 = ordinary silk
        mirror=bool(d[35]) if len(d)>35 else False,
        w=mil(i32(d,23)) if len(d)>27 else 0.0,
        text=clean(s[1:1+s[0]].decode('latin-1')) if s else ''))
out['texts']=tx
# --- regions (copper keep-outs KIND=1, filled shapes KIND=0)
rg=[]
b=rd('Regions6/Data'); i=0
while i+5<=len(b):
    t=b[i]; n=struct.unpack('<I',b[i+1:i+5])[0]; i+=5
    d=b[i:i+n]; i+=n
    if len(d)<26: continue
    off=13+4+1
    sl=struct.unpack('<I',d[off:off+4])[0]; off+=4
    ps=d[off:off+sl].decode('latin-1'); off+=sl
    nv=struct.unpack('<I',d[off:off+4])[0]; off+=4
    if off+nv*16>len(d): continue
    vs=[struct.unpack('<dd',d[off+j*16:off+j*16+16]) for j in range(nv)]
    pp=dict(kv.split('=',1) for kv in ps.split('|') if '=' in kv)
    rg.append(dict(layer=d[0],net=u16(d,3),comp=u16(d,7),kind=pp.get('KIND'),
                   verts=[(x/K,y/K) for x,y in vs]))
out['regions']=rg

# polygons / regions raw
out['polygons']=[{k:v for k,v in p.items() if k in ('NAME','LAYER','NET','POURINDEX','HATCHSTYLE')} for p in textrecs('Polygons6')]
json.dump(out,open('pcb.json','w'),indent=1)
print("layers:",len([l for l in layers.values() if l['name'].strip()]))
print("nets",len(nets),"comps",len(comps),"tracks",len(tr),"arcs",len(ar),"vias",len(vi),"pads",len(pd),"fills",len(fl),"regions",len(rg),"polys",len(out['polygons']))
