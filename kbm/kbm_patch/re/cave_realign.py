# Body re-align: while a menu is up (TF2VR_SetMenuActive -> byte 0x31808c) the plugin's per-frame view code re-aligns
# the body with the head (closing the pause menu fixes a body that has drifted off to the side). The recenter key
# sets the convar tf2vr_realign_body for a moment; these helpers make the three view-code reads of the menu flag
# (0x90021 anchor/recenter controller, 0x915dc anchor update choice, 0x916d7) see "menu up or re-align asked", while
# the menu rendering keeps reading the plain flag, so no 2D menu screen shows.
#   flag: eax = menu || tf2vr_realign_body != 0; keeps every other register (xmm0-5 too) and needs no alignment
#   at  0x90021 movzx r8d, [menu]   -> call r8_site ; nop x3
#       0x915dc movzx eax, [menu]   -> call flag ; nop x2
#       0x916d7 cmp byte [menu], 0  -> call cmp_site ; nop x2
# usage: cave_realign.py <untouched Titanfall2VR.dll>
import struct, sys, re, keystone, capstone, pefile

START = 0x44220                  # dead body of 0x435a0, after the ADS position hold (end 0x4421a)
LIMIT = 0x44364
MENU = 0x31808c                  # byte set by TF2VR_SetMenuActive
G_REALIGN = 0x31ecd8             # ConVar* cache of tf2vr_realign_body (spare .data page)
F_STR, F_CV = 0x5060, 0x3d5f0

asm = r'''
flag:
    movzx eax, byte ptr [rip + 0x11111101]
    test al, al
    jne flag_ret
    push rcx
    push rdx
    push r8
    push r9
    push r10
    push r11
    sub rsp, 0xa8
    movups xmmword ptr [rsp + 0x40], xmm0
    movups xmmword ptr [rsp + 0x50], xmm1
    movups xmmword ptr [rsp + 0x60], xmm2
    movups xmmword ptr [rsp + 0x70], xmm3
    movups xmmword ptr [rsp + 0x80], xmm4
    movups xmmword ptr [rsp + 0x90], xmm5
    mov rax, qword ptr [rip + 0x11111102]
    test rax, rax
    jne have
    ; rsp alignment unknown here: align for the lookup calls, restore after
    mov r10, rsp
    and rsp, -16
    sub rsp, 0x60
    mov qword ptr [rsp + 0x50], r10             ; clear of the 0x20-byte string at [rsp+0x20]
    lea rcx, [rsp + 0x20]
    lea rdx, [rip + n_realign]
    call 0x5060
    lea rcx, [rsp + 0x20]
    call 0x3d5f0
    mov rsp, qword ptr [rsp + 0x50]
    mov qword ptr [rip + 0x11111103], rax
    test rax, rax
    je off
have:
    mov eax, dword ptr [rax + 0x58]
    and eax, 0x7fffffff
    setne al
    movzx eax, al
    jmp restore
off:
    xor eax, eax
restore:
    movups xmm0, xmmword ptr [rsp + 0x40]
    movups xmm1, xmmword ptr [rsp + 0x50]
    movups xmm2, xmmword ptr [rsp + 0x60]
    movups xmm3, xmmword ptr [rsp + 0x70]
    movups xmm4, xmmword ptr [rsp + 0x80]
    movups xmm5, xmmword ptr [rsp + 0x90]
    add rsp, 0xa8
    pop r11
    pop r10
    pop r9
    pop r8
    pop rdx
    pop rcx
flag_ret:
    ret
    int3
r8_site:
    call flag
    movzx r8d, al
    ret
    int3
cmp_site:
    call flag
    test al, al
    ret
    int3
    int3
n_realign:
    .asciz "tf2vr_realign_body"
'''

ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)
enc, _ = ks.asm(asm.replace(";", "#"), START)
code = bytearray(enc)
for ph, target in {0x11111101: MENU, 0x11111102: G_REALIGN, 0x11111103: G_REALIGN}.items():
    i = code.find(struct.pack('<I', ph))
    assert i >= 0 and code.find(struct.pack('<I', ph), i + 1) < 0, hex(ph)
    code[i:i + 4] = struct.pack('<i', target - (START + i + 4))
code = bytes(code)
assert START + len(code) <= LIMIT, hex(START + len(code))
r8_site = START + code.find(bytes.fromhex('e8')) if False else None
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
labels = {}
end_code = code.find(b'tf2vr_realign_body')
for x in md.disasm(code[:end_code], START):
    r = re.search(r'\[rip \+ (0x[0-9a-f]+)\]', x.op_str)
    t = f'  -> {x.address + x.size + int(r.group(1), 16):#x}' if r else ''
    print(f'{x.address:x} {x.mnemonic} {x.op_str}{t}')
# entry points: the two small stubs start right after an int3 and begin with "call flag"
stubs = [START + m.start() + 1 for m in re.finditer(b'\xcc\xe8', code)]
r8_entry, cmp_entry = stubs[0], stubs[1]
print('flag', hex(START), 'r8_site', hex(r8_entry), 'cmp_site', hex(cmp_entry), 'len', hex(len(code)), 'end', hex(START + len(code)))
pe = pefile.PE(sys.argv[1], fast_load=True)
print('EXP', pe.get_data(START, len(code)).hex())
print('NEW', code.hex())
def call(site, target, size):
    return (b'\xe8' + struct.pack('<i', target - (site + 5)) + b'\x90' * (size - 5)).hex()
print('90021', pe.get_data(0x90021, 8).hex(), '->', call(0x90021, r8_entry, 8))
print('915dc', pe.get_data(0x915dc, 7).hex(), '->', call(0x915dc, START, 7))
print('916d7', pe.get_data(0x916d7, 7).hex(), '->', call(0x916d7, cmp_entry, 7))
