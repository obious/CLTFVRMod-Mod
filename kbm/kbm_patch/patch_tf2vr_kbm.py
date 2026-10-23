r"""Patch Titanfall2VR.dll so keyboard/mouse drive the game while the headset still drives the camera.

Usage:  python patch_tf2vr_kbm.py [path\to\Titanfall2VR.dll] [--restore] [--vr-rig] [--size=WxH]
        python patch_tf2vr_kbm.py path\to\untouched\Titanfall2VR.dll --export=kbm.json
        --vr-rig keeps the plugin's VR hand/weapon rig instead of the game's own viewmodel.
        --size sets the game window size; the default is the primary monitor's resolution.
        --export writes the patch set the launcher applies (run it after changing any patch).
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
WINDOW_RVA = 0x16d6a0
_width, _height = screen_size()
PATCHES.append((f'window: client area 1280x720 -> {_width}x{_height}', WINDOW_RVA,
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
        # End (0xc34b0) also binds the plugin's blend state [renderer+0x1b8] behind materialsystem's state cache,
        # so the game's bound blend state is saved (0x31ec80/88/98) and put back after each end; otherwise the
        # HUD groups drawn after the crosshair (damage overlay) draw opaque and cover the HUD.
        ('pilot reticle: capture helpers in dead code', 0x346e0,
         bytes.fromhex('00488b4424284981c0ad525b0048897424304c897424384c8bf24c897c24404c8bf9be10000000493bc075'
                       '2e448b057987290065488b0425580000004a8b3cc0803c37007505e8c5d00d00b8400100008bd8803c3800'
                       '7407eb64bb40010000488d1542091100488d0d93452e00e87e11fdff488bc8b20ae85413fdff488d0d7d45'
                       '2e00ff155f6d0f00b902000000ff15f4710f00488bc84c8d050a091100488d15bbaf0f00e856d0fcff488d'
                       '0df7081100ff15296a0f00b907000000cd29488b051b8f2e00498bd64805c0746200498bcfffd08b0dd386'
                       '290065488b0425580000004c8b7c2440488b3cc8803c37007505e81ad00d00ba00030000488d0dda'),
         bytes.fromhex('80b98c0600000074588a8190060000fec0880571a52e00515241504883ec20488b4908488b01488d1573a5'
                       '2e004c8d0574a52e004c8d0d7da52e00ff90d8020000488b4c24308b542428e881ed0800488b4c2430e87b'
                       '0000004883c42041585a59e9eae8080051524883ec28e85fed08004883c4285a59440fb60509a52e004585'
                       'c0744fc605fda42e000041ffc8515241504883ec20e839000000488b4c24308b542428448b442420e8a2e8'
                       '0800488b0deba42e004885c97411488b01ff501048c705d5a42e00000000004883c42041585a59c34883ec'
                       '28488b4908488b01488b15baa42e004c8d05bba42e00448b0dc4a42e00ff90180100004883c428c3')),
        ('pilot reticle: group-6 begin capture goes through the helper', 0x27036,
         bytes.fromhex('e8f5bf0900'), bytes.fromhex('e8a5d60000')),
        ('pilot reticle: group-6 end capture goes through the helper', 0x27056,
         bytes.fromhex('e855c40900'), bytes.fromhex('e8ebd60000')),
    ]
    # Dominant-eye ADS: the game places the viewmodel for its one camera at the head centre, so with both eyes
    # rendering it the sights sit between them. The viewmodel group-view hook (0x88220) rebuilds the viewmodel's
    # per-eye view from the eye pose only in "DISTANT" mode (0x2ca51f); otherwise it equals the world eye view.
    # Always rebuild it, through a helper (dead body of 0x435a0, needs the VR-magazine patch above) that moves
    # both viewmodel eye cameras by -0.5*tf2vr_ads_eye*(R-L) and up by tf2vr_ads_drop (metres), times the game's
    # ADS fraction. ConVar pointers are cached at 0x31ec70/78; TF2VR.Minimal must define both convars.
    PATCHES += [
        ('ADS eye: always rebuild the viewmodel view from the eye pose (je -> nop)', 0x88267,
         bytes.fromhex('0f848b000000'), b'\x90' * 6),
        ('ADS eye: viewmodel eye-pose helper in dead code', 0x435b0,
         bytes.fromhex(
          '41544155415641574881ec90010000488b05ba9b14004833c44889842480010000488bf9488b05e5a02d00480540ef1400'
          'b9ffffffffffd0488be88b9f341200004885c00f84f106000083fbff0f84e80600000fb7f381fe004000007235b9020000'
          '00ff154f830e00488bc84c8d056d1e1000488d1516c10e00e8b1e1fbff488d0d5a1e1000ff15847b0e00b907000000cd29'
          'c1e6058bc6488b0d71a02d0048038130f0b000483968080f858b060000c1eb10395810745f488d15c9241000488d0d6a56'
          '2d00e85522fcff488bc8b20ae82b24fcff488d0d54562d00ff15367e0e00b902000000ff15cb820e00488bc84c8d059124'
          '1000488d1592c00e00e82de1fbff488d0d7e241000ff15007b0e00b907000000cd29488b9d582a00004885db0f84140600'
          '00448b33458bc6488d542430488d0d279e1400e852dafeff448bbf50120000448baf5412000080bc24d0000000000f84e1'
          '050000448ba424c8000000443ba7c81500000f85cc0500008b4b04394c24340f94c3742a488d1566241000488d0da7552d'
          '00e89221fcff488bc8b20ae86823fcff488d0d91552d00ff15737d0e0084db7535b9020000'),
         bytes.fromhex(
          '5356574881eca00000004889ce4889d74c898424900000004c89cb0f10030f114424400f1043100f114424500f1043200f'
          '114424600f1043300f11442470488b057bb62d004885c07522488d4c2420488d153a010000e8551afcff488d4c2420e8db'
          '9fffff48890554b62d00488b0555b62d004885c07522488d4c2420488d151a010000e8271afcff488d4c2420e8ad9fffff'
          '4889052eb62d000f57c0f30f11842498000000488b0563a02d00480540ef1400b9ffffffffffd04885c00f84950000004889'
          'c1488b0543a02d00480540842c00ffd0f30f118424980000000f57c90f2fc10f866e000000488b05cfb52d00f30f105058'
          '488b05cbb52d00f30f105858f30f59d0f30f59156e000000f30f59d8488b05971e28000f10a0e80800000f10a8a8080000'
          '0f5ce50fc6d2000f59e20f102d480000000f54e50f106c24600f58ec0f116c2460f30f10642464f30f58e3f30f11642464'
          '4889f14889fa4c8b8424900000004c8d4c2440e8800200004881c4a00000005f5e5bc3cc000000bfffffffffffffffffff'
          'ffffff0000000074663276725f6164735f6579650074663276725f6164735f64726f7000')),
        ('ADS eye: viewmodel eye view goes through the helper', 0x8829e,
         bytes.fromhex('e8cda3ffff'), bytes.fromhex('e80db3fbff')),
    ]
    # Optic reticles: the RUI evaluate hook drops draw-group-1 RUIs (weapon RUIs, incl. hcog/holo sight reticles)
    # unless 0x317bb8 (Titan / VR weapon held) is set, which never happens on foot with the stock viewmodel.
    PATCHES += [
        ('optic reticle: keep the game\'s weapon/sight RUIs on foot (je -> nop)', 0x2919c,
         bytes.fromhex('0f843c0c0000'), b'\x90' * 6),
        # drawWeaponRui hook (0x2fc00) draws weapon RUIs with the game's view at client+0x22abd00, which the ADS
        # eye shift doesn't touch; for that view first rebuild it via 0x88220 (eye pose -> ADS helper), then
        # projection as before:  mov rax,[client] ; add rax,0x22abd00 ; cmp rcx,rax ; jne p ; push rcx ;
        # sub rsp,0x20 ; call 0x88220 ; add rsp,0x20 ; pop rcx ; p: jmp 0x881b0
        ('optic reticle: weapon-RUI view helper in dead code', 0x43760,
         bytes.fromhex('04820e00488bc84c8d052a241000488d15cbbf0e00e866e0fbff488d0d17241000ff15397a0e'),
         bytes.fromhex('488b05599f2d00480500bd2a024839c1750f514883ec20e8a44a04004883c42059e92a4a0400')),
        ('optic reticle: weapon-RUI view goes through the helper', 0x2fd9f,
         bytes.fromhex('e80c840500'), bytes.fromhex('e8bc390100')),
    ]
    # Barf mode (tf2vr_barf_mode): each frame 0x30bf0 (called at 0x91391) builds the yaw-only world -> body matrix
    # 0x2c7ec8 that both eye-view builders apply to the headset pose. The helper (0x43790) calls it, then pitches the
    # body by the game's aim pitch (client+0x2c53c0) times the convar, so mouse up/down tilts the view; 0 leaves it.
    # The pitch pivots at the player's eye (EyePosition, vtable slot 180 = client+0x2c3f40, mapped through the
    # matrix), not the body origin, so looking down doesn't swing the view into the chest.
    # Assembled by kbm_patch/re/cave_barf.py.
    # Skip calibration (tf2vr_skip_cal): the startup state machine 0x82800 only jumps to "done" (phase 5) once a
    # local player exists (0x8281a); the helper (0x4388d) also takes that path when the convar is set.
    # Both helpers sit in the dead body of 0x435a0 (needs the VR-magazine patch); ConVar* cached at 0x31eca0/a8.
    PATCHES += [
        ('barf mode / skip calibration: helpers in dead code', 0x43790,
         bytes.fromhex(
          '447a0e003b05f64628000f94c3742a488d15ca231000488d0d33552d00e81e21fcff488bc8b20ae8f422fcff488d0d1d552d00ff'
          '15ff7c0e0084db7535b902000000ff1590810e00488bc84c8d058e231000488d1557bf0e00e8f2dffbff488d0d7b231000ff15c5'
          '790e00b907000000cd29c6879c210000000fb6b424d20000004084f6741a488b05a39e2d004805e0845b004533c94533c033d248'
          '8bcfffd08b9c24cc000000f6c3100f84800000004585ff7f5f488d1594231000488d0d8d542d00e87820fcff488bc8b20ae84e22'
          'fcff488d0d77542d00ff15597c0e00b902000000ff15ee800e00488bc84c8d055c231000488d15b5be0e00e850dffbff488d0d49'
          '231000ff1523790e00b907000000cd29418d57ff488b05119e2d004805e0845b004533c94533c0488bcfffd0b9ffffff7ff6c302'
          '0f84e90000004084f60f85e00000008bc3c1e802a8010f84c1000000c7842470010000010000008b875412000089842474010000'
          '8b977c18000085d20f48d18b87701800003bd00f4cc22b875012000089842478010000488d8c2470010000488d94247c010000e8'
          '0cd70c008bf085c07935b902000000ff1523800e00488bc84c8d05d9231000488d15eabd0e00e885defbff488d0dc6231000ff15'
          '58780e00b907000000cd298b975012000003d6488b05429d2d004805e0845b004533c94533c0488bcfffd0488b052a9d2d004805'
          'a0685b'),
         bytes.fromhex(
          '53564881ec88000000e852d4feff4889c3488b05f8b42d004885c07522488d4c2420488d15c3010000e8a218fcff488d4c2420e8'
          '289effff488905d1b42d00f30f1040580f57c90f2ec10f84310100000f8a2b010000f30f11442440488b05cd9e2d00480540ef14'
          '00b9ffffffffffd04885c00f84080100004889c64889f1488d542444488b05a59e2d004805c0532c00ffd04889f1488d54246048'
          '8b06ff90a0050000c744246c0000803ff30f10442444f30f59442440f30f5905bc961200f30f11442440e809f00c00f30f114424'
          '50f30f10442440e8d4ef0c00f30f104c24500f106424600f1053100f59d4f20f7cd2f20f7cd2f30f115424700f105b200f59dcf2'
          '0f7cdbf20f7cdbf30f115c2474f30f10531cf30f5c542470f30f11531cf30f105b2cf30f5c5c2474f30f115b2c0f1053100f105b'
          '200fc6c0000fc6c9000f28e20f59e00f28eb0f59e90f5ce50f59d10f59d80f58d30f1163100f115320f30f10531cf30f58542470'
          'f30f11531cf30f105b2cf30f585c2474f30f115b2c4889d84881c4880000005e5bc34584c90f85f8ee03005152415041514883ec'
          '40488b0570b32d004885c07522488d4c2420488d1543000000e81217fcff488d4c2420e8989cffff48890549b32d008b405c4883'
          'c440415941585a5985c00f85abee0300e9b8ee0300cccccc74663276725f626172665f6d6f64650074663276725f736b69705f63'
          '616c00')),
        # ADS view hold (tf2vr_ads_hold, with barf mode, on foot only): wrapper of the eye-view builder 0x82670 that renders
        # the eye without the head's pitch, scaled by the ADS fraction, so the view's up/down is exactly the mouse
        # aim and sights line up vertically. Main eye views (0x87589) and the ADS eye helper's viewmodel views
        # (its call at 0x4371b, above) use it; submitted poses stay real. ConVar* cached at 0x31ecb0.
        # Assembled by kbm_patch/re/cave_adshold.py.
        ('ADS pitch hold: helper in dead code', 0x439a0,
         bytes.fromhex(
          'cfffd0eb12488b05149d2d004805f05b5a00488bcfffd08bb7501200008baf54120000488d059e9914004889842470010000488b'
          'c8ff15dd790e0085c0740cb905000000ff157e790e00cc813dbf991400ffffff7f7516c705b3991400feffff7fb906000000ff15'
          '5c790e00900fb6052c9a280084c00f8496000000488d1599131000488d0db6942d00e8a11efcff0fb6050a9a280084c07478b22c'
          '488d0d9d942d00e86820fcff0fb605f199280084c0745f418bd6488d0d83942d00ff15a57a0e000fb605d699280084c07444b22c'
          '488d0d69942d00e83420fcff0fb605bd99280084c0742b488b542438488d0d4d942d00ff151f7a0e000fb605a099280084c0740e'
          'b22c488d0d33942d00e8fe1ffcffff1520770e000fb60d8199280084c90f84130200008bd0488d0d10942d00ff15da790e000fb6'
          '0d6399280084c90f84f5010000b22c488d0df2932d00e8bd1ffcff0fb60d4699280084c90f84d80100008bd3488d0dd5932d00ff'
          '15f7790e000fb60d2899280084c90f84ba010000b22c488d0db7932d00e8821ffcff0fb60d0b99280084c90f849d0100000fb694'
          '24d1000000488d0d94932d00ff15ae790e000fb60de798280084c90f8479010000b22c488d0d76932d00e8411ffcff0fb60dca98'
          '280084c90f845c010000418bd7488d0d58932d00ff15aa790e000fb60dab98280084c90f843d010000b22c488d0d3a932d00e805'
          '1ffcff0fb60d8e98280084c90f84200100008bd6488d0d1d932d00ff156f790e000fb60d7098280084c90f8402010000b22c488d'
          '0dff922d00e8ca1efcff0fb60d5398280084c90f84e5000000418bd5488d0de1922d00ff1533790e000fb60d3498280084c90f84'
          'c6000000b22c488d0dc3922d00e88e1efcff0fb60d1798280084c90f84a90000008bd5488d0da6922d00ff15f8780e000fb60df9'
          '97280084c90f848b000000b22c488d0d88922d00e8531efcff0fb60ddc97280084c97472488bd7488d0d6e922d00ff15c8780e00'
          '0fb60dc197280084c97457b22c488d0d54922d00e81f1efcff0fb60da897280084c9743e418bd4488d0d3a922d00ff155c780e00'
          '803d8d972800007425b20a488d0d22922d00e8ed1dfcff803d7697280000740e488d0d0d922d00ff15ef770e0090488d0d879614'
          '00ff15e1760e00b001eb0232c0488b8c24800100004833cce843d50c004c8d9c2490010000498b5b38498b6b40498b7348498be3'
          '415f415e415d415c5fc3cccc488bc448895808488970104889781855488da8e8feffff4881ec100200000f2978e8440f2940d844'
          '0f2948c8488b052d9414004833c4488985d0000000488bd9488b0561992d00480510aa2600b901000000ffd0488bf88b8bb80e00'
          '004885c00f849c05000083f9ff0f8493050000e8ec56ffff483bc70f8585050000488b9fd82100004885db0f8475050000448b03'
          '488d542450488d0d54971400e87fd3feff807dd4000f8457050000807d48000f844d0500008b4b04394c2454400f94c7742a488d'
          '154f1c1000488d0df04e2d00e8db1afcff488bc8b20ae8b11cfcff488d0dda4e2d00ff15bc760e00bb020000004084ff75328bcb'
          'ff154a7b'),
         bytes.fromhex(
          '535657554881eca80100000f11b424980100000f11bc2488010000440f11842478010000440f118c2468010000440f1194245801'
          '0000440f119c24480100004889ce4889d74c89c5410f10010f11442440410f1041100f11442450410f1041200f11442460410f10'
          '41300f114424700fb605ca6a280084c00f8574030000488b057bb22d004885c07522488d4c2420488d15c7030000e82516fcff48'
          '8d4c2420e8ab9bffff48890554b22d00f30f1040580f57c90f2ec10f8635030000f30f5d058c030000f30f11842480000000488b'
          '053bb22d004885c07522488d4c2420488d1587030000e8d515fcff488d4c2420e85b9bffff48890514b22d00f30f1040580f57c9'
          '0f2ec10f86e5020000f30f59842480000000f30f11842480000000488b05fa9b2d00480540ef1400b9ffffffffffd04885c00f84'
          'b60200004889c1488b05da9b2d00480540842c00ffd00f57c90f2fc10f8698020000f30f5d05ef020000f30f59842480000000f3'
          '0f11842480000000e847060000f30f10642450f30f106c2454f30f10742458f30f107c245c0f28c4f30f59c60f28cff30f59cdf3'
          '0f58c1f30f5905aa020000f30f118424840000000f28c5f30f59c60f28cff30f59ccf30f5cc1f30f590587020000f30f11842488'
          '0000000f28c4f30f59c40f28cdf30f59cdf30f58c1f30f58c0f30f5c055c020000f30f1184248c000000f30f10842484000000f3'
          '0f59c0f30f108c248c000000f30f59c9f30f58c1f30f51c00f2f05320200000f86c5010000f30f108c2484000000f30f5ec8f30f'
          '1094248c000000f30f5ed0f30f109c2488000000f30f59d3f30f59cb0f57dbf30f5cd90f28cbf30f5805e70100000f28daf30f59'
          'daf30f119c24900000000f28d9f30f59d9f30f589c2490000000f30f119c24900000000f28d8f30f59d8f30f589c2490000000f3'
          '0f51dbf30f5ed3f30f5ecbf30f5ec3f30f109c2480000000f30f59d3f30f59cbf30f59c3f30f580581010000f30f5cc30f28daf3'
          '0f59daf30f119c24900000000f28d9f30f59d9f30f589c2490000000f30f119c24900000000f28d8f30f59d8f30f589c24900000'
          '00f30f51dbf30f5ed3f30f5ecbf30f5ec30f28d8f30f59dcf30f119c24900000000f28daf30f59dff30f589c2490000000f30f11'
          '9c24900000000f28d9f30f59ddf3440f10842490000000f3440f5cc30f28d8f30f59ddf30f119c24900000000f28daf30f59def3'
          '440f108c2490000000f3440f5ccb0f28d9f30f59dcf3440f58cb0f28d8f30f59def3440f10d30f28daf30f59ddf3440f58d30f28'
          'd9f30f59dff3440f58d30f28d8f30f59dff3440f10db0f28daf30f59dcf3440f5cdb0f28d9f30f59def3440f5cdbf3440f114424'
          '50f3440f114c2454f3440f11542458f3440f115c245c0f10b424980100000f10bc2488010000440f10842478010000440f108c24'
          '68010000440f10942458010000440f109c24480100004889f14889fa4989e84c8d4c2440e897e803004881c4a80100005d5f5e5b'
          'c3cccccccccccccccccccccccc0000803f000000c06f12833a74663276725f626172665f6d6f64650074663276725f6164735f68'
          '6f6c6400')),
        # position hold (called by the view hold): the eyes' centre eases to the recenter anchor's position, keeping
        # each eye's offset, so looking up or down (the head pivots on the neck), slouching or leaning doesn't move
        # the sights
        ('ADS position hold: subroutine in dead code', 0x44160,
         bytes.fromhex(
          'fcffff1570700e000fb60dd192280084c90f84a20100008bd0488d0da0532d00ff152a730e000fb60db392280084c90f84840100'
          '00b22c488d0d82532d00e80d19fcff0fb60d9692280084c90f8467010000f30f104d4c488d0d62532d00ff155c730e000fb60d75'
          '92280084c90f8446010000b22c488d0d44532d00e8cf18fcff0fb60d5892280084c90f8429010000f30f104d50488d0d24532d00'
          'ff151e730e000fb60d3792280084c90f8408010000b22c488d0d06532d00'),
         bytes.fromhex(
          '488b05f91328004885c00f84a2000000f30f1088a8080000f30f5888e8080000f30f590d8e000000f30f105510f30f5cd1f30f59'
          '942488000000f30f58542468f30f11542468f30f1088ac080000f30f5888ec080000f30f590d58000000f30f105514f30f5cd1f3'
          '0f59942488000000f30f5854246cf30f1154246cf30f1088b0080000f30f5888f0080000f30f590d22000000f30f105518f30f5c'
          'd1f30f59942488000000f30f58542470f30f11542470c3cccccc0000003f')),
        ('ADS pitch hold: main eye views go through it', 0x87589,
         bytes.fromhex('e8e2b0ffff'), bytes.fromhex('e812c4fbff')),
        # Menu pointer dot: the plugin's menu pointer (0x981b0, state 0x318420) is a motion-controller laser, and the
        # Windows cursor isn't in the captured menu, so menus showed no pointer. The helper runs the pointer update
        # and, with no laser and an interactive menu, reads the mouse (GetCursorPos + ScreenToClient, resolved once
        # into 0x31ecc8/d0) and puts the plugin's pointer on the panel there (u/v, hit flags, a tiny beam on the
        # panel via the panel matrix 0x97d50). It also stores the pixel the caller derives from u/v as the last
        # posted one (0x318098), so the caller never moves the real cursor. Assembled by kbm_patch/re/cave_menudot.py.
        ('menu dot: pointer helper in dead code', 0x43e20,
         bytes.fromhex(
          'c84c8d05101c1000488d1511b90e00e8acd9fbff488d0dfd1b1000ff157f730e00b907000000cd2948833d68462d0000755c488d'
          '151f1c1000488d0d804e2d00e86b1afcff488bc8b20ae8411cfcff488d0d6a4e2d00ff154c760e008bcbff15e47a0e00488bc84c'
          '8d05ea1b1000488d15abb80e00e846d9fbff488d0dd71b1000ff1519730e00b907000000cd29488d35b3941400488bceff15fa74'
          '0e0085c00f8593040000813de4941400ffffff7f0f84cd010000488d0ddb941400488d4424500f10000f11010f1048100f114910'
          '0f1040200f1141200f1048300f1149300f1040400f1141400f1048500f1149500f1040600f114160488d89800000000f1048700f'
          '1149f0488d80800000004883eb0175ae0f10000f11010f1048100f1149100f1040200f114120488b403048894130488bceff156d'
          '740e00f3440f104d5c410f28c9f3440f104558410f28c0e8bae80c000f28c8f30f1045600f57058d9b1200e8b2e80c000f28f8f3'
          '0f593d31921200410f28c8410f28c1e89ae80c00f30f59051c921200f20f104d4cf20f118d900000008b7d5489bd98000000410f'
          '28c8410f14c9f20f118d9c0000008b45608985a4000000f30f11bda8000000f30f1185ac000000899db0000000f20f104c247cf2'
          '0f118db40000008b45848985bc000000f20f104588f20f1185c00000008b45908985c8000000488d85900000004889442430488d'
          '85cc00000048894424388b5c2450895c2420488d4424204889442440488d44242448894424480f28442430660f7f4424300f284c'
          '2440660f7f4c24404c8d4c24304c8d442440488d152b1a1000488d0d3c442d00e8ff1a00004889742420488bceff1529730e0085'
          'c00f85c2020000813d13931400ffffff7f7516c70507931400feffff7fb906000000ff15b0720e00900fb6058093280084c00f84'
          '9a000000488d15f50c1000488d0d4a542d00e8f517fcff0fb6055e93280084c0747cb22c488d0d31542d00e8bc19fcff0fb60545'
          '93280084c074638bd3488d0d18542d00ff15fa730e000fb6052b93280084c07449b22c488d0dfe532d00e88919fcff0fb6051293'
          '280084c07430488b542458488d0de2532d00ff1574730e000fb605f592280084c07413488d153e19100048'),
         bytes.fromhex(
          '5356575541544881eca00000004889cb4889d64489c74c89cd8b8424f000000089442420e8674305004189c4807b30000f85ae02'
          '00004084ff0f84a5020000488b0562ae2d004885c07551488d0db3020000ff1598730e004885c00f848302000048898424900000'
          '004889c1488d15b5020000ff156f730e0048890530ae2d00488b8c2490000000488d158c020000ff1553730e004889050cae2d00'
          '488b0505ae2d004885c00f8438020000488b05fdad2d004885c00f8428020000488d8c2498000000ff15dead2d0085c00f841202'
          '0000ff15d0770e004885c00f84030200004889c1488d942498000000ff15bead2d0085c00f84ea0100008b842498000000f30f2a'
          'c0f30f5805ec0100008b842418010000ffc80f8ec8010000f30f2ac8f30f5ec10f57c9f30f5fc1f30f5d05ca010000f30f118424'
          '800000008b84249c000000f30f2ac0f30f5805aa0100008b84241c010000ffc80f8e86010000f30f2ac8f30f5ec10f57c9f30f5f'
          'c1f30f5d0588010000f30f118424840000008b842418010000ffc8f3480f2ac0f30f59842480000000f30f2cd08b84241c010000'
          'ffc8f3480f2ac0f30f59842484000000f30f2cc88915be402d00890dbc402d00488d4c24404889eaf30f109424f0000000e85a3d'
          '0500f30f10842480000000f30f5c0512010000f30f11842488000000f30f100501010000f30f5c842484000000f30f1184248c00'
          '0000f30f108c24880000000fc6c9000f105c24400f59d9f30f108c248c0000000fc6c9000f106424500f59e10f58dc0f10642470'
          '0f58dc0f28e30fc6e4ff0f5edcf20f115b400f28e30fc6e4aaf30f116348f30f108c2488000000f30f5c0d960000000fc6c9000f'
          '105c24400f59d9f30f108c248c0000000fc6c9000f106424500f59e10f58dc0f106424700f58dc0f28e30fc6e4ff0f5edcf20f11'
          '5b340f28e30fc6e4aaf30f11633cf30f10842480000000f30f114328f30f11434cf30f10842484000000f30f11432cf30f114350'
          'c6433001c6433101c64332004489e04881c4a0000000415c5d5f5e5bc3cccccccc0000003f0000803f6f12033b75007300650072'
          '00330032002e0064006c006c000000476574437572736f72506f730053637265656e546f436c69656e7400')),
        ('menu dot: menu pointer update goes through the helper', 0x9a61e,
         bytes.fromhex('e88ddbffff'), bytes.fromhex('e8fd97faff')),
        ('barf mode: body matrix call goes through the pitch helper', 0x91391,
         bytes.fromhex('e85af8f9ff'), bytes.fromhex('e8fa23fbff')),
        ('skip calibration: startup state machine checks tf2vr_skip_cal', 0x8281a,
         bytes.fromhex('4584c97412'), bytes.fromhex('e9ff10fcff')),
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
        # server.vortexAngles hook (0x351a0) calls the game's function first (0x35259), then resolves the vortex
        # sphere's owner handles (fail-fast "native entity handle index changed" on a stale one) and overwrites the
        # angles with the VR command pose (fail-fast "Vortex command pose unavailable" without one). Return the game's
        # result right after its call (jmp to the epilogue 0x356fa), so the vortex shield aims like the flat game.
        ('vanilla vortex shield: keep the game\'s aim, skip the VR override', 0x3525e,
         bytes.fromhex('8b9ef8030000'), bytes.fromhex('e997040000') + b'\x90'),
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


def export(dll, out):
    """Writes the patch set for the launcher (src/Installer reads it as an embedded resource).

    dll must be the untouched Titanfall2VR.dll; every site is verified against it and its sha256 recorded,
    so the launcher only ever patches that exact build. The window-size site is filled in at launch.
    """
    import hashlib, json
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import install
    data = dll.read_bytes()
    patches, window = [], None
    for desc, rva, expected, replacement in PATCHES:
        off = rva_to_offset(data, rva)
        if data[off:off + len(expected)] != expected:
            sys.exit(f'ABORT: {dll} is not the untouched build ("{desc}" at rva {rva:#x} differs)')
        entry = {'name': desc, 'rva': rva, 'expected': expected.hex(), 'replacement': replacement.hex()}
        if rva == WINDOW_RVA:
            window = {'rva': rva, 'expected': expected.hex()}
        else:
            patches.append(entry)
    mod = json.loads((install.REPO / 'mods' / 'TF2VR.Minimal' / 'mod.json').read_text())
    out.write_text(json.dumps({
        'dllSha256': hashlib.sha256(data).hexdigest(),
        'modName': mod['Name'],
        'modVersion': mod['Version'],
        'cockpitUiFiles': install.COCKPIT_UI_FILES,
        'menuEdits': [{'file': f, 'pattern': p, 'replacement': r} for f, p, r in install.MENU_EDITS],
        'window': window,
        'patches': patches,
    }, indent=1) + '\n', encoding='utf-8')
    print(f'exported {len(patches)} patches + window size to {out}')


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    dll = Path(args[0]) if args else Path(__file__).resolve().parent.parent / 'plugins' / 'Titanfall2VR.dll'
    orig = dll.with_name(dll.name + '.orig')

    for arg in sys.argv:
        if arg.startswith('--export='):
            return export(dll, Path(arg.split('=', 1)[1]))

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
