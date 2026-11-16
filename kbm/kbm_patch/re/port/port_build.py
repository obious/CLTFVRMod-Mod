r"""Ports the patch set of patch_tf2vr_kbm.py (written for the reference build) to another Titanfall2VR.dll build.

Usage:  python port_build.py <untouched reference dll> <untouched new dll> --version=1.0.25 [--out=..\..\builds\1.0.25.json] [-v]
Needs pefile + capstone.

Every patch site is mapped by mapper.py (identical / aligned functions, reference votes), then by a byte signature
(sig.py), then by the build's MANUAL table below. Branch and rip-relative targets in the replacement bytes are
relocated the same way; targets inside a patch move with it. Each site is checked: the new bytes must be the same
instructions with targets that map, except sites in MANUAL (checked by hand). Struct fields that moved and code the
compiler restructured are fixed up per build in BUILD_FIXUPS. Writes nothing when any check fails.
"""
import importlib.util, json, hashlib, struct, sys
from pathlib import Path
import capstone

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mapper, sig
from mapper import target_and_norm

ARGS = sys.argv[1:]
sys.argv = [sys.argv[0], '--size=1280x720']   # the window size doesn't matter here
spec = importlib.util.spec_from_file_location('ptk', HERE.parent.parent / 'patch_tf2vr_kbm.py')
ptk = importlib.util.module_from_spec(spec); spec.loader.exec_module(ptk)

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64); md.detail = True

# Per new build (sha256): sites found by hand, struct field moves, and extra patches.
BUILD_FIXUPS = {
    # Titanfall 2 VR 1.0.25 (Oct 24 2026)
    '9a555fe9f6fc19bd3ab3f81459643aaaa2c9f55350510d4db3917c3085818450': {
        # spare zeroed bytes past the end of .data (0x3622e8), inside its RW page; same 16-byte alignment
        'spare': (0x31ec58, 0x31f000, 0x362300 - 0x31ec60),
        'manual': {
            0x27056: 0x290df,   # group-6 end capture (the aligner pairs it with the wrong call)
            0x2919c: 0x2b31a,   # RUI evaluate hook (grew): draw group 1 gated on 0x317bb8 (-> 0x35b128)
            0x29bae: 0x2bda3,   # RUI evaluate hook: crosshair hidden while pilot (0x316ad0 -> 0x35a040, now in r13b)
            0x90021: 0x96290,   # view code (0x8f610 -> 0x95610, grew): anchor/recenter controller menu flag read
            0x915dc: 0x98815,   # view code: anchor update choice
            0x916d7: 0x9894a,   # view code: anchor reset
        },
        # eye pose struct (global 0x2c5560 -> 0x308600): fields from 0x888 up moved by +0x40 (viewmodel hook
        # 0x88289 `add rax,0x888` -> 0x8de19 `add rax,0x8c8`; 0x26447.. 0x8e8/0x8ec/0x8f0 -> 0x928/0x92c/0x930)
        'fields': {0x436c9: (0x8e8, 0x928), 0x436d0: (0x8a8, 0x8e8),
                   0x44170: (0x8a8, 0x8e8), 0x44178: (0x8e8, 0x928),
                   0x441a6: (0x8ac, 0x8ec), 0x441ae: (0x8ec, 0x92c),
                   0x441dc: (0x8b0, 0x8f0), 0x441e4: (0x8f0, 0x930)},
        # barf mode: the reference build calls the body-matrix function 0x30bf0 at 0x91391; this build inlines it
        # and reaches 0x984b0 with rax = the matrix ([rbp+0x118]) on both paths (the other path calls a function,
        # so no volatile register is live there). The 7-byte `lea rax,[rbp+0x118]` at 0x984a9 calls the pitch
        # helper instead, and the helper's call of the body-matrix function goes to a thunk returning that pointer.
        'replace_site': {0x91391: (0x984a9, '488d8518010000', 'barf mode: inlined body matrix goes through the pitch helper')},
        'call_override': {(0x43790, 0x30bf0): 0x44330},   # (cave, old target) -> old-space address of the thunk
        'extra': [('barf mode: body matrix thunk (lea rax,[rbp+0x118] ; ret)', 0x44330, '488d8518010000c3')],
    },
}


def main():
    paths = [a for a in ARGS if not a.startswith('-')]
    opts = dict(a[2:].split('=', 1) for a in ARGS if a.startswith('--') and '=' in a)
    verbose = '-v' in ARGS
    old_dll, new_dll = Path(paths[0]), Path(paths[1])
    old_sha = hashlib.sha256(old_dll.read_bytes()).hexdigest()
    new_sha = hashlib.sha256(new_dll.read_bytes()).hexdigest()
    if old_sha != ptk.REFERENCE_SHA256:
        sys.exit(f'ABORT: {old_dll} is not the untouched reference build ({ptk.REFERENCE_SHA256[:12]}...)')
    fx = BUILD_FIXUPS.get(new_sha)
    if fx is None:
        sys.exit(f'ABORT: no BUILD_FIXUPS entry for {new_sha}; add one (spare .data area at least) and rerun')
    mapper.load(old_dll, new_dll)
    OLD, NEW = mapper.OLD, mapper.NEW
    s_lo, s_hi, s_delta = fx['spare']

    def m(rva):
        if s_lo <= rva < s_hi:
            return rva + s_delta, 'spare data'
        if rva in fx['manual']:
            return fx['manual'][rva], 'manual'
        r, why = mapper.map_rva(rva, True)
        return (r, why) if r is not None else sig.find(rva)

    def m_old_space(cave, t):
        """target for a relocated reference; an override points into old-space dead code that moves with the cave"""
        o = fx['call_override'].get((cave, t))
        if o is not None:
            return o - cave + m(cave)[0], f'override -> {o:#x}'
        return m(t)

    problems, out = [], []

    def relocate(cave, rva, nrva, code):
        b = bytearray(code)
        for x in md.disasm(bytes(code), rva):
            t, _ = target_and_norm(x)
            if t is None or (rva <= t < rva + len(code) and (cave, t) not in fx['call_override']):
                continue
            nt, why = m_old_space(cave, t)
            if nt is None:
                problems.append(f'{x.address:#x} {x.mnemonic} {x.op_str}: target {t:#x} unmapped ({why})'); continue
            if (x.group(capstone.CS_GRP_JUMP) or x.group(capstone.CS_GRP_CALL)) and x.operands \
                    and x.operands[0].type == capstone.x86.X86_OP_IMM:
                fo, fl = x.imm_offset, x.imm_size
            else:
                fo, fl = x.disp_offset, 4
            off = x.address - rva
            disp = nt - (nrva + off + x.size)
            try:
                b[off + fo:off + fo + fl] = struct.pack({1: '<b', 4: '<i'}[fl], disp)
            except struct.error:
                problems.append(f'{x.address:#x} {x.mnemonic}: displacement {disp} does not fit')
            if verbose:
                print(f'    {x.address:#x} {x.mnemonic} {x.op_str}: {t:#x} -> {nt:#x} ({why})')
        for x in md.disasm(bytes(b), rva):
            if x.address in fx['fields']:
                was, now = fx['fields'][x.address]
                o = x.address - rva + x.disp_offset
                assert struct.unpack_from('<i', b, o)[0] == was, (hex(x.address), x.op_str)
                struct.pack_into('<i', b, o, now)
                print(f'    field {x.address:#x} {x.mnemonic} {x.op_str}: {was:#x} -> {now:#x}')
        return bytes(b)

    window = None
    for desc, rva, expected, repl in ptk.PATCHES:
        if rva in fx['replace_site']:
            nrva, exp_hex, ndesc = fx['replace_site'][rva]
            cur = bytes(NEW.img[nrva:nrva + len(bytes.fromhex(exp_hex))])
            if cur.hex() != exp_hex:
                problems.append(f'{ndesc}: {cur.hex()} at {nrva:#x}, expected {exp_hex}')
            x = next(md.disasm(repl, rva))
            target = m(x.operands[0].imm)[0]   # the call's target, the helper
            nrepl = b'\xe8' + struct.pack('<i', target - (nrva + 5)) + b'\x90' * (len(cur) - 5)
            print(f'{ndesc}\n  {rva:#x} -> {nrva:#x} (replaced site)')
            out.append((ndesc, nrva, cur, nrepl)); continue
        if desc.startswith('patch table:'):
            # rva is the disp32 of `lea r9,[rip+x]` (patched bytes); the replacement points it at the original
            # bytes, which a `lea r8` right after loads
            nlea, why = m(rva - 3)
            print(f'{desc}\n  {rva - 3:#x} -> {nlea:#x} ({why})' if nlea else f'{desc}\n  UNMAPPED ({why})')
            if nlea is None:
                problems.append(desc); continue
            cur = bytes(NEW.img[nlea + 3:nlea + 7])
            o9 = rva + 4 + struct.unpack('<i', expected)[0]
            o8 = rva + 4 + struct.unpack('<i', repl)[0]
            n9 = nlea + 7 + struct.unpack('<i', cur)[0]
            n8 = n9 - (o9 - o8)
            k = o9 - o8
            r8s = [target_and_norm(x)[0] for x in md.disasm(bytes(NEW.img[nlea:nlea + 14]), nlea)
                   if x.mnemonic == 'lea' and x.op_str.startswith('r8,')]
            if not (NEW.img[nlea:nlea + 3] == b'\x4c\x8d\x0d' and n8 in r8s and
                    NEW.img[n8:n8 + k] == OLD.img[o8:o8 + k] and NEW.img[n9:n9 + k] == OLD.img[o9:o9 + k]):
                problems.append(desc)
            out.append((desc, nlea + 3, cur, struct.pack('<i', n8 - (nlea + 7)))); continue
        nrva, why = m(rva)
        print(f'{desc}\n  {rva:#x} -> {nrva:#x} ({why})' if nrva else f'{desc}\n  UNMAPPED ({why})')
        if nrva is None:
            problems.append(desc); continue
        cur = bytes(NEW.img[nrva:nrva + len(expected)])
        if rva == ptk.WINDOW_RVA:
            if cur != expected:
                problems.append(desc)
            window = {'rva': nrva, 'expected': cur.hex()}
            continue
        cave = len(expected) > 30   # dead code or a block replaced as a whole
        if not cave and cur != expected:
            to = [(x.address - rva, x.mnemonic, target_and_norm(x)[0]) for x in md.disasm(expected, rva)]
            tn = [(x.address - nrva, x.mnemonic, target_and_norm(x)[0]) for x in md.disasm(cur, nrva)]
            same = [a[:2] for a in to] == [a[:2] for a in tn] and \
                all(m(a[2])[0] == b[2] for a, b in zip(to, tn) if a[2] is not None)
            print(f'  expected {expected.hex()}, this build {cur.hex()}: ' + ('same, targets map' if same else 'DIFFERENT'))
            if not same and rva not in fx['manual']:
                problems.append(desc)
        out.append((desc, nrva, cur, relocate(rva if cave else None, rva, nrva, repl)))
    for desc, orva, code in fx['extra']:
        nrva = m(orva)[0]
        code = bytes.fromhex(code)
        out.append((desc, nrva, bytes(NEW.img[nrva:nrva + len(code)]), code))
        print(f'{desc}\n  at {nrva:#x}')
    spans = sorted((r, r + len(e), d) for d, r, e, _ in out)
    problems += [f'overlap: {a[2]} / {b[2]}' for a, b in zip(spans, spans[1:]) if a[1] > b[0]]
    if window is None:
        problems.append('window size site not found')
    if problems:
        sys.exit('ABORT, nothing written:\n  ' + '\n  '.join(problems))
    result = {'version': opts.get('version', ''), 'dllSha256': new_sha, 'portedFrom': old_sha, 'window': window,
              'patches': [{'name': d, 'rva': r, 'expected': e.hex(), 'replacement': p.hex()} for d, r, e, p in out]}
    dest = Path(opts.get('out') or HERE.parent.parent / 'builds' / f'{opts.get("version", new_sha[:12])}.json')
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(result, indent=1) + '\n', encoding='utf-8')
    print(f'\nwrote {len(out)} patches + window size to {dest}')


if __name__ == '__main__':
    main()
