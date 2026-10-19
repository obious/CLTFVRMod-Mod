# regenerates the barf mode / skip calibration helpers at 0x43790 (dead body of 0x435a0)
# usage: cave_pc.py <untouched Titanfall2VR.dll>
import struct, sys, capstone, pefile, re
START = 0x43790
CLIENT, G_BARF, G_CAL = 0x31d6c0, 0x31eca0, 0x31eca8
F_STR, F_CV, SINF, COSF, BODYMAT = 0x5060, 0x3d5f0, 0x112864, 0x112840, 0x30bf0
DEG2RAD = 0x16cf0c
EYE_POSITION_SLOT = 0x5a0   # C_BasePlayer vtable slot 180 = client+0x2c3f40, EyePosition(this, Vector* out)
code = bytearray(); fix = []; labels = {}
def emit(b): code.extend(b)
def rip(op, t, tr=b''):
    p = len(code) + len(op); code.extend(op + b'\0\0\0\0' + tr); fix.append((p, t, 4 + len(tr)))
def j8(op, l): code.extend(bytes([op, 0])); fix.append((len(code) - 1, l, 'r8'))
def j32(op2, l): code.extend(b'\x0f' + bytes([op2]) + b'\0\0\0\0'); fix.append((len(code) - 4, l, 4))
def label(n): labels[n] = len(code)
def cvlookup(g, name, tag):
    rip(b'\x48\x8b\x05', g); emit(b'\x48\x85\xc0'); j8(0x75, 'h' + tag)
    emit(b'\x48\x8d\x4c\x24\x20'); rip(b'\x48\x8d\x15', name); rip(b'\xe8', F_STR)
    emit(b'\x48\x8d\x4c\x24\x20'); rip(b'\xe8', F_CV); rip(b'\x48\x89\x05', g)
    label('h' + tag)
# ---- pitch: replaces call 0x30bf0 at 0x91391 (rcx=out, rdx=&origin, xmm2=yaw deg) ----
# body matrix M (world -> body, rows r0..r3, translation in .w) is pitched about the body x axis, pivoting at the
# player's eye: M' = T(q) Rx T(-q) M with q = M * eye, so the camera stays at the eye instead of swinging around
# the body origin (which sank the view into the chest when looking down)
# stack: 0x40 scale/angle, 0x44 eye angles, 0x50 sin, 0x60 eye position (w = 1), 0x70 q.y, 0x74 q.z
label('pitch')
emit(b'\x53\x56\x48\x81\xec\x88\x00\x00\x00')                   # push rbx ; push rsi ; sub rsp, 0x88
rip(b'\xe8', BODYMAT); emit(b'\x48\x89\xc3')                    # rbx = body matrix
cvlookup(G_BARF, 'n_barf', 'b')
emit(b'\xf3\x0f\x10\x40\x58\x0f\x57\xc9\x0f\x2e\xc1')            # xmm0 = scale ; ucomiss xmm0,0
j32(0x84, 'p_done'); j32(0x8a, 'p_done')                       # 0 or NaN -> unchanged
emit(b'\xf3\x0f\x11\x44\x24\x40')
rip(b'\x48\x8b\x05', CLIENT); emit(b'\x48\x05' + struct.pack('<i', 0x14ef40) + b'\xb9\xff\xff\xff\xff\xff\xd0')
emit(b'\x48\x85\xc0'); j32(0x84, 'p_done')
emit(b'\x48\x89\xc6')                                          # rsi = player
emit(b'\x48\x89\xf1\x48\x8d\x54\x24\x44')
rip(b'\x48\x8b\x05', CLIENT); emit(b'\x48\x05' + struct.pack('<i', 0x2c53c0) + b'\xff\xd0')   # eye angles
emit(b'\x48\x89\xf1\x48\x8d\x54\x24\x60\x48\x8b\x06')          # rcx = player ; rdx = &eye ; rax = vtable
emit(b'\xff\x90' + struct.pack('<i', EYE_POSITION_SLOT))        # EyePosition
emit(b'\xc7\x44\x24\x6c\x00\x00\x80\x3f')                      # eye.w = 1
emit(b'\xf3\x0f\x10\x44\x24\x44\xf3\x0f\x59\x44\x24\x40'); rip(b'\xf3\x0f\x59\x05', DEG2RAD)
emit(b'\xf3\x0f\x11\x44\x24\x40'); rip(b'\xe8', SINF); emit(b'\xf3\x0f\x11\x44\x24\x50')
emit(b'\xf3\x0f\x10\x44\x24\x40'); rip(b'\xe8', COSF)
emit(b'\xf3\x0f\x10\x4c\x24\x50')                              # xmm0 = c, xmm1 = s
emit(b'\x0f\x10\x64\x24\x60')                                  # xmm4 = (eye, 1)
emit(b'\x0f\x10\x53\x10\x0f\x59\xd4\xf2\x0f\x7c\xd2\xf2\x0f\x7c\xd2\xf3\x0f\x11\x54\x24\x70')   # q.y = r1 . eye
emit(b'\x0f\x10\x5b\x20\x0f\x59\xdc\xf2\x0f\x7c\xdb\xf2\x0f\x7c\xdb\xf3\x0f\x11\x5c\x24\x74')   # q.z = r2 . eye
emit(b'\xf3\x0f\x10\x53\x1c\xf3\x0f\x5c\x54\x24\x70\xf3\x0f\x11\x53\x1c')   # r1.w -= q.y
emit(b'\xf3\x0f\x10\x5b\x2c\xf3\x0f\x5c\x5c\x24\x74\xf3\x0f\x11\x5b\x2c')   # r2.w -= q.z
emit(b'\x0f\x10\x53\x10\x0f\x10\x5b\x20')                      # r1, r2
emit(b'\x0f\xc6\xc0\x00\x0f\xc6\xc9\x00')
emit(b'\x0f\x28\xe2\x0f\x59\xe0\x0f\x28\xeb\x0f\x59\xe9\x0f\x5c\xe5')   # r1' = c*r1 - s*r2
emit(b'\x0f\x59\xd1\x0f\x59\xd8\x0f\x58\xd3')                  # r2' = s*r1 + c*r2
emit(b'\x0f\x11\x63\x10\x0f\x11\x53\x20')
emit(b'\xf3\x0f\x10\x53\x1c\xf3\x0f\x58\x54\x24\x70\xf3\x0f\x11\x53\x1c')   # r1.w += q.y
emit(b'\xf3\x0f\x10\x5b\x2c\xf3\x0f\x58\x5c\x24\x74\xf3\x0f\x11\x5b\x2c')   # r2.w += q.z
label('p_done'); emit(b'\x48\x89\xd8\x48\x81\xc4\x88\x00\x00\x00\x5e\x5b\xc3')
# ---- calibration skip: jmp from 0x8281a (test r9b,r9b ; je 0x82831) ----
label('cal')
emit(b'\x45\x84\xc9'); j32(0x85, 0x8281f)
emit(b'\x51\x52\x41\x50\x41\x51\x48\x83\xec\x40')
cvlookup(G_CAL, 'n_cal', 'c')
emit(b'\x8b\x40\x5c\x48\x83\xc4\x40\x41\x59\x41\x58\x5a\x59\x85\xc0')
j32(0x85, 0x8281f)
code.extend(b'\xe9\0\0\0\0'); fix.append((len(code) - 4, 0x82831, 4))
while len(code) % 4: emit(b'\xcc')
label('n_barf'); emit(b'tf2vr_barf_mode\0')
label('n_cal'); emit(b'tf2vr_skip_cal\0')
for p, t, k in fix:
    if k == 'r8':
        code[p] = labels[t] - (p + 1); assert 0 <= code[p] < 128, t
    else:
        tt = START + labels[t] if isinstance(t, str) else t
        code[p:p+4] = struct.pack('<i', tt - (START + p + k))
code = bytes(code)
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
for x in md.disasm(code[:labels['n_barf']], START):
    r = re.search(r'\[rip \+ (0x[0-9a-f]+)\]', x.op_str); t = f'  -> {x.address+x.size+int(r.group(1),16):#x}' if r else ''
    print(f'{x.address:x} {x.mnemonic} {x.op_str}{t}')
print({k: hex(v+START) for k, v in labels.items()}, 'len', hex(len(code)), 'end', hex(START+len(code)))
pe = pefile.PE(sys.argv[1], fast_load=True)
print('EXP', pe.get_data(START, len(code)).hex()); print('NEW', code.hex())
print('91391', pe.get_data(0x91391,5).hex(), '->', (b'\xe8'+struct.pack('<i', START+labels['pitch']-0x91396)).hex())
print('8281a', pe.get_data(0x8281a,5).hex(), '->', (b'\xe9'+struct.pack('<i', START+labels['cal']-0x8281f)).hex())
