import sys, pefile, capstone
pe=pefile.PE('Titanfall2VR.dll',fast_load=True); base=pe.OPTIONAL_HEADER.ImageBase
img=pe.get_memory_mapped_image()
md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64)
rva=int(sys.argv[1],16); n=int(sys.argv[2])
def s(r):
    e=img.find(b'\0',r); v=img[r:e]
    return v.decode() if 3<=len(v)<90 and all(32<=c<127 for c in v) else None
import re
for x in md.disasm(img[rva:rva+n*8], base+rva):
    if n<=0: break
    n-=1
    c=''
    m=re.search(r'\[rip \+ (0x[0-9a-f]+)\]',x.op_str)
    if m:
        r=x.address+x.size+int(m.group(1),16)-base; st=s(r); c=f'   ; {r:#x}'+(f' "{st}"' if st else '')
    print(f'{x.address-base:08x}  {x.mnemonic} {x.op_str}{c}')
