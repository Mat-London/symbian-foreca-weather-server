#!/usr/bin/env python3
"""build_foreca_sis.py -- repoint the Foreca S60 app at another host (same length) and rebuild the SIS.

Steps:
  * unzlib each target file (exe + dll) out of the SIS data section
  * Symbian-deflate decode the E32 image body (symdeflate.py), patch UTF-16 host strings
  * store the E32 image uncompressed (compression type 0), recompute E32 header CRC (e32crc.py)
  * zlib the file into the SIS, update controller FileDescription (SHA-1, lengths)
  * drop the signature chain (0x27), bump version build number, recompute both CRC16s
Usage: build_foreca_sis.py IN.sis OUT.sis NEWHOST [http|https]
  http : http://NEWHOST/fd/   (same layout as the original)
  https: https://NEWHOST/     (server serves login.php etc. at the root; URL literal length prefix 24 -> 22)
"""
import hashlib, struct, sys, zlib, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import symdeflate, e32crc

OLD_HOST = 'pw.foreca.com'
TARGETS = ('ForecaWeather_2000E024.exe', 'ForecaLib_2000e024.dll')
u32 = lambda b, o: struct.unpack_from('<I', b, o)[0]
pad4 = lambda n: (n + 3) & ~3


def crc16(buf, init=0, poly=0x1021):
    c = init
    for x in buf:
        c ^= x << 8
        for _ in range(8):
            c = ((c << 1) ^ poly) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c


def fields(buf, off, end):
    """list of (type, start, bodystart, bodyend) for a sequence of fields"""
    out = []
    while off + 8 <= end:
        t, l = u32(buf, off), u32(buf, off + 4)
        if l & 0x80000000:
            raise SystemExit('64-bit field length not supported')
        out.append((t, off, off + 8, off + 8 + l))
        off += 8 + pad4(l)
    return out


def field(t, body):
    return struct.pack('<II', t, len(body)) + body + b'\0' * (pad4(len(body)) - len(body))


def compressed_field(data):
    z = zlib.compress(data, 9)
    return field(3, struct.pack('<IQ', 1, len(data)) + z), len(z)


def elems(buf, b, e):
    """SIS array body: [element type u32] then elements as [len u32][body] (no per-element type)"""
    etype = u32(buf, b)
    off, out = b + 4, []
    while off + 4 <= e:
        l = u32(buf, off)
        out.append((off, off + 4, off + 4 + l))
        off += 4 + pad4(l)
    return etype, out


def array_field(etype, bodies):
    return field(2, struct.pack('<I', etype) + b''.join(
        struct.pack('<I', len(x)) + x + b'\0' * (pad4(len(x)) - len(x)) for x in bodies))


def find_filedescs(ctrl):
    """walk controller; return {target_basename: dict(hash_body, tail)}"""
    res = []

    def fd(b, e):
        tf = fields(ctrl, b, e)
        target = ctrl[tf[0][2]:tf[0][3]].decode('utf-16le')
        hashf = [x for x in tf if x[0] == 0x19][0]
        if target:
            res.append(dict(hash_body=hashf[2], tail=hashf[3] + pad4(hashf[3] - hashf[2]) - (hashf[3] - hashf[2]),
                            target=target))

    def walk(t, b, e):
        if t == 2:
            et, els = elems(ctrl, b, e)
            for _, eb, ee in els:
                if et == 0x18:
                    fd(eb, ee)
                elif et in (0x1a, 0x1b, 0x1c):
                    walk(et, eb, ee)
        elif t in (0x0d, 0x1a, 0x1b, 0x1c):
            for ft, _, fb, fe in fields(ctrl, b, e):
                walk(ft, fb, fe)
    walk(0x0d, 8, len(ctrl))   # root field header is 8 bytes; body walked as field sequence
    return res


def main(src, dst, newhost, mode='http'):
    assert mode in ('http', 'https')
    assert len(newhost) == len(OLD_HOST), f'host must be exactly {len(OLD_HOST)} chars'
    sis = open(src, 'rb').read()
    top = fields(sis, 0x10, len(sis))
    assert len(top) == 1 and top[0][0] == 0x0c
    cont = fields(sis, top[0][2], top[0][3])
    types = [c[0] for c in cont]
    assert types == [0x22, 0x23, 0x03, 0x1e], types
    cf = cont[2]
    algo, usize = struct.unpack_from('<IQ', sis, cf[2])
    ctrl = bytearray(zlib.decompress(sis[cf[2] + 12:cf[3]]))
    assert len(ctrl) == usize
    descs = find_filedescs(bytes(ctrl))
    print('files in package:', len(descs))

    # ---- data section: Data(0x1e) > Array(0x1f) > DataUnit body > Array(0x20) of FileData
    d = cont[3]
    et, units = elems(sis, d[2] + 8, d[3]) if False else (None, None)
    arr = fields(sis, d[2], d[3]); assert [x[0] for x in arr] == [2]
    et, units = elems(sis, arr[0][2], arr[0][3]); assert et == 0x1f and len(units) == 1
    ub, ue = units[0][1], units[0][2]
    inner = fields(sis, ub, ue); assert [x[0] for x in inner] == [2]
    et, filedata = elems(sis, inner[0][2], inner[0][3]); assert et == 0x20
    print('data files:', len(filedata))
    new_fd = [sis[f[1]:f[2]] for f in filedata]      # FileData bodies (Compressed field incl. header)

    total_patched, seen = 0, set()
    old = OLD_HOST.encode('utf-16le'); new = newhost.encode('utf-16le')
    for dsc in descs:
        tail = dsc['tail']
        length, ulength, findex = struct.unpack_from('<QQI', ctrl, tail + 8)
        if findex in seen:
            continue
        f = filedata[findex]
        cfld = fields(sis, f[1], f[2]); assert [c[0] for c in cfld] == [3]
        alg, zsize = struct.unpack_from('<IQ', sis, cfld[0][2])
        if alg != 1:
            continue
        raw = zlib.decompress(sis[cfld[0][2] + 12:cfld[0][3]])
        assert len(raw) == zsize, (len(raw), zsize)
        if raw[16:20] != b'EPOC' or u32(raw, 0x1c) != 0x101F7AFC:
            continue                                       # not a Symbian-deflated E32 image
        assert ulength == len(raw), (dsc['target'], ulength, len(raw))
        assert u32(raw, 0x64) == 0x9c
        body = symdeflate.inflate(raw, 0x9c)
        assert len(body) == u32(raw, 0x7c), (len(body), u32(raw, 0x7c))
        n = body.count(old)
        if n == 0:
            assert body.count(OLD_HOST.encode()) == 0
            continue
        assert n == 2, f'{dsc["target"]}: expected 2 host strings, found {n}'
        assert body.count(OLD_HOST.encode()) == 0, 'ascii host occurrence'
        assert hashlib.sha1(raw).digest() == bytes(ctrl[dsc['hash_body'] + 12: dsc['hash_body'] + 32]), 'orig SHA-1 mismatch'
        assert length == len(sis[cfld[0][2] + 12:cfld[0][3]]), 'Length != zlib stream length'
        body = body.replace(old, new)
        if mode == 'https':
            lit_old = struct.pack('<I', 24) + ('http://' + newhost + '/fd/').encode('utf-16le') + b'\0' * 4
            lit_new = struct.pack('<I', 22) + ('https://' + newhost + '/').encode('utf-16le') + b'\0' * 8
            assert len(lit_old) == len(lit_new) and body.count(lit_old) == 1, (len(lit_old), len(lit_new), body.count(lit_old))
            body = body.replace(lit_old, lit_new)
        total_patched += n
        seen.add(findex)
        hdr = bytearray(raw[:0x9c])
        struct.pack_into('<I', hdr, 0x1c, 0)                       # uncompressed image
        struct.pack_into('<I', hdr, 0x14, e32crc.header_crc(bytes(hdr)))
        img = bytes(hdr) + body
        print(f'  {dsc["target"]} (file {findex}): {len(raw)} -> {len(img)} bytes, {n} host strings patched')
        cfield, zlen = compressed_field(img)
        new_fd[findex] = cfield
        ctrl[dsc['hash_body'] + 12: dsc['hash_body'] + 32] = hashlib.sha1(img).digest()
        struct.pack_into('<QQ', ctrl, tail + 8, zlen, len(img))
    print('patched images:', len(seen), 'strings:', total_patched)
    assert seen and total_patched == 2 * len(seen)

    # ---- controller: drop signature chain, fix root length -------------------
    root = fields(bytes(ctrl), 0, len(ctrl))
    assert len(root) == 1 and root[0][0] == 0x0d
    kids = fields(bytes(ctrl), root[0][2], root[0][3])
    sig = [k for k in kids if k[0] == 0x27]
    assert len(sig) == 1, 'signature chain not found'
    s, e = sig[0][1], sig[0][3] + (pad4(sig[0][3] - sig[0][2]) - (sig[0][3] - sig[0][2]))
    del ctrl[s:e]
    struct.pack_into('<I', ctrl, 4, u32(ctrl, 4) - (e - s))
    print(f'  dropped signature chain ({e - s} bytes)')
    # version build number +1 (so it installs as an upgrade of the signed original)
    info = [k for k in fields(bytes(ctrl), 8, len(ctrl)) if k[0] == 0x0e][0]
    ver = [k for k in fields(bytes(ctrl), info[2], info[3]) if k[0] == 4][0]
    ma, mi, bu = struct.unpack_from('<iii', ctrl, ver[2])
    bump = 1 if mode == 'http' else 2
    struct.pack_into('<iii', ctrl, ver[2], ma, mi, bu + bump)
    print(f'  version {ma}.{mi}.{bu} -> {ma}.{mi}.{bu + bump}')

    # ---- reassemble ------------------------------------------------------------
    cfield_ctrl, _ = compressed_field(bytes(ctrl))
    # compressed_field gives algorithm+size+zlib; SIS uses same layout
    unit_new = array_field(0x20, new_fd)
    data_new = field(0x1e, array_field(0x1f, [unit_new]))
    ctrl_crc = crc16(cfield_ctrl)
    data_crc = crc16(data_new)
    contents_body = (field(0x22, struct.pack('<H', ctrl_crc)) + field(0x23, struct.pack('<H', data_crc))
                     + cfield_ctrl + data_new)
    out = sis[:0x10] + field(0x0c, contents_body)
    open(dst, 'wb').write(out)
    print(f'wrote {dst} ({len(out)} bytes)  crc ctrl {ctrl_crc:04x} data {data_crc:04x}')


if __name__ == '__main__':
    if len(sys.argv) not in (4, 5):
        raise SystemExit(__doc__)
    main(*sys.argv[1:])
