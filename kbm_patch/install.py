"""Set up CLTFVRMod-Mod inside a Titanfall 2 VR (TF2VR) profile folder, or undo it.

Usage:  python kbm_patch\\install.py [--undo] [patcher options]

  1. copies the VR settings menu from the installed Titanfall2VR.Cockpit mod into TF2VR.Minimal
     (those files belong to Titanfall 2 VR and are not redistributed here)
  2. disables Titanfall2VR.Cockpit and enables TF2VR.Minimal in enabledmods.json
  3. launches the game borderless at the monitor's size (tools/launch.json)
  4. patches plugins/Titanfall2VR.dll (see patch_tf2vr_kbm.py; extra options are passed through)
"""
import json, shutil, subprocess, sys
from pathlib import Path

PROFILE = Path(__file__).resolve().parent.parent
COCKPIT = PROFILE / 'mods' / 'Titanfall2VR.Cockpit' / 'mod'
MINIMAL = PROFILE / 'mods' / 'TF2VR.Minimal' / 'mod'
PATCHER = Path(__file__).resolve().parent / 'patch_tf2vr_kbm.py'

COCKPIT_UI_FILES = [
    'scripts/vscripts/tf2vr_menu.nut',
    'scripts/vscripts/tf2vr_settings.nut',
    'resource/ui/menus/ingame_sp.menu',
    'resource/ui/menus/tf2vr_settings.menu',
    'resource/tf2vr_english.txt',
]


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


def install():
    missing = [f for f in COCKPIT_UI_FILES if not (COCKPIT / f).exists()]
    if missing:
        sys.exit(f'ABORT: Titanfall 2 VR is missing files this mod needs: {missing}')
    for f in COCKPIT_UI_FILES:
        (MINIMAL / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(COCKPIT / f, MINIMAL / f)
    print(f'copied {len(COCKPIT_UI_FILES)} settings menu files from Titanfall2VR.Cockpit')

    set_enabled_mods(minimal=True)
    print('enabled TF2VR.Minimal, disabled Titanfall2VR.Cockpit')

    sys.path.insert(0, str(PATCHER.parent))
    from patch_tf2vr_kbm import screen_size
    width, height = screen_size()
    set_launch_args(width, height)
    print(f'launch: borderless {width}x{height}')

    subprocess.run([sys.executable, str(PATCHER), *sys.argv[1:]], check=True)


def uninstall():
    set_enabled_mods(minimal=False)
    print('enabled Titanfall2VR.Cockpit, disabled TF2VR.Minimal')
    backup = PROFILE / 'tools' / 'launch.json.orig'
    if backup.exists():
        shutil.copy2(backup, PROFILE / 'tools' / 'launch.json')
        print('launch: restored original arguments')
    subprocess.run([sys.executable, str(PATCHER), '--restore'], check=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(line_buffering=True)  # keep our lines in order with the patcher's output
    uninstall() if '--undo' in sys.argv else install()
