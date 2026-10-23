import struct
_T=[]
for i in range(256):
    c=i
    for _ in range(8): c=(c>>1)^0xEDB88320 if c&1 else c>>1
    _T.append(c)
def crc32_sym(data,crc=0):
    for x in data: crc=(crc>>8)^_T[(crc^x)&0xff]
    return crc&0xffffffff
def header_crc(hdr):
    h=bytearray(hdr); struct.pack_into('<I',h,0x14,0xC90FDAA2)
    return crc32_sym(bytes(h))
