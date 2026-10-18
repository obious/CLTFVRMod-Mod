import sys, pefile, capstone, re
pe=pefile.PE('Titanfall2VR.dll',fast_load=True); base=pe.OPTIONAL_HEADER.ImageBase
img=pe.get_memory_mapped_image()
t=next(s for s in pe.sections if s.Name.startswith(b'.text'))
md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64); md.skipdata=True
targets={int(a,16) for a in sys.argv[1].split(',')}
for x in md.disasm(img[t.VirtualAddress:t.VirtualAddress+t.Misc_VirtualSize], base+t.VirtualAddress):
    m=re.search(r'\[rip ([+-]) (0x[0-9a-f]+)\]',x.op_str)
    if m:
        d=int(m.group(2),16)*(1 if m.group(1)=='+' else -1)
        r=x.address+x.size+d-base
        if r in targets: print(f'{x.address-base:08x} {r:#x}  {x.mnemonic} {x.op_str}')
