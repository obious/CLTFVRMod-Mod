import sys, pefile, capstone
from capstone.x86 import *
pe=pefile.PE('Titanfall2VR.dll',fast_load=True); base=pe.OPTIONAL_HEADER.ImageBase
img=pe.get_memory_mapped_image()
t=next(s for s in pe.sections if s.Name.startswith(b'.text'))
md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64); md.detail=True; md.skipdata=True
insns=list(md.disasm(img[t.VirtualAddress:t.VirtualAddress+t.Misc_VirtualSize], base+t.VirtualAddress))
target=int(sys.argv[1],16)
def s(rva):
    e=img.find(b'\0',rva)
    if e-rva<3 or e-rva>80: return None
    v=img[rva:e]
    return v.decode() if all(32<=c<127 for c in v) else None
for i,x in enumerate(insns):
    if x.mnemonic=='call' and x.op_str==hex(target):
        args=[]
        for y in insns[max(0,i-12):i]:
            if y.mnemonic in('lea','mov') and len(y.operands)==2:
                d,src=y.operands
                dn=y.reg_name(d.reg) if d.type==X86_OP_REG else (f'[rsp+{d.mem.disp:#x}]' if d.type==X86_OP_MEM else '?')
                if src.type==X86_OP_MEM and src.mem.base==X86_REG_RIP and y.mnemonic=='lea':
                    r=y.address+y.size+src.mem.disp-base; st=s(r)
                    args.append(f"{dn}={st!r}" if st else f"{dn}=&{r:#x}")
                elif src.type==X86_OP_IMM: args.append(f"{dn}={src.imm:#x}")
                elif src.type==X86_OP_MEM and src.mem.base!=X86_REG_RIP: args.append(f"{dn}=[{y.reg_name(src.mem.base)}+{src.mem.disp:#x}]")
        print(f"{x.address-base:#x}: "+'  '.join(args))
