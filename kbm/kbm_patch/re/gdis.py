import sys, pefile, capstone, re
pe=pefile.PE(sys.argv[1],fast_load=True); base=pe.OPTIONAL_HEADER.ImageBase
img=pe.get_memory_mapped_image()
md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64)
rva=int(sys.argv[2],16); before=int(sys.argv[3]); after=int(sys.argv[4])
def s(r):
    if r<0 or r>=len(img): return None
    e=img.find(b'\0',r); v=img[r:e]
    return v.decode() if 3<=len(v)<90 and all(32<=c<127 for c in v) else None
for back in range(before*7, before*2, -1):
    ins=list(md.disasm(img[rva-back:rva+after*8], base+rva-back))
    idx=next((k for k,x in enumerate(ins) if x.address==base+rva),None)
    if idx is not None and idx>=before: break
for x in ins[idx-before:idx+after]:
    c=''; m=re.search(r'\[rip \+ (0x[0-9a-f]+)\]',x.op_str)
    if m:
        r=x.address+x.size+int(m.group(1),16)-base; st=s(r); c=f'   ; {r:#x}'+(f' "{st}"' if st else '')
    print(('>>' if x.address==base+rva else '  ')+f'{x.address-base:08x}  {x.mnemonic} {x.op_str}{c}')
