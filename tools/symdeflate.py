# Derived from the Symbian Foundation e32tools source (Eclipse Public License 1.0) - this file stays under the EPL 1.0.
# Python port of Symbian e32tools Huffman/Inflater (e32image/deflate/decode.cpp, inflate.cpp)
import sys,re
M=0xffffffff
HD=[0x0004006c,0x00040064,0x0004005c,0x00040050,0x00040044,0x0004003c,0x00040034,0x00040021,0x00040023,0x00040025,0x00040027,0x00040029,0x00040014,0x0004000c,0x00040035,0x00390037,0x00330031,0x0004002b,0x002f002d,0x001f001d,0x001b0019,0x00040013,0x00170015,0x0004000d,0x0011000f,0x000b0009,0x00070003,0x00050001]
KMAX=27
class Bits:
    def __init__(s,b,off): s.b=b; s.pos=off*8
    def bit(s):
        i=s.pos; s.pos+=1
        return (s.b[i>>3]>>(7-(i&7)))&1
    def read(s,n):
        v=0
        for _ in range(n): v=(v<<1)|s.bit()
        return v
    def huff(s,t):
        h=0; p=0
        while True:
            p+=(h>>16)//4; h=t[p]
            if s.bit()==0: h=(h<<16)&M
            if h&0x10000: break
        return h>>17
def subtree(T,ptr,val,level,li):
    l=level[li]; li+=1
    if l>val:
        sub0=subtree(T,ptr,val,level,li)
        ptr=subtree(T,sub0,val-(ptr-sub0)-1,level,li)
        br0=4*(sub0-(ptr-1)); ptr-=1
        T[ptr]=((4<<16)|br0)&M
    elif l==val:
        t0=T[val]; val-=1
        ptr=subtree(T,ptr,val,level,li); ptr-=1
        T[ptr]=((4<<16)|(t0>>16))&M
    else:
        t0=T[val]; val-=1; t1=T[val]; val-=1; ptr-=1
        T[ptr]=((t1>>16<<16)|(t0>>16))&M
    return ptr
def decoding(lens,base=0):
    n=len(lens); T=[0]*n; counts=[0]*KMAX; codes=0
    for i in range(n):
        l=lens[i]; T[i]=l
        if l-1>=0: counts[l-1]+=1; codes+=1
    level=[0]*KMAX; lit=codes
    for i in range(KMAX): level[i]=lit; lit-=counts[i]
    sb=(base<<17)+(1<<16)
    for i in range(n):
        l=T[i]&0xff
        if l:
            level[l-1]-=1
            T[level[l-1]]=(T[level[l-1]]|((i<<17)+sb))&M
    if codes==1:
        term=T[0]>>16; T[0]=(term|(term<<16))&M
    elif codes>1:
        subtree(T,codes-1,codes-1,level,0)
    return T
def internalize(bi,n):
    lst=list(range(28)); last=0; out=[]; rl=0
    while len(out)+rl<n:
        c=bi.huff(HD)
        if c<2: rl+=rl+c+1
        else:
            out+= [last]*rl; rl=0
            c-=1; lst[0]=last; last=lst[c]
            lst[1:c+1]=lst[0:c]
            out.append(last)
    out+=[last]*rl
    return out[:n]
def inflate(data,off):
    bi=Bits(data,off)
    lens=internalize(bi,285+44)
    lit=decoding(lens[:285]); dist=decoding(lens[285:],0x200)
    out=bytearray(); tree=lit; ln=0
    while True:
        val=bi.huff(tree)-256 if tree is lit else bi.huff(tree)-256
        if tree is lit and val<0: out.append(val&0xff); continue
        if val==285-256-1+0 and tree is lit and val==284-256+ (0): pass
        if tree is lit and val==28: break   # EEos-ELiterals
        code=val&0xff
        if code>=8:
            x=(code>>2)-1; code-=x<<2; code<<=x; code|=bi.read(x)
        if val<0x200-256:
            ln=code+3; tree=dist; continue
        d=code+1
        for _ in range(ln): out.append(out[-d])
        tree=lit
    return bytes(out)
if __name__=='__main__':
    for fn in sys.argv[1:]:
        b=open(fn,'rb').read()
        try: o=inflate(b,0x9c)
        except Exception as e: print(fn,'ERR',repr(e)); continue
        open(fn+'.raw','wb').write(o); print(fn,len(o))
