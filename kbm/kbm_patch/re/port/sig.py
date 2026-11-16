"""Finds an old-build code address in the new build by a wildcard byte signature around it.

Displacements of branches and rip-relative operands are wildcards. Tries windows of k instructions before and
after the address, growing until exactly one match remains in the new .text. Needs mapper.load() first.
"""
import re
import mapper
from mapper import target_and_norm


def _pattern(xs):
    p = b''
    for x in xs:
        _, n = target_and_norm(x)
        for a, c in zip(x.bytes, n):
            p += re.escape(bytes([a])) if a == c else b'.'
    return p


def find(rva, max_k=40):
    old, new = mapper.OLD, mapper.NEW
    f = old.func_of(rva)
    xs = old.insns(*f) if f else list(old.md.disasm(old.img[rva - 0x200:rva + 0x200], rva - 0x200))
    idx = next((i for i, x in enumerate(xs) if x.address == rva), None)
    if idx is None:
        return None, 'not an instruction start'
    tb, ts = new.secs['.text']
    text = new.img[tb:tb + ts]
    for k in range(2, max_k):
        lo, hi = max(0, idx - k), min(len(xs), idx + k)
        ms = [m.start() for m in re.finditer(_pattern(xs[lo:hi]), text, re.S)]
        if len(ms) == 1:
            return tb + ms[0] + sum(x.size for x in xs[lo:idx]), f'signature ({2 * k} instructions)'
        if not ms:
            for lo2, hi2 in ((idx, min(len(xs), idx + 2 * k)), (max(0, idx - 2 * k), idx + 1)):
                ms2 = [m.start() for m in re.finditer(_pattern(xs[lo2:hi2]), text, re.S)]
                if len(ms2) == 1:
                    return tb + ms2[0] + sum(x.size for x in xs[lo2:idx]), f'one-sided signature ({2 * k})'
            return None, f'no signature match ({2 * k} instructions)'
    return None, 'signature ambiguous'
