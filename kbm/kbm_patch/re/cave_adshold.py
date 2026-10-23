# ADS pitch hold: while aiming down sights (barf mode on), the eye views are rendered without the head's pitch, so
# the view's up/down follows the mouse aim exactly and the sights line up vertically. Yaw, roll and positions keep
# tracking; only the rendered views change (the poses submitted to the runtime stay real, so the compositor keeps
# the image on the gaze).
# Wrapper with 0x82670's signature (rcx out, rdx body matrix, r8 anchor pose, r9 XrView): copies the XrView, takes
# on foot only, q' = r(t) * q where r rotates the view's forward (-Z) onto the horizontal, t = ADS fraction * tf2vr_ads_hold *
# min(tf2vr_barf_mode, 1), then calls 0x82670 with the copy. Used by the main eye views (call at 0x87589) and the
# viewmodel eye views (call at 0x4371b inside the ADS eye helper).
# usage: cave_adshold.py <untouched Titanfall2VR.dll>
import struct, sys, re, keystone, capstone, pefile

START = 0x439a0                  # dead body of 0x435a0, after the barf / skip-calibration helpers (end 0x4399b)
LIMIT = 0x44364
BUILD, F_STR, F_CV = 0x82670, 0x5060, 0x3d5f0
CLIENT = 0x31d6c0                # client.dll base
G_BARF = 0x31eca0                # ConVar* cache of tf2vr_barf_mode (barf helper)
IS_TITAN = 0x2ca4e0               # byte: local player is in a Titan
G_HOLD = 0x31ecb0                # ConVar* cache of tf2vr_ads_hold (new, next to the barf / skip-calibration ones)
EXTERN = {'CLIENT': CLIENT, 'G_BARF': G_BARF, 'G_HOLD': G_HOLD}

asm = r'''
hold:
    push rbx
    push rsi
    push rdi
    push rbp
    sub rsp, 0xa8
    mov rsi, rcx
    mov rdi, rdx
    mov rbp, r8
    ; copy the XrView (0x40 bytes) to [rsp+0x40]
    movups xmm0, xmmword ptr [r9]
    movups xmmword ptr [rsp + 0x40], xmm0
    movups xmm0, xmmword ptr [r9 + 0x10]
    movups xmmword ptr [rsp + 0x50], xmm0
    movups xmm0, xmmword ptr [r9 + 0x20]
    movups xmmword ptr [rsp + 0x60], xmm0
    movups xmm0, xmmword ptr [r9 + 0x30]
    movups xmmword ptr [rsp + 0x70], xmm0
    ; on foot only: in a Titan (0x2ca4e0) the view keeps tracking the head
    movzx eax, byte ptr [rip + 0x11111107]
    test al, al
    jne plain
    ; t = barf scale (clamped to 1); 0 or NaN -> plain view
    mov rax, qword ptr [rip + 0x11111101]
    test rax, rax
    jne have_barf
    lea rcx, [rsp + 0x20]
    lea rdx, [rip + n_barf]
    call 0x5060
    lea rcx, [rsp + 0x20]
    call 0x3d5f0
    mov qword ptr [rip + 0x11111102], rax
have_barf:
    movss xmm0, dword ptr [rax + 0x58]
    xorps xmm1, xmm1
    ucomiss xmm0, xmm1
    jbe plain
    minss xmm0, dword ptr [rip + one]
    movss dword ptr [rsp + 0x80], xmm0
    ; * tf2vr_ads_hold
    mov rax, qword ptr [rip + 0x11111103]
    test rax, rax
    jne have_hold
    lea rcx, [rsp + 0x20]
    lea rdx, [rip + n_hold]
    call 0x5060
    lea rcx, [rsp + 0x20]
    call 0x3d5f0
    mov qword ptr [rip + 0x11111104], rax
have_hold:
    movss xmm0, dword ptr [rax + 0x58]
    xorps xmm1, xmm1
    ucomiss xmm0, xmm1
    jbe plain
    mulss xmm0, dword ptr [rsp + 0x80]
    movss dword ptr [rsp + 0x80], xmm0
    ; * ADS fraction of the local player (client+0x2c8440)
    mov rax, qword ptr [rip + 0x11111105]
    add rax, 0x14ef40
    mov ecx, 0xffffffff
    call rax
    test rax, rax
    je plain
    mov rcx, rax
    mov rax, qword ptr [rip + 0x11111106]
    add rax, 0x2c8440
    call rax
    xorps xmm1, xmm1
    comiss xmm0, xmm1
    jbe plain
    minss xmm0, dword ptr [rip + one]
    mulss xmm0, dword ptr [rsp + 0x80]
    movss dword ptr [rsp + 0x80], xmm0          ; t
    ; q = (x, y, z, w) at copy + 0x10
    movss xmm4, dword ptr [rsp + 0x50]          ; qx
    movss xmm5, dword ptr [rsp + 0x54]          ; qy
    movss xmm6, dword ptr [rsp + 0x58]          ; qz (xmm6/xmm7 saved below)
    movss xmm7, dword ptr [rsp + 0x5c]          ; qw
    ; forward f = q * (0,0,-1): fx = -2(xz + wy), fy = -2(yz - wx), fz = 2(xx + yy) - 1
    movaps xmm0, xmm4
    mulss xmm0, xmm6
    movaps xmm1, xmm7
    mulss xmm1, xmm5
    addss xmm0, xmm1
    mulss xmm0, dword ptr [rip + minus_two]
    movss dword ptr [rsp + 0x84], xmm0          ; fx
    movaps xmm0, xmm5
    mulss xmm0, xmm6
    movaps xmm1, xmm7
    mulss xmm1, xmm4
    subss xmm0, xmm1
    mulss xmm0, dword ptr [rip + minus_two]
    movss dword ptr [rsp + 0x88], xmm0          ; fy
    movaps xmm0, xmm4
    mulss xmm0, xmm4
    movaps xmm1, xmm5
    mulss xmm1, xmm5
    addss xmm0, xmm1
    addss xmm0, xmm0
    subss xmm0, dword ptr [rip + one]
    movss dword ptr [rsp + 0x8c], xmm0          ; fz
    ; len = |(fx, fz)|; skip when looking straight up or down
    movss xmm0, dword ptr [rsp + 0x84]
    mulss xmm0, xmm0
    movss xmm1, dword ptr [rsp + 0x8c]
    mulss xmm1, xmm1
    addss xmm0, xmm1
    sqrtss xmm0, xmm0
    comiss xmm0, dword ptr [rip + tiny]
    jbe plain
    ; h = (fx, 0, fz) / len ; r = normalize(fy*hz, 0, -fy*hx, 1 + len)
    movss xmm1, dword ptr [rsp + 0x84]
    divss xmm1, xmm0                            ; hx
    movss xmm2, dword ptr [rsp + 0x8c]
    divss xmm2, xmm0                            ; hz
    movss xmm3, dword ptr [rsp + 0x88]          ; fy
    mulss xmm2, xmm3                            ; rx = fy*hz
    mulss xmm1, xmm3
    xorps xmm3, xmm3
    subss xmm3, xmm1
    movaps xmm1, xmm3                           ; rz = -fy*hx (no aligned SSE memory operands here)
    addss xmm0, dword ptr [rip + one]           ; rw = 1 + len
    ; normalize r
    movaps xmm3, xmm2
    mulss xmm3, xmm2
    movss dword ptr [rsp + 0x90], xmm3
    movaps xmm3, xmm1
    mulss xmm3, xmm1
    addss xmm3, dword ptr [rsp + 0x90]
    movss dword ptr [rsp + 0x90], xmm3
    movaps xmm3, xmm0
    mulss xmm3, xmm0
    addss xmm3, dword ptr [rsp + 0x90]
    sqrtss xmm3, xmm3
    divss xmm2, xmm3
    divss xmm1, xmm3
    divss xmm0, xmm3
    ; blend with identity: r_t = normalize(t*r + (1-t)*(0,0,0,1))
    movss xmm3, dword ptr [rsp + 0x80]
    mulss xmm2, xmm3
    mulss xmm1, xmm3
    mulss xmm0, xmm3
    addss xmm0, dword ptr [rip + one]
    subss xmm0, xmm3
    movaps xmm3, xmm2
    mulss xmm3, xmm2
    movss dword ptr [rsp + 0x90], xmm3
    movaps xmm3, xmm1
    mulss xmm3, xmm1
    addss xmm3, dword ptr [rsp + 0x90]
    movss dword ptr [rsp + 0x90], xmm3
    movaps xmm3, xmm0
    mulss xmm3, xmm0
    addss xmm3, dword ptr [rsp + 0x90]
    sqrtss xmm3, xmm3
    divss xmm2, xmm3                            ; rx
    divss xmm1, xmm3                            ; rz
    divss xmm0, xmm3                            ; rw
    ; q' = r * q (ry = 0):
    ;   x' = rw*qx + rx*qw - rz*qy      y' = rw*qy - rx*qz + rz*qx
    ;   z' = rw*qz + rx*qy + rz*qw      w' = rw*qw - rx*qx - rz*qz
    movaps xmm3, xmm0
    mulss xmm3, xmm4
    movss dword ptr [rsp + 0x90], xmm3
    movaps xmm3, xmm2
    mulss xmm3, xmm7
    addss xmm3, dword ptr [rsp + 0x90]
    movss dword ptr [rsp + 0x90], xmm3
    movaps xmm3, xmm1
    mulss xmm3, xmm5
    movss xmm8, dword ptr [rsp + 0x90]
    subss xmm8, xmm3                            ; x'
    movaps xmm3, xmm0
    mulss xmm3, xmm5
    movss dword ptr [rsp + 0x90], xmm3
    movaps xmm3, xmm2
    mulss xmm3, xmm6
    movss xmm9, dword ptr [rsp + 0x90]
    subss xmm9, xmm3
    movaps xmm3, xmm1
    mulss xmm3, xmm4
    addss xmm9, xmm3                            ; y'
    movaps xmm3, xmm0
    mulss xmm3, xmm6
    movss xmm10, xmm3
    movaps xmm3, xmm2
    mulss xmm3, xmm5
    addss xmm10, xmm3
    movaps xmm3, xmm1
    mulss xmm3, xmm7
    addss xmm10, xmm3                           ; z'
    movaps xmm3, xmm0
    mulss xmm3, xmm7
    movss xmm11, xmm3
    movaps xmm3, xmm2
    mulss xmm3, xmm4
    subss xmm11, xmm3
    movaps xmm3, xmm1
    mulss xmm3, xmm6
    subss xmm11, xmm3                           ; w'
    movss dword ptr [rsp + 0x50], xmm8
    movss dword ptr [rsp + 0x54], xmm9
    movss dword ptr [rsp + 0x58], xmm10
    movss dword ptr [rsp + 0x5c], xmm11
plain:
    mov rcx, rsi
    mov rdx, rdi
    mov r8, rbp
    lea r9, [rsp + 0x40]
    call 0x82670
    add rsp, 0xa8
    pop rbp
    pop rdi
    pop rsi
    pop rbx
    ret
    int3
    int3
    int3
    int3
    int3
    int3
    int3
    int3
    int3
    int3
    int3
    int3
one:
    .long 0x3f800000
minus_two:
    .long 0xc0000000
tiny:
    .long 0x3a83126f
n_barf:
    .asciz "tf2vr_barf_mode"
n_hold:
    .asciz "tf2vr_ads_hold"
'''

# xmm6-xmm11 are callee-saved in the Windows x64 ABI: save them around the body
asm = asm.replace("    sub rsp, 0xa8\n", "    sub rsp, 0xa8\n" + "".join(
    f"    movups xmmword ptr [rsp + {0x98 - 0x10 * i + 0x100:#x}], xmm{6 + i}\n" for i in range(6)), 1)
asm = asm.replace("    sub rsp, 0xa8\n", "    sub rsp, 0x1a8\n", 1)
asm = asm.replace("plain:\n", "plain:\n" + "".join(
    f"    movups xmm{6 + i}, xmmword ptr [rsp + {0x98 - 0x10 * i + 0x100:#x}]\n" for i in range(6)), 1)
asm = asm.replace("    add rsp, 0xa8\n", "    add rsp, 0x1a8\n", 1)

ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_64)
enc, _ = ks.asm(asm.replace(";", "#"), START)
code = bytearray(enc)
# fix the rip-relative references to the plugin's globals (placeholders 0x111111NN)
targets = {0x11111101: G_BARF, 0x11111102: G_BARF, 0x11111103: G_HOLD, 0x11111104: G_HOLD,
           0x11111105: CLIENT, 0x11111106: CLIENT, 0x11111107: IS_TITAN}
for ph, target in targets.items():
    i = code.find(struct.pack('<I', ph))
    assert i >= 0 and code.find(struct.pack('<I', ph), i + 1) < 0, hex(ph)
    code[i:i + 4] = struct.pack('<i', target - (START + i + 4))   # all are plain loads/stores, no trailing imm
code = bytes(code)
assert START + len(code) <= LIMIT

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
end_code = code.find(b'\xcc' * 12)
for x in md.disasm(code[:end_code], START):
    r = re.search(r'\[rip \+ (0x[0-9a-f]+)\]', x.op_str)
    t = f'  -> {x.address + x.size + int(r.group(1), 16):#x}' if r else ''
    print(f'{x.address:x} {x.mnemonic} {x.op_str}{t}')
print('len', hex(len(code)), 'end', hex(START + len(code)))
pe = pefile.PE(sys.argv[1], fast_load=True)
print('EXP', pe.get_data(START, len(code)).hex())
print('NEW', code.hex())
for site in (0x87589, 0x4371b):
    print(f'{site:x}', pe.get_data(site, 5).hex(), '->', (b'\xe8' + struct.pack('<i', START - (site + 5))).hex())
