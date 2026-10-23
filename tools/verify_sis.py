import sys,zlib,struct,hashlib
sys.path.insert(0,'.')
import build_foreca_sis as b, e32crc
o=open(sys.argv[1],'rb').read(); n=open(sys.argv[2],'rb').read()
NEWHOST=sys.argv[3] if len(sys.argv)>3 else ''   # optional: the host you patched in, to count occurrences
def load(sis):
    top=b.fields(sis,0x10,len(sis)); assert len(top)==1 and top[0][1]+8+b.pad4(top[0][3]-top[0][2])==len(sis),'container length'
    cont=b.fields(sis,top[0][2],top[0][3]); assert [c[0] for c in cont]==[0x22,0x23,0x03,0x1e]
    cc=struct.unpack_from('<H',sis,cont[0][2])[0]; dc=struct.unpack_from('<H',sis,cont[1][2])[0]
    cf=cont[2]; assert b.crc16(sis[cf[1]:cf[1]+8+b.pad4(cf[3]-cf[2])])==cc,'ctrl crc'
    d=cont[3]; assert b.crc16(sis[d[1]:d[3]+(b.pad4(d[3]-d[2])-(d[3]-d[2]))])==dc,'data crc'
    ctrl=zlib.decompress(sis[cf[2]+12:cf[3]])
    root=b.fields(ctrl,0,len(ctrl)); assert len(root)==1 and root[0][3]==len(ctrl),'ctrl root len'
    arr=b.fields(sis,d[2],d[3]); et,u=b.elems(sis,arr[0][2],arr[0][3]); inn=b.fields(sis,u[0][1],u[0][2]); et,fd=b.elems(sis,inn[0][2],inn[0][3])
    return ctrl,[sis[f[1]:f[2]] for f in fd]
co,fo=load(o); cn,fn=load(n)
print('CRCs ok; files',len(fo),len(fn))
descs=b.find_filedescs(cn); bad=0; changed=0
for dsc in descs:
    L,U,I=struct.unpack_from('<QQI',cn,dsc['tail']+8)
    cf=b.fields(fn[I],0,len(fn[I]))[0]
    alg,zs=struct.unpack_from('<IQ',fn[I],8)
    if alg!=1: continue
    z=fn[I][8+12:8+cf[3]-cf[2]]
    raw=zlib.decompress(z)
    ok=hashlib.sha1(raw).digest()==cn[dsc['hash_body']+12:dsc['hash_body']+32]
    if raw[16:20]==b'EPOC' and U==len(raw) and L==len(z): pass
    elif raw[16:20]==b'EPOC' or not ok: print('MISMATCH',dsc['target'],U,len(raw),L,len(z),ok); bad+=1
    if raw[16:20]==b'EPOC':
        h=raw[:0x9c]; hc=struct.unpack_from('<I',raw,0x14)[0]
        if struct.unpack_from('<I',raw,0x1c)[0]==0:
            print(dsc['target'],'uncompressed hdrcrc ok' if e32crc.header_crc(h)==hc else 'HDR CRC BAD','sha ok' if ok else 'SHA BAD','size',len(raw), 'hdr usize',hex(struct.unpack_from('<I',raw,0x7c)[0]), 'body',len(raw)-0x9c, 'new host x',raw.count(NEWHOST.encode('utf-16le')),'old x',raw.count('pw.foreca.com'.encode('utf-16le')))
            changed+=1
print('changed images',changed,'bad',bad)
same=sum(1 for a,c in zip(fo,fn) if a==c); print('identical file records',same,'of',len(fo))
print('sig chain in new controller:', any(t==0x27 for t,_,_,_ in b.fields(cn,cn and 8,len(cn))))
