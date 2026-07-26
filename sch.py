import olefile,struct,json
from tx import clean
from collections import Counter
import config as cfg
ole=olefile.OleFileIO(cfg.SCH_IN)
b=ole.openstream('FileHeader').read()
i=0;recs=[]
while i+4<=len(b):
    n=struct.unpack('<I',b[i:i+4])[0]; i+=4
    if n<=0 or i+n>len(b): break
    s=b[i:i+n].decode('latin-1').rstrip('\x00'); i+=n
    d={}
    for kv in s.lstrip('|').split('|'):
        if '=' in kv:
            k,v=kv.split('=',1); k=k.upper()
            if k.startswith('%UTF8%'): d[k[6:]]=clean(v,True)
            elif k not in d: d[k]=clean(v,False)
    recs.append(d)
print("records:",len(recs),"consumed",i,"of",len(b))
c=Counter(r.get('RECORD','?') for r in recs)
print(sorted(c.items(), key=lambda x:-x[1]))
json.dump(recs,open('sch.json','w'),indent=1)
