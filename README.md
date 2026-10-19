# CLTFVRMod-Mod

Keyboard and mouse play for Titanfall 2 VR by CircuitLord.

Titanfall 2 VR plays the campaign with motion controllers: guns in your hands, magazine reloads, physical grabbing. This mod of the mod keeps its headset rendering and turns everything else back into the normal game:

- keyboard movement and your own key binds
- the mouse turns you and aims, while the headset looks around freely on top of that
- the game's crosshair, placed in the world where you aim rather than stuck to your view
- aiming down sights lines the sights up with your dominant eye (Sight Eye and Sight Height in the VR settings menu)
- the stock first-person gun, its animations, firing and reloading
- a borderless full-screen desktop window that keeps the mouse inside
- the VR settings menu in the pause menu

Titanfall 2 VR is closed source and not included here. This repository holds only the changes made around it.

## Requirements

- Titanfall 2 with Titanfall 2 VR installed. The patch offsets fit the Titanfall2VR.dll build of Oct 9 2026 (sha256 `6b550331c178…`).
- Python 3 on Windows.

## Install

1. Download or clone this repository anywhere. Find the `TF2VR` profile folder of your Titanfall 2 install. That folder holds `plugins/Titanfall2VR.dll`.
2. With the game closed, run `python kbm_patch\install.py --profile=<path to TF2VR>`. You can set the `TF2VR_PROFILE` environment variable instead of passing `--profile`. It:
   - copies `TF2VR.Minimal` into the profile's `mods` folder;
   - copies the VR settings menu files from your installed `Titanfall2VR.Cockpit` mod into `TF2VR.Minimal`, turning the VR gun's angle and grip rows into Sight Eye and Sight Height;
   - disables `Titanfall2VR.Cockpit` and enables `TF2VR.Minimal` in `enabledmods.json`;
   - sets `tools/launch.json` to start the game borderless at your monitor's resolution;
   - patches `plugins/Titanfall2VR.dll`. The original is kept as `Titanfall2VR.dll.orig`.
3. Start the game with the Titanfall 2 VR launcher as usual.

Before patching, the patcher checks every site against the bytes it expects. If Titanfall 2 VR was updated, it stops without changing anything.

To undo everything, run `python kbm_patch\install.py --undo`. This leaves `TF2VR.Minimal` in place, disabled.

For development, add `--link`. The profile then gets a junction to this repository's `TF2VR.Minimal` instead of a copy, so script edits show up in the game without reinstalling.

Optional patcher settings, passed through by the installer:

- `--vr-rig` keeps Titanfall 2 VR's hands and guns instead of the stock first-person gun.
- `--size=WxH` sets the window size, if the primary monitor isn't the one you play on.

Your key binds live in `%LOCALAPPDATA%\Respawn\Titanfall2_VR`, separate from the normal game's `Documents\Respawn\Titanfall2`. To use your usual binds, copy the `bind` lines from the normal `local\settings.cfg` into the VR one.

## How it works

`TF2VR.Minimal` replaces the Cockpit script mod. It gives Titanfall2VR.dll the settings variables, menu signal and script callbacks it expects, and nothing else.

`kbm_patch/patch_tf2vr_kbm.py` byte-patches Titanfall2VR.dll. It:

- stops the plugin dropping mouse messages, replacing the cursor, and overwriting movement, buttons and view angles;
- turns the VR body with the mouse's yaw;
- skips the hand/gun rig, shot-direction and manual-reload hooks;
- shows the game's crosshair on foot, drawn with the plugin's Titan reticle at the point a trace along your aim hits;
- shows the gun's own displays, such as red-dot and holo reticles, and draws them with the same eye shift;
- moves the gun toward your dominant eye while aiming down sights (`tf2vr_ads_eye`, `tf2vr_ads_drop`);
- sizes the desktop window.

Every patch site is commented in the script.

`kbm_patch/re/` holds the pefile + capstone helpers used to find those sites. You need them again whenever Titanfall 2 VR is updated.

## Known issues and plans

- Moving the mouse up and down aims but doesn't tilt the headset view.
- There's no mouse cursor in the headset in menus. Use the keyboard or the desktop window.
- The HUD (health, ammo and so on) isn't visible; damage flashes show as a floating rectangle.
- The arm-span calibration still runs at every start. Do it in the pose you play in, for example seated.
- Jump occasionally misses a press.
- The grenade throw arc isn't shown.

## Licence

The code in this repository is MIT licensed; see `LICENSE`. That covers only this repository, not Titanfall 2 VR, Northstar or the game.

## Disclaimer

Not affiliated with CircuitLord, Respawn or EA. Titanfall 2 VR is © CircuitLord. Use this at your own risk.
