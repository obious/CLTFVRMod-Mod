import sys, pefile, capstone
from capstone.x86 import *
pe=pefile.PE('Titanfall2VR.dll',fast_load=True); base=pe.OPTIONAL_HEADER.ImageBase
img=pe.get_memory_mapped_image()
t=next(s for s in pe.sections if s.Name.startswith(b'.text'))
md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64); md.detail=True; md.skipdata=True
target=int(sys.argv[1],16) if len(sys.argv)>1 else 0x1800a5090
insns=list(md.disasm(img[t.VirtualAddress:t.VirtualAddress+t.Misc_VirtualSize], base+t.VirtualAddress))
def cstr(rva):
    e=img.find(b'\0',rva); return img[rva:e].decode('latin1')
from collections import Counter
calls=Counter()
for i,x in enumerate(insns):
    if x.mnemonic=='call' and x.operands and x.operands[0].type==X86_OP_IMM: calls[x.operands[0].imm]+=1
    if not(x.mnemonic=='call' and x.op_str==hex(target)): continue
    st={}
    for y in insns[max(0,i-10):i]:
        ops=y.operands
        if len(ops)!=2: continue
        d,s=ops
        key=None
        if d.type==X86_OP_REG: key=y.reg_name(d.reg)
        elif d.type==X86_OP_MEM and d.mem.base==X86_REG_RSP: key=f'rsp+{d.mem.disp:#x}'
        if y.mnemonic=='xor' and s.type==X86_OP_REG and d.type==X86_OP_REG and s.reg==d.reg: st[key]=0
        elif y.mnemonic=='mov' and s.type==X86_OP_IMM: st[key]=s.imm
        elif y.mnemonic=='lea' and s.type==X86_OP_MEM and s.mem.base==X86_REG_RIP: st[key]=('p',y.address+y.size+s.mem.disp-base)
        elif y.mnemonic=='mov' and s.type==X86_OP_REG: st[key]=st.get(y.reg_name(s.reg),('r',y.reg_name(s.reg)))
    mod=st.get('ecx'); off=st.get('edx'); n=st.get('rsp+0x20'); nm=st.get('rsp+0x28')
    name=cstr(nm[1]) if isinstance(nm,tuple) and nm[0]=='p' else nm
    def b(k):
        v=st.get(k)
        if isinstance(v,tuple) and v[0]=='p' and isinstance(n,int): return img[v[1]:v[1]+n].hex(' ')
        return v
    print(f"{name:40} mod={mod} off={off if not isinstance(off,int) else hex(off)} len={n} r8={b('r8')} r9={b('r9')}")
if len(sys.argv)>2:
    for a,c in calls.most_common(25): print(hex(a),c)
