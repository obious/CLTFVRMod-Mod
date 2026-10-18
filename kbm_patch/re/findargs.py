import pefile, capstone
from capstone.x86 import *
pe=pefile.PE('Titanfall2VR.dll',fast_load=True); base=pe.OPTIONAL_HEADER.ImageBase
img=pe.get_memory_mapped_image()
t=next(s for s in pe.sections if s.Name.startswith(b'.text'))
md=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64); md.detail=True; md.skipdata=True
insns=list(md.disasm(img[t.VirtualAddress:t.VirtualAddress+t.Misc_VirtualSize], base+t.VirtualAddress))
want={'client.disableMouse','inputSystem.disableCursorWarp','inputSystem.disableCursorCapture','inputSystem.disableCursorShape'}
for i,x in enumerate(insns):
    if x.mnemonic=='call' and x.op_str=='0x1800a5090':
        win=insns[max(0,i-10):i]; regs={}; name=None
        for y in win:
            if y.mnemonic=='lea' and y.operands[1].type==X86_OP_MEM and y.operands[1].mem.base==X86_REG_RIP:
                tgt=y.address+y.size+y.operands[1].mem.disp-base
                regs[y.reg_name(y.operands[0].reg)]=(y.address-base,y.size,tgt)
        if 'rax' in regs:
            e=img.find(b'\0',regs['rax'][2]); name=img[regs['rax'][2]:e].decode('latin1')
        if name in want: print(name, 'r8', [hex(v) for v in regs['r8']], 'r9', [hex(v) for v in regs['r9']])
