"""Set up CLTFVRMod-Mod inside a Titanfall 2 VR (TF2VR) profile folder, or undo it.

Usage:  python kbm_patch\\install.py [--profile=PATH] [--link] [--undo] [patcher options]

  --profile=PATH  the TF2VR profile folder (holds plugins/Titanfall2VR.dll). Defaults to the
                  TF2VR_PROFILE environment variable, then to this repository's parent folder.
  --link          put a junction to this repository's TF2VR.Minimal in the profile instead of a copy,
                  so script edits in the repository show up in the game (for development)

  1. copies (or links) TF2VR.Minimal into the profile's mods folder
  2. copies the VR settings menu from the installed Titanfall2VR.Cockpit mod into TF2VR.Minimal
     (those files belong to Titanfall 2 VR and are not redistributed here)
  3. disables Titanfall2VR.Cockpit and enables TF2VR.Minimal in enabledmods.json
  4. launches the game borderless at the monitor's size (tools/launch.json)
  5. patches plugins/Titanfall2VR.dll (see patch_tf2vr_kbm.py; extra options are passed through)
"""
import json, os, re, shutil, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PATCHER = REPO / 'kbm_patch' / 'patch_tf2vr_kbm.py'


def find_profile():
    for arg in sys.argv:
        if arg.startswith('--profile='):
            path = Path(arg.split('=', 1)[1])
            break
    else:
        path = Path(os.environ['TF2VR_PROFILE']) if 'TF2VR_PROFILE' in os.environ else REPO
    if not (path / 'plugins' / 'Titanfall2VR.dll').exists():
        sys.exit(f'ABORT: {path} is not a TF2VR profile folder (no plugins/Titanfall2VR.dll); pass --profile=PATH')
    return path.resolve()


PROFILE = find_profile()
COCKPIT = PROFILE / 'mods' / 'Titanfall2VR.Cockpit' / 'mod'
MINIMAL = PROFILE / 'mods' / 'TF2VR.Minimal' / 'mod'
DLL = PROFILE / 'plugins' / 'Titanfall2VR.dll'

COCKPIT_UI_FILES = [
    'scripts/vscripts/tf2vr_menu.nut',
    'scripts/vscripts/tf2vr_settings.nut',
    'resource/ui/menus/ingame_sp.menu',
    'resource/ui/menus/tf2vr_settings.menu',
    'resource/tf2vr_english.txt',
]


# Without the VR gun, its two settings rows (angle offset, grip toggle) do nothing; reuse them for the sight eye
# and sight height of dominant-eye ADS (convars defined in TF2VR.Minimal's mod.json). (file, pattern, new text)
ADS_EYE_LIST = '''ConVar "tf2vr_ads_eye"
\t\t\tlist
\t\t\t{
\t\t\t\t"#CLTFVR_EYE_LEFT" -1
\t\t\t\t"#CLTFVR_EYE_CENTER" 0
\t\t\t\t"#CLTFVR_EYE_RIGHT" 1
\t\t\t}'''
ADS_DROP_LIST = 'ConVar "tf2vr_ads_drop"\n\t\t\tlist\n\t\t\t{\n' + ''.join(
    f'\t\t\t\t"{cm:+d} cm" {cm / 100:g}\n'.replace('+0 cm', '0 cm') for cm in range(-3, 9)) + '\t\t\t}'
ADS_TOKENS = '''        "CLTFVR_ADS_EYE" "Sight Eye"
        "CLTFVR_ADS_EYE_DESC" "The eye the sights line up with when aiming down sights. Pick your dominant eye."
        "CLTFVR_ADS_DROP" "Sight Height"
        "CLTFVR_ADS_DROP_DESC" "Lowers the gun while aiming down sights so the sights meet your eye. Negative values raise it."
        "CLTFVR_EYE_LEFT" "Left"
        "CLTFVR_EYE_CENTER" "Between the eyes"
        "CLTFVR_EYE_RIGHT" "Right"
'''
MENU_EDITS = [
    ('resource/ui/menus/tf2vr_settings.menu', r'ConVar "tf2vr_gun_angle_offset"\s*list\s*\{[^}]*\}', ADS_EYE_LIST),
    ('resource/ui/menus/tf2vr_settings.menu', r'ConVar "tf2vr_toggle_grip"\s*list\s*\{[^}]*\}', ADS_DROP_LIST),
    ('scripts/vscripts/tf2vr_settings.nut', r'"SwchGunAngleOffset", "#TF2VR_GUN_ANGLE_OFFSET"',
     '"SwchGunAngleOffset", "#CLTFVR_ADS_EYE"'),
    ('scripts/vscripts/tf2vr_settings.nut', r'"SwchToggleGrip", "#TF2VR_GUN_GRIP"', '"SwchToggleGrip", "#CLTFVR_ADS_DROP"'),
    ('resource/tf2vr_english.txt', r'(?=\n    \}\s*\}\s*$)', '\n' + ADS_TOKENS.rstrip('\n')),
]


def edit_menu():
    for f, pattern, new in MENU_EDITS:
        path = MINIMAL / f
        raw = path.read_bytes()
        encoding = 'utf-16' if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else 'utf-8'
        text = raw.decode(encoding)
        crlf = '\r\n' in text
        text = text.replace('\r\n', '\n')
        matches = len(re.findall(pattern, text))
        if matches != 1:
            sys.exit(f'ABORT: {f} changed in this Titanfall 2 VR version ({matches} matches for {pattern!r})')
        text = re.sub(pattern, lambda _: new, text)
        path.write_bytes((text.replace('\n', '\r\n') if crlf else text).encode(encoding))


def set_enabled_mods(minimal):
    path = PROFILE / 'enabledmods.json'
    mods = json.loads(path.read_text())
    mods.setdefault('Titanfall2VR.Cockpit', {'1.0.0': True})
    for version in mods['Titanfall2VR.Cockpit']:
        mods['Titanfall2VR.Cockpit'][version] = not minimal
    version = json.loads((MINIMAL.parent / 'mod.json').read_text())['Version']
    mods['TF2VR.Minimal'] = {version: minimal}
    path.write_text(json.dumps(mods, indent=4))


def set_launch_args(width, height):
    path = PROFILE / 'tools' / 'launch.json'
    backup = path.with_name(path.name + '.orig')
    if not backup.exists():
        shutil.copy2(path, backup)
    launch = json.loads(backup.read_text())
    args = launch['arguments']
    i = args.index('-windowed')
    if args[i + 1:i + 5] != ['-w', '{width}', '-h', '{height}']:
        sys.exit(f'ABORT: unexpected launch arguments in {backup}: {args}')
    args[i:i + 5] = ['-windowed', '-noborder', '-w', str(width), '-h', str(height)]
    path.write_text(json.dumps(launch, indent=2))


def deploy_minimal():
    src, dst = REPO / 'mods' / 'TF2VR.Minimal', MINIMAL.parent
    if dst.resolve() == src.resolve():
        return  # the repository is the profile folder, or the junction is already in place
    try:
        os.readlink(dst)  # an old link pointing elsewhere: replace it
        os.rmdir(dst)
    except OSError:
        pass
    if '--link' in sys.argv:
        if dst.exists():
            sys.exit(f'ABORT: {dst} is a folder; delete it to replace it with a link to {src}')
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(dst), str(src)], check=True, capture_output=True)
        print(f'linked {dst} -> {src}')
    else:
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
        print(f'copied TF2VR.Minimal into {dst.parent}')


def install():
    missing = [f for f in COCKPIT_UI_FILES if not (COCKPIT / f).exists()]
    if missing:
        sys.exit(f'ABORT: Titanfall 2 VR is missing files this mod needs: {missing}')
    deploy_minimal()
    for f in COCKPIT_UI_FILES:
        (MINIMAL / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(COCKPIT / f, MINIMAL / f)
    print(f'copied {len(COCKPIT_UI_FILES)} settings menu files from Titanfall2VR.Cockpit')
    if '--vr-rig' not in sys.argv:
        edit_menu()
        print('settings menu: gun angle and grip rows now set the sight eye and sight height')

    set_enabled_mods(minimal=True)
    print('enabled TF2VR.Minimal, disabled Titanfall2VR.Cockpit')

    sys.path.insert(0, str(PATCHER.parent))
    from patch_tf2vr_kbm import screen_size
    width, height = screen_size()
    set_launch_args(width, height)
    print(f'launch: borderless {width}x{height}')

    subprocess.run([sys.executable, str(PATCHER), str(DLL), *sys.argv[1:]], check=True)


def uninstall():
    set_enabled_mods(minimal=False)
    print('enabled Titanfall2VR.Cockpit, disabled TF2VR.Minimal')
    backup = PROFILE / 'tools' / 'launch.json.orig'
    if backup.exists():
        shutil.copy2(backup, PROFILE / 'tools' / 'launch.json')
        print('launch: restored original arguments')
    subprocess.run([sys.executable, str(PATCHER), str(DLL), '--restore'], check=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(line_buffering=True)  # keep our lines in order with the patcher's output
    uninstall() if '--undo' in sys.argv else install()
