# Titanfall 2 VR Keyboard and Mouse (based on CircuitLord's Titanfall 2 VR)

Keyboard and mouse play for [Titanfall 2 VR](https://github.com/CircuitLord/CircuitLordVRModInstaller) by CircuitLord.

Titanfall 2 VR plays the campaign with motion controllers. This mod of the mod keeps its headset rendering and turns everything else back into the normal game: WASD and your own key binds, the mouse turns and aims while the headset looks around freely, the stock gun with its animations, the game's crosshair placed in the world where you aim, sights lined up with your dominant eye, and the HUD.

This repository is a fork of [CircuitLord's VR Mod Installer](https://github.com/CircuitLord/CircuitLordVRModInstaller), cut down to Titanfall 2 and extended with a **Keyboard and mouse** switch. It is not made or endorsed by CircuitLord, Respawn or EA.

## Using it

1. Run the launcher, let it find Titanfall 2 and install Titanfall 2 VR, as with CircuitLord's installer.
2. Leave **Keyboard and mouse** on and press **Launch in VR**. Turn it off to play Titanfall 2 VR with motion controllers again; the launcher swaps between the two on every launch.
3. Options under the switch:
   - **Mouse tilts the view (barf mode)**: mouse up and down also tilts the headset view, like a flat screen.
   - **Hold the view level while aiming** (with barf mode): aiming down sights holds your head's up and down tilt and position where you last recentered, so the sights line up with where you shoot.
   - **Skip calibration**: no arm-span and height setup at startup. Press your recenter key once seated.
   - **Keys**: recenter the view (F9), switch the sight eye (F7) and turn barf mode on or off (F8). Click a key to change it. The launcher writes these binds into the game's settings at each launch and warns when a key already does something else.
4. In the pause menu's VR settings, **Sight Eye** and **Sight Height** line the sights up with your dominant eye when aiming down sights.
5. In menus, a dot on the menu panel shows where the mouse points.

The keyboard and mouse patch fits one Titanfall 2 VR build (v1.0.17, plugin sha256 `6b550331…`). After a Titanfall 2 VR update the launcher says the version isn't supported yet until this repository catches up; turn the switch off to keep playing with controllers.

## How it works

Titanfall 2 VR is closed source and nothing of it is in this repository. At launch the launcher:

- byte-patches `Titanfall2VR.dll` from an untouched copy (`Titanfall2VR.dll.orig`), after checking its sha256 and every patch site;
- swaps the `Titanfall2VR.Cockpit` script mod for `TF2VR.Minimal`, our small replacement, copying the VR settings menu in from your own Titanfall 2 VR install;
- starts the game borderless at your monitor's resolution.

The patch set lives in [`kbm/`](kbm/), with the Python tools used to find and test it; see [kbm/README.md](kbm/README.md).

## Building

`dotnet build CircuitLordVRModInstaller.sln -c Release` (Windows, .NET Framework 4.8 targeting) builds `CLTFV_KBM.exe`; `dotnet run --project tests/InstallerValidation -c Release` runs the checks. After changing a patch, re-export the patch set with `python kbm/kbm_patch/patch_tf2vr_kbm.py <untouched Titanfall2VR.dll> --export=kbm/kbm.json`.

## Credits and licence

The launcher is CircuitLord's VR Mod Installer, MIT licensed, © Jordan (CircuitLord); see `LICENSE`. Titanfall 2 VR is © CircuitLord. The keyboard and mouse changes are MIT licensed; see `kbm/LICENSE`. Use at your own risk.
