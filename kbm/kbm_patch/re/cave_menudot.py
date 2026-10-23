# Menu pointer dot: the plugin draws a laser dot where a motion controller points at the menu panel; with keyboard
# and mouse there is no laser and the Windows cursor isn't part of the captured menu, so menus had no pointer.
# The helper replaces the call to the pointer update 0x981b0 at 0x9a61e: it runs the original; when no laser is
# active and the menu is interactive (its r8b), it reads the mouse (GetCursorPos + ScreenToClient on the foreground
# window, resolved once through GetModuleHandleW/GetProcAddress) and puts the pointer on the panel there: u/v
# (+0x28/+0x2c, +0x4c/+0x50), pointer/hit flags (+0x30/+0x31) and a tiny beam lying on the panel (+0x34 start,
# +0x40 end), made with the plugin's panel matrix 0x97d50 (panel local x/y in -0.5..0.5, u = x + 0.5, v = 0.5 - y).
# The caller then syncs the menu cursor to the pointer by posting a move when its pixel differs from the last one
# (0x318098/9c); the helper stores that pixel, computed with the caller's own instructions, so the real cursor is
# never moved.
# usage: cave_menudot.py <untouched Titanfall2VR.dll>
import struct, sys, re, keystone, capstone, pefile

START = 0x43e20                  # dead body of 0x435a0, after the ADS pitch hold (end 0x43e17)
LIMIT = 0x44364
IAT_GETPROC, IAT_GETMODULE, IAT_FOREGROUND = 0x12b208, 0x12b210, 0x12b6c8
FN_CURSOR, FN_S2C = 0x31ecc8, 0x31ecd0          # resolved GetCursorPos / ScreenToClient (spare .data page)
LAST_PIXEL = 0x318098                           # caller's last posted cursor pixel (x, y)

asm = r'''
dot:
    push rbx
    push rsi
    push rdi
    push rbp
    push r12
    sub rsp, 0xa0
    mov rbx, rcx
    mov rsi, rdx
    mov edi, r8d
    mov rbp, r9
    mov eax, dword ptr [rsp + 0xf0]
    mov dword ptr [rsp + 0x20], eax
    call 0x981b0
    mov r12d, eax
    cmp byte ptr [rbx + 0x30], 0
    jne done
    test dil, dil
    je done
    ; resolve GetCursorPos / ScreenToClient once
    mov rax, qword ptr [rip + 0x11111101]
    test rax, rax
    jne resolved
    lea rcx, [rip + w_user32]
    call qword ptr [rip + 0x11111102]
    test rax, rax
    je done
    mov qword ptr [rsp + 0x90], rax
    mov rcx, rax
    lea rdx, [rip + s_s2c]
    call qword ptr [rip + 0x11111103]
    mov qword ptr [rip + 0x11111104], rax
    mov rcx, qword ptr [rsp + 0x90]
    lea rdx, [rip + s_cursor]
    call qword ptr [rip + 0x11111105]
    mov qword ptr [rip + 0x11111106], rax
resolved:
    mov rax, qword ptr [rip + 0x11111107]
    test rax, rax
    je done
    mov rax, qword ptr [rip + 0x11111108]
    test rax, rax
    je done
    ; cursor in the game window's client pixels
    lea rcx, [rsp + 0x98]
    call qword ptr [rip + 0x11111109]
    test eax, eax
    je done
    call qword ptr [rip + 0x1111110a]
    test rax, rax
    je done
    mov rcx, rax
    lea rdx, [rsp + 0x98]
    call qword ptr [rip + 0x1111110b]
    test eax, eax
    je done
    ; u = clamp((x + 0.5) / (w - 1)), v = clamp((y + 0.5) / (h - 1)); caller's size: low dword w, high dword h
    mov eax, dword ptr [rsp + 0x98]
    cvtsi2ss xmm0, eax
    addss xmm0, dword ptr [rip + half]
    mov eax, dword ptr [rsp + 0x118]
    dec eax
    jle done
    cvtsi2ss xmm1, eax
    divss xmm0, xmm1
    xorps xmm1, xmm1
    maxss xmm0, xmm1
    minss xmm0, dword ptr [rip + one]
    movss dword ptr [rsp + 0x80], xmm0
    mov eax, dword ptr [rsp + 0x9c]
    cvtsi2ss xmm0, eax
    addss xmm0, dword ptr [rip + half]
    mov eax, dword ptr [rsp + 0x11c]
    dec eax
    jle done
    cvtsi2ss xmm1, eax
    divss xmm0, xmm1
    xorps xmm1, xmm1
    maxss xmm0, xmm1
    minss xmm0, dword ptr [rip + one]
    movss dword ptr [rsp + 0x84], xmm0
    ; the pixel the caller will compute from u/v (its exact instructions), stored as its last posted pixel
    mov eax, dword ptr [rsp + 0x118]
    dec eax
    cvtsi2ss xmm0, rax
    mulss xmm0, dword ptr [rsp + 0x80]
    cvttss2si edx, xmm0
    mov eax, dword ptr [rsp + 0x11c]
    dec eax
    cvtsi2ss xmm0, rax
    mulss xmm0, dword ptr [rsp + 0x84]
    cvttss2si ecx, xmm0
    mov dword ptr [rip + 0x1111110c], edx
    mov dword ptr [rip + 0x1111110d], ecx
    ; panel matrix (rows m0..m3 at [rsp+0x40])
    lea rcx, [rsp + 0x40]
    mov rdx, rbp
    movss xmm2, dword ptr [rsp + 0xf0]
    call 0x97d50
    ; local x = u - 0.5, y = 0.5 - v
    movss xmm0, dword ptr [rsp + 0x80]
    subss xmm0, dword ptr [rip + half]
    movss dword ptr [rsp + 0x88], xmm0
    movss xmm0, dword ptr [rip + half]
    subss xmm0, dword ptr [rsp + 0x84]
    movss dword ptr [rsp + 0x8c], xmm0
    ; end = x*m0 + y*m1 + m3, / w
    movss xmm1, dword ptr [rsp + 0x88]
    shufps xmm1, xmm1, 0
    movups xmm3, xmmword ptr [rsp + 0x40]
    mulps xmm3, xmm1
    movss xmm1, dword ptr [rsp + 0x8c]
    shufps xmm1, xmm1, 0
    movups xmm4, xmmword ptr [rsp + 0x50]
    mulps xmm4, xmm1
    addps xmm3, xmm4
    movups xmm4, xmmword ptr [rsp + 0x70]
    addps xmm3, xmm4
    movaps xmm4, xmm3
    shufps xmm4, xmm4, 0xff
    divps xmm3, xmm4
    movsd qword ptr [rbx + 0x40], xmm3
    movaps xmm4, xmm3
    shufps xmm4, xmm4, 0xaa
    movss dword ptr [rbx + 0x48], xmm4
    ; start = the same a hair to the left on the panel ((x - 0.002)*m0 + y*m1 + m3, / w)
    movss xmm1, dword ptr [rsp + 0x88]
    subss xmm1, dword ptr [rip + stub]
    shufps xmm1, xmm1, 0
    movups xmm3, xmmword ptr [rsp + 0x40]
    mulps xmm3, xmm1
    movss xmm1, dword ptr [rsp + 0x8c]
    shufps xmm1, xmm1, 0
    movups xmm4, xmmword ptr [rsp + 0x50]
    mulps xmm4, xmm1
    addps xmm3, xmm4
    movups xmm4, xmmword ptr [rsp + 0x70]
    addps xmm3, xmm4
    movaps xmm4, xmm3
    shufps xmm4, xmm4, 0xff
    divps xmm3, xmm4
    movsd qword ptr [rbx + 0x34], xmm3
    movaps xmm4, xmm3
    shufps xmm4, xmm4, 0xaa
    movss dword ptr [rbx + 0x3c], xmm4
    ; u/v and flags
    movss xmm0, dword ptr [rsp + 0x80]
    movss dword ptr [rbx + 0x28], xmm0
    movss dword ptr [rbx + 0x4c], xmm0
    movss xmm0, dword ptr [rsp + 0x84]
    movss dword ptr [rbx + 0x2c], xmm0
    movss dword ptr [rbx + 0x50], xmm0
    mov byte ptr [rbx + 0x30], 1
    mov byte ptr [rbx + 0x31], 1
    mov byte ptr [rbx + 0x32], 0
done:
    mov eax, r12d
    add rsp, 0xa0
    pop r12
    pop rbp
    pop rdi
    pop rsi
    pop rbx
    ret
    int3
    int3
    int3
    int3
half:
    .long 0x3f000000
one:
    .long 0x3f800000
stub:
    .long 0x3b03126f
w_user32:
    .byte 0x75, 0, 0x73, 0, 0x65, 0, 0x72, 0, 0x33, 0, 0x32, 0, 0x2e, 0, 0x64, 0, 0x6c, 0, 0x6c, 0, 0, 0
s_cursor:
    .asciz "GetCursorPos"
s_s2c:
    .asciz "ScreenToClient"
'''

ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)
enc, _ = ks.asm(asm.replace(";", "#"), START)
code = bytearray(enc)
targets = {0x11111101: FN_CURSOR, 0x11111102: IAT_GETMODULE, 0x11111103: IAT_GETPROC, 0x11111104: FN_S2C,
           0x11111105: IAT_GETPROC, 0x11111106: FN_CURSOR, 0x11111107: FN_CURSOR, 0x11111108: FN_S2C,
           0x11111109: FN_CURSOR, 0x1111110a: IAT_FOREGROUND, 0x1111110b: FN_S2C,
           0x1111110c: LAST_PIXEL, 0x1111110d: LAST_PIXEL + 4}
for ph, target in targets.items():
    i = code.find(struct.pack('<I', ph))
    assert i >= 0 and code.find(struct.pack('<I', ph), i + 1) < 0, hex(ph)
    code[i:i + 4] = struct.pack('<i', target - (START + i + 4))   # plain loads/stores/calls, no trailing imm
code = bytes(code)
assert START + len(code) <= LIMIT

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
end_code = code.find(b'\xcc' * 4)
for x in md.disasm(code[:end_code], START):
    r = re.search(r'\[rip \+ (0x[0-9a-f]+)\]', x.op_str)
    t = f'  -> {x.address + x.size + int(r.group(1), 16):#x}' if r else ''
    print(f'{x.address:x} {x.mnemonic} {x.op_str}{t}')
print('len', hex(len(code)), 'end', hex(START + len(code)))
pe = pefile.PE(sys.argv[1], fast_load=True)
print('EXP', pe.get_data(START, len(code)).hex())
print('NEW', code.hex())
print('9a61e', pe.get_data(0x9a61e, 5).hex(), '->', (b'\xe8' + struct.pack('<i', START - (0x9a61e + 5))).hex())
tail = code[end_code:]
print('data', tail)
