import sys, pefile, capstone, struct
dll, names, ctx = sys.argv[1], sys.argv[2].split(','), int(sys.argv[3]) if len(sys.argv)>3 else 40
pe = pefile.PE(dll, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
img = pe.get_memory_mapped_image()
text = next(s for s in pe.sections if s.Name.startswith(b'.text'))
tva, tsz = text.VirtualAddress, text.Misc_VirtualSize
code = img[tva:tva+tsz]
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
def find_str(n):
    b = n.encode()+b'\0'; out=[]; i=img.find(b)
    while i!=-1:
        if i==0 or img[i-1]==0: out.append(i)
        i=img.find(b,i+1)
    return out
for n in names:
    for srva in find_str(n):
        print(f"### {n} @ rva {srva:#x}")
        # scan for rip-relative disp32 pointing at srva
        for off in range(0, len(code)-7):
            if code[off] in (0x48,0x4c) and code[off+1]==0x8d and (code[off+2]&0xc7)==0x05:
                disp = struct.unpack_from('<i', code, off+3)[0]
                if tva+off+7+disp == srva:
                    ip = tva+off
                    idx=None
                    for back in range(ctx*6, ctx*2, -1):
                        start=max(0,off-back)
                        insns=list(md.disasm(code[start:off+ctx*6], base+tva+start))
                        idx=next((k for k,x in enumerate(insns) if x.address==base+ip), None)
                        if idx is not None and idx>=ctx: break
                    if idx is None: print("  (resync failed)", hex(ip)); continue
                    print(f"  xref at rva {ip:#x}")
                    for x in insns[max(0,idx-ctx):idx+ctx]:
                        mark = '>>' if x.address==base+ip else '  '
                        print(f"  {mark} {x.address-base:08x}  {x.mnemonic} {x.op_str}")
