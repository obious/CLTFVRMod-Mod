"""Maps RVAs of one Titanfall2VR.dll build (old) to another (new).

1. functions (from .pdata) whose normalized bytes (rel32 / rip displacements masked) are unique and equal in both
   builds are matched outright
2. walking matched pairs instruction by instruction, every branch / rip-relative target votes old -> new
3. functions reached by votes, or sharing most of their (mapped) references with a new function, are aligned
   instruction by instruction (difflib on the normalized instruction sequence), so addresses inside changed
   functions map too

Usage as a library: mapper.load(old_dll, new_dll); mapper.map_rva(rva) -> new rva or None.
"""
import bisect, collections, difflib, struct, sys
import capstone, pefile


class Img:
    def __init__(self, path):
        pe = pefile.PE(str(path), fast_load=True)
        self.img = pe.get_memory_mapped_image()
        self.base = pe.OPTIONAL_HEADER.ImageBase
        self.secs = {s.Name.rstrip(b'\0').decode(): (s.VirtualAddress, s.Misc_VirtualSize) for s in pe.sections}
        pva, psz = self.secs['.pdata']
        funcs = {}
        for i in range(0, psz - 11, 12):
            b, e, _ = struct.unpack_from('<III', self.img, pva + i)
            if b == 0:
                break
            funcs[b] = e
        self.funcs = sorted(funcs.items())
        self.starts = [b for b, _ in self.funcs]
        self.md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
        self.md.detail = True
        self._ins = {}

    def func_of(self, rva):
        i = bisect.bisect_right(self.starts, rva) - 1
        if i >= 0 and self.funcs[i][0] <= rva < self.funcs[i][1]:
            return self.funcs[i]
        return None

    def insns(self, b, e):
        if (b, e) not in self._ins:
            self._ins[(b, e)] = list(self.md.disasm(self.img[b:e], b))
        return self._ins[(b, e)]


def target_and_norm(x):
    """(branch / rip-relative target or None, instruction bytes with that displacement zeroed)"""
    raw = bytearray(x.bytes)
    tgt = None
    if x.group(capstone.CS_GRP_JUMP) or x.group(capstone.CS_GRP_CALL):
        ops = x.operands
        if len(ops) == 1 and ops[0].type == capstone.x86.X86_OP_IMM:
            tgt = ops[0].imm
            if x.imm_offset:
                for k in range(x.imm_offset, len(raw)):
                    raw[k] = 0
    for op in x.operands:
        if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
            tgt = x.address + x.size + op.mem.disp
            for k in range(x.disp_offset, x.disp_offset + 4):
                raw[k] = 0
    return tgt, bytes(raw)


def norm_seq(img, b, e):
    seq, tg = [], []
    for x in img.insns(b, e):
        t, n = target_and_norm(x)
        seq.append(n)
        tg.append((x.address, x.size, t))
    return seq, tg


OLD = NEW = M = None


def _align(so, sn, to, tn):
    sm = difflib.SequenceMatcher(None, so, sn, autojunk=False)
    pairs = []
    for a, b, size in sm.get_matching_blocks():
        pairs += [(a + k, b + k) for k in range(size)]
    return sm.ratio(), pairs


def load(old_dll, new_dll, log=sys.stderr):
    global OLD, NEW, M
    OLD, NEW = Img(old_dll), Img(new_dll)
    old, new = OLD, NEW

    def hashes(img):
        h = collections.defaultdict(list)
        for b, e in img.funcs:
            h[b''.join(norm_seq(img, b, e)[0])].append(b)
        return h
    ho, hn = hashes(old), hashes(new)
    fmap = {v[0]: hn[k][0] for k, v in ho.items() if len(v) == 1 and len(hn.get(k, ())) == 1}
    print(f'functions: old {len(old.funcs)} new {len(new.funcs)}, identical {len(fmap)}', file=log)
    votes = collections.defaultdict(collections.Counter)
    oend, nend = dict(old.funcs), dict(new.funcs)

    def vote_pair(ob, nb, pairs=None):
        _, to = norm_seq(old, ob, oend[ob])
        _, tn = norm_seq(new, nb, nend[nb])
        for i, j in (pairs if pairs is not None else zip(range(len(to)), range(len(tn)))):
            if to[i][2] is not None and tn[j][2] is not None:
                votes[to[i][2]][tn[j][2]] += 1
    for ob, nb in fmap.items():
        vote_pair(ob, nb)
    aligned = {}

    def align(ob, nb):
        so, to = norm_seq(old, ob, oend[ob])
        sn, tn = norm_seq(new, nb, nend[nb])
        ratio, pairs = _align(so, sn, to, tn)
        aligned[ob] = (nb, ratio, [(to[i][0], tn[j][0]) for i, j in pairs])
        vote_pair(ob, nb, pairs)

    for rnd in range(8):
        added = 0
        for ob, _ in old.funcs:
            if ob in fmap or ob in aligned or ob not in votes:
                continue
            nb = votes[ob].most_common(1)[0][0]
            if nb in nend:
                align(ob, nb); added += 1
        if not added:
            # fingerprint: shared mapped references
            def best(t):
                c = votes.get(t)
                return c.most_common(1)[0][0] if c else None
            taken = set(fmap.values()) | {v[0] for v in aligned.values()}
            inv, ntargets = collections.defaultdict(set), {}
            for nb, ne in new.funcs:
                if nb in taken:
                    continue
                ts = {t for _, _, t in norm_seq(new, nb, ne)[1] if t is not None}
                ntargets[nb] = ts
                for t in ts:
                    inv[t].add(nb)
            for ob, oe in old.funcs:
                if ob in fmap or ob in aligned:
                    continue
                ts = {best(t) for _, _, t in norm_seq(old, ob, oe)[1] if t is not None} - {None}
                if len(ts) < 3:
                    continue
                score = collections.Counter(nb for t in ts for nb in inv.get(t, ()))
                if not score:
                    continue
                nb, hits = score.most_common(1)[0]
                if hits / len(ts | ntargets[nb]) >= 0.4:
                    align(ob, nb); added += 1
        print(f'round {rnd}: aligned {added} more functions', file=log)
        if not added:
            break
    M = {'fmap': fmap, 'aligned': aligned, 'votes': votes}
    return M


def map_rva(rva, why=False):
    f = OLD.func_of(rva)
    r, w = None, 'unmapped'
    if f and f[0] in M['fmap']:
        r, w = M['fmap'][f[0]] + rva - f[0], 'identical function'
    elif f and f[0] in M['aligned']:
        nb, ratio, pairs = M['aligned'][f[0]]
        for o, n in pairs:
            if o == rva:
                r, w = n, f'aligned instruction ({ratio:.2f})'
                break
    if r is None and rva in M['votes']:
        c = M['votes'][rva]
        r, n = c.most_common(1)[0]
        w = f'votes {n}/{sum(c.values())}'
    return (r, w) if why else r
