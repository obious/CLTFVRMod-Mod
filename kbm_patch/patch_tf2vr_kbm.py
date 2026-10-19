"""Patch Titanfall2VR.dll so keyboard/mouse drive the game while the headset still drives the camera.

Usage:  python patch_tf2vr_kbm.py [path\to\Titanfall2VR.dll] [--restore] [--vr-rig] [--size=WxH]
        --vr-rig keeps the plugin's VR hand/weapon rig instead of the game's own viewmodel.
        --size sets the game window size; the default is the primary monitor's resolution.
Every site is checked against its expected bytes first; nothing is written unless all match.
The untouched DLL is kept next to it as Titanfall2VR.dll.orig.
"""
import shutil, struct, sys
from pathlib import Path

# Offsets are for the Titanfall2VR.dll build with sha256 6b550331c178...23f3 (Oct 9 2026).


def lea_retarget(insn_rva, new_target_rva):
    # rewrites the disp32 of a 7-byte `lea reg, [rip+disp]`
    return struct.pack('<i', new_target_rva - (insn_rva + 7))


# The plugin applies byte patches through a table: (module, offset, original bytes [r8], patched bytes [r9]).
# Pointing r9 at the original bytes turns each patch into a no-op.
TABLE_PATCHES = {
    # name: (rva of `lea r9`, r9 target, r8 target)
    'client.disableMouse':              (0x1abe3, 0x1424e2, 0x1424e0),
    'inputSystem.disableCursorWarp':    (0x1ab25, 0x14284d, 0x142848),
    'inputSystem.disableCursorCapture': (0x1ab57, 0x142825, 0x142820),
    'inputSystem.disableCursorShape':   (0x1ab89, 0x142804, 0x142800),
}

PATCHES = [
    # (description, rva, expected, replacement)
    ('window hook: stop dropping mouse messages (ja -> jmp)', 0x31408, b'\x77\x04', b'\xeb\x04'),
    ('movement hook: keep keyboard forward/side move (je -> jmp)', 0x32677, b'\x74\x1a', b'\xeb\x1a'),
    # command hook: while the VR magazine mechanic is active it strips button 0x1000 (reload), sometimes fire too
    ('command hook: keep the reload button (je -> jmp)', 0x31666, b'\x74\x39', b'\xeb\x39'),
    ('window: do not add a resize frame (or rbx, 0x50000 -> 0)', 0x1f95e,
     bytes.fromhex('4881cb00000500'), bytes.fromhex('4881cb00000000')),
    ('window: move to 0,0 (SetWindowPos flags 0x36 -> 0x34)', 0x1fa7c,
     bytes.fromhex('c744243036000000'), bytes.fromhex('c744243034000000')),
    # inputsystem reads the cursor position for mouse deltas; the plugin substitutes its laser pointer
    ('cursor hook: always report the real cursor (je rel32 -> jmp rel32)', 0x9a4ae,
     b'\x0f\x84\x96\x00\x00\x00', b'\xe9\x97\x00\x00\x00\x90'),
]


def screen_size():
    for arg in sys.argv:
        if arg.startswith('--size='):
            width, height = arg.split('=', 1)[1].lower().split('x')
            return int(width), int(height)
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # physical pixels, not the scaled desktop size
    return ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)


# The plugin sizes the game window once to a 1280x720 resizable "desktop mirror". Make it a fixed window
# covering the primary monitor at 0,0, so the game's own mouse capture keeps the cursor inside it.
_width, _height = screen_size()
PATCHES.append((f'window: client area 1280x720 -> {_width}x{_height}', 0x16d6a0,
                struct.pack('<4i', 0, 0, 1280, 720), struct.pack('<4i', 0, 0, _width, _height)))


def mouse_yaw_block():
    """Replaces the command hook's "overwrite view angles with VR aim" block (0x3152f..0x31579, now unused).

    The usercmd keeps the mouse's view angles; each command, the change in its yaw is added to the
    plugin's body yaw so the headset camera turns with the mouse. Jumps over 90 degrees (yaw wrap,
    teleports, level loads) are ignored. Falls through to 0x3157a, where the hook continues.
    """
    start, end = 0x3152f, 0x3157a
    PREV_YAW, SEEN = 0x31ec60, 0x31ec64   # spare zeroed bytes past the end of .data, inside its RW page
    BODY_YAW, ABS_MASK, NINETY = 0x2ca508, 0x16daf0, 0x16d1e0
    code = bytearray()

    def rip(opcode, target, trailing=b''):
        insn_end = start + len(code) + len(opcode) + 4 + len(trailing)
        code.extend(opcode + struct.pack('<i', target - insn_end) + trailing)

    code += b'\xf3\x0f\x10\x43\x10'          # movss  xmm0, [rbx+0x10]      ; cmd yaw (mouse)
    code += b'\x0f\x28\xc8'                  # movaps xmm1, xmm0
    rip(b'\xf3\x0f\x5c\x05', PREV_YAW)       # subss  xmm0, [prev]          ; delta
    rip(b'\xf3\x0f\x11\x0d', PREV_YAW)       # movss  [prev], xmm1
    rip(b'\x80\x3d', SEEN, b'\x00')          # cmp    byte [seen], 0
    rip(b'\xc6\x05', SEEN, b'\x01')          # mov    byte [seen], 1
    code += b'\x74' + bytes([end - (start + len(code) + 2)])        # je end (first command)
    code += b'\x0f\x28\xc8'                  # movaps xmm1, xmm0
    rip(b'\x0f\x54\x0d', ABS_MASK)           # andps  xmm1, [absmask]
    rip(b'\x0f\x2f\x0d', NINETY)             # comiss xmm1, [90.0]
    code += b'\x77' + bytes([end - (start + len(code) + 2)])        # ja end (jump too large)
    rip(b'\xf3\x0f\x58\x05', BODY_YAW)       # addss  xmm0, [body yaw]
    rip(b'\xf3\x0f\x11\x05', BODY_YAW)       # movss  [body yaw], xmm0
    assert len(code) == end - start, len(code)
    return start, bytes(code)


_start, _code = mouse_yaw_block()
PATCHES.append(('command hook: keep mouse view angles, turn the VR body with mouse yaw', _start, bytes.fromhex(
    '803d928c2900007442803dce8f29000075390f100d908c29000f28c1660f73d908f20f11430c660f7e4b14'
    '803d7f8f2900007517803dfa672e0000b8feefdeffb9ffffdfff0f45c1214340'), _code))

# The plugin swaps client.dll vtable entries to drive its VR hand/weapon rig. The install calls
# (to the slot-swap helper at 0xa3e70) can be skipped outright: the helper keeps no record and its
# result is unused, so the game keeps its own viewmodel code. Opt out with --vr-rig.
RIG_SLOT_INSTALLS = {
    'client.buildRigSlot': (0x1940b, 'e860aa0800'),
    'client.blendRigSlot': (0x19433, 'e838aa0800'),
    'client.setupRigSlot': (0x1950a, 'e861a90800'),
    'client.setupRigSlot2': (0x19532, 'e839a90800'),
    'client.setupSeatedRigSlot': (0x1955a, 'e811a90800'),
    'client.setupCinematicRigSlot': (0x19582, 'e8e9a80800'),
    'client.drawRigSlot': (0x1b1ca, 'e8a18c0800'),
    'client.setupGrenadeSlot': (0x1b1f2, 'e8798c0800'),
}
if '--vr-rig' not in sys.argv:
    for name, (rva, call) in RIG_SLOT_INSTALLS.items():
        PATCHES.append((f'vanilla viewmodel: skip {name}', rva, bytes.fromhex(call), b'\x90' * 5))
    # RUI evaluate hook (0x28fe0): crosshair RUIs (group 6 / crosshair_*) the game wants visible are hidden while
    # the player is a pilot (0x316ad0), since VR aims with the gun's sights. Leave them to the game on foot.
    PATCHES.append(('vanilla crosshair: keep the game\'s crosshair on foot (jne -> nop)', 0x29bae,
                    b'\x0f\x85\x04\xfe\xff\xff', b'\x90' * 6))
    # On foot that crosshair lands on the head-locked HUD canvas. Use the plugin's Titan reticle instead: the
    # crosshair group is captured into reticleCanvas and drawn as a quad where a trace along the aim hits.
    PATCHES += [
        # reticle trace (0x30000) runs whenever there is a local player, not only in a Titan (0x2ca4e0):
        #   movzx eax,[isTitan] -> test rcx,rcx ; setne al   (al also feeds trace-ran 0x316b50)
        ('pilot reticle: run the reticle trace on foot', 0x30020,
         bytes.fromhex('0fb605b9a42900'), bytes.fromhex('4885c90f95c090')),
        # trace origin: VR muzzle only in a Titan (valid & isTitan), else the game's eye + aim angles
        #   lea rcx,[2ca274] ; movzx eax,[rcx-4] ; and al,[2ca4e0] ; lea rdx,[rcx+0xc] ; je 0x30098 ; nop2
        ('pilot reticle: trace from the game aim on foot, muzzle in a Titan', 0x3005f,
         bytes.fromhex('0fb6050aa22900488d0d07a22900488d150ca2290084c07420'),
         bytes.fromhex('488d0d0ea229000fb641fc220570a42900488d510c74229090')),
        # frame producer: reticle-capture flag (packet +0x304 -> renderer+0x694) no longer needs isTitan
        ('pilot reticle: capture the crosshair group on foot (je -> nop)', 0x239af, b'\x74\x17', b'\x90' * 2),
        # frame producer: fill the reticle state (0x1e2f0 at 0x23cc5) on foot
        ('pilot reticle: place the reticle on foot (je -> nop)', 0x23c08,
         bytes.fromhex('0f84fd000000'), b'\x90' * 6),
        # On foot the crosshair group is drawn inside the HUD-canvas capture (renderer+0x68c), and beginning the
        # reticle capture there fail-fasts ("nested UI capture"). Two helpers in the dead tail of 0x346d0 (needs
        # the clientShotDirectionCall patch above) wrap the group-6 draw: begin ends an active capture, saving
        # its type+1 in spare byte 0x31ec68, then begins the reticle capture; end ends it and resumes the saved
        # capture for the same eye. With no active capture (Titan) they pass straight through.
        ('pilot reticle: capture helpers in dead code', 0x346e0,
         bytes.fromhex('00488b4424284981c0ad525b0048897424304c897424384c8bf24c897c24404c8bf9be10000000'
                       '493bc0752e448b057987290065488b0425580000004a8b3cc0803c37007505e8c5d00d00b84001'
                       '00008bd8803c38007407eb64bb40010000'),
         bytes.fromhex('80b98c0600000074238a8190060000fec0880571a52e00515241504883ec20e8aced08004883c4'
                       '2041585a59e91fe9080051524883ec28e894ed08004883c4285a59440fb6053ea52e004585c074'
                       '0fc60532a52e000041ffc8e9f2e80800c3')),
        ('pilot reticle: group-6 begin capture goes through the helper', 0x27036,
         bytes.fromhex('e8f5bf0900'), bytes.fromhex('e8a5d60000')),
        ('pilot reticle: group-6 end capture goes through the helper', 0x27056,
         bytes.fromhex('e855c40900'), bytes.fromhex('e8b6d60000')),
    ]
    # server weapon-frame hook (0x3d2d0): its manual-reload manager drives ammo from VR magazine
    # gestures, and it restores weapon+0x1eac after the game's frame to cancel vanilla reloads
    PATCHES += [
        # shot direction comes from the VR gun's muzzle; with no VR gun it is (0,0,0) and weapon scripts error
        ('vanilla firing: skip client.clientShotCall', 0x1962a, bytes.fromhex('e801b70800'), b'\x90' * 5),
        ('vanilla firing: skip server.serverFirePoseCall', 0x1a3bf, bytes.fromhex('e86ca90800'), b'\x90' * 5),
        # client.clientShotDirectionCall (installed from a table, so its hook can't be skipped) calls the
        # game's direction function at client+0x6274c0, then overwrites the result with the VR muzzle and
        # fail-fasts without clientShotCall; turn it into a tail jump to the game's function:
        #   mov rax, [client base] ; add rax, 0x6274c0 ; jmp rax
        ('vanilla firing: client.clientShotDirectionCall passes straight to the game', 0x346d0,
         bytes.fromhex('48895c2420574883ec204c8b05df8f'), bytes.fromhex('488b05e98f2e004805c0746200ffe0')),
        ('vanilla reload: skip the VR manual-reload manager', 0x3d36d, bytes.fromhex('e8ae690000'), b'\x90' * 5),
        ('vanilla reload: keep reloads the game starts (je -> jmp)', 0x3d5ca, b'\x74\x07', b'\xeb\x07'),
        # the per-frame VR magazine logic (client 0x435a0, server 0x44370) reads the VR command snapshot and
        # drives clip/stockpile; only the weapon-frame hooks call it. Return 0 ("don't suppress") at once.
        ('vanilla reload: client VR magazine logic returns at once', 0x435a0, b'\x48\x89\x5c', b'\x31\xc0\xc3'),
        ('vanilla reload: server VR magazine logic returns at once', 0x44370, b'\x48\x89\x5c', b'\x31\xc0\xc3'),
        # client weapon-frame hook (0x3d1a0) does the same on the predicting client with weapon+0x219c
        ('vanilla reload: keep reloads the client predicts (je -> jmp)', 0x3d27d, b'\x74\x07', b'\xeb\x07'),
    ]

for name, (r9_rva, r9_target, r8_target) in TABLE_PATCHES.items():
    PATCHES.append((f'patch table: skip {name}', r9_rva + 3,
                    lea_retarget(r9_rva, r9_target), lea_retarget(r9_rva, r8_target)))


def rva_to_offset(data, rva):
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    nsec = struct.unpack_from('<H', data, pe + 6)[0]
    opt = struct.unpack_from('<H', data, pe + 20)[0]
    sec = pe + 24 + opt
    for i in range(nsec):
        vsize, va, rawsize, raw = struct.unpack_from('<IIII', data, sec + i * 40 + 8)
        if va <= rva < va + max(vsize, rawsize):
            return raw + rva - va
    raise ValueError(f'rva {rva:#x} not in any section')


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    dll = Path(args[0]) if args else Path(__file__).resolve().parent.parent / 'plugins' / 'Titanfall2VR.dll'
    orig = dll.with_name(dll.name + '.orig')

    if '--restore' in sys.argv:
        shutil.copy2(orig, dll)
        print(f'restored {dll} from {orig.name}')
        return

    data = bytearray(dll.read_bytes())
    todo, already = [], 0
    for desc, rva, expected, replacement in PATCHES:
        off = rva_to_offset(data, rva)
        cur = bytes(data[off:off + len(expected)])
        if cur == replacement:
            already += 1
        elif cur == expected:
            todo.append((desc, off, replacement))
        else:
            sys.exit(f'ABORT: unexpected bytes for "{desc}" at rva {rva:#x}: {cur.hex()} '
                     f'(expected {expected.hex()}). The DLL was probably updated; offsets need re-finding.')
    if not todo:
        print(f'already patched ({already} sites)')
        return
    if already:
        sys.exit('ABORT: DLL is partially patched; restore it first with --restore')

    if not orig.exists():
        shutil.copy2(dll, orig)
        print(f'backup: {orig}')
    for desc, off, replacement in todo:
        data[off:off + len(replacement)] = replacement
        print(f'  patched: {desc}')
    dll.write_bytes(data)
    print(f'done, {len(todo)} sites patched')


if __name__ == '__main__':
    main()
