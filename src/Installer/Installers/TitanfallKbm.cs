using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using BigWalkVRInstaller.Services;

namespace BigWalkVRInstaller.Installers
{
    // kbm/kbm.json, written by kbm/kbm_patch/patch_tf2vr_kbm.py --export
    public sealed class KbmPatchSet
    {
        public string dllSha256;
        public string modName;
        public string modVersion;
        public string[] cockpitUiFiles;
        public KbmMenuEdit[] menuEdits;
        public KbmPatch window;
        public KbmPatch[] patches;
    }

    public sealed class KbmPatch
    {
        public string name;
        public int rva;
        public string expected;
        public string replacement;
    }

    public sealed class KbmMenuEdit
    {
        public string file;
        public string pattern;
        public string replacement;
    }

    public enum KbmSupport { Supported, NotInstalled, UnsupportedBuild }

    // Keyboard/mouse play (CLTFVRMod-Mod): per launch, either patches Titanfall2VR.dll and swaps the Cockpit script
    // mod for TF2VR.Minimal, or puts the untouched plugin and Cockpit back. The patch set only fits one plugin build,
    // identified by its sha256; the untouched copy is kept beside it as Titanfall2VR.dll.orig.
    public static class TitanfallKbm
    {
        const string Resources = "kbm/";
        const string CockpitMod = "Titanfall2VR.Cockpit";

        static KbmPatchSet _patchSet;
        public static KbmPatchSet PatchSet => _patchSet ?? (_patchSet = JsonUtil.Deserialize<KbmPatchSet>(ReadResource("kbm.json")));

        static string Profile(string gamePath) => Path.Combine(gamePath, Titanfall2Installer.ProfileName);
        static string Dll(string gamePath) => Path.Combine(Profile(gamePath), "plugins", "Titanfall2VR.dll");
        static string Orig(string gamePath) => Dll(gamePath) + ".orig";

        public static KbmSupport Check(string gamePath) => FindUntouched(gamePath, out _) ?? KbmSupport.Supported;

        // null when an untouched build is found (returned in untouched), otherwise why not
        static KbmSupport? FindUntouched(string gamePath, out byte[] untouched)
        {
            untouched = null;
            var dll = Dll(gamePath);
            if (!File.Exists(dll)) return KbmSupport.NotInstalled;
            var current = File.ReadAllBytes(dll);
            if (Sha256(current) == PatchSet.dllSha256)
            {
                untouched = current;
                return null;
            }
            // our patched copy of the supported build; anything else is a Titanfall 2 VR update the patch doesn't know yet
            var orig = Orig(gamePath);
            if (File.Exists(orig))
            {
                var saved = File.ReadAllBytes(orig);
                if (Sha256(saved) == PatchSet.dllSha256 && IsPatchedFrom(saved, current))
                {
                    untouched = saved;
                    return null;
                }
            }
            return KbmSupport.UnsupportedBuild;
        }

        public static void Enable(string gamePath, int width, int height)
        {
            if (FindUntouched(gamePath, out var untouched) is KbmSupport problem)
                throw new Exception(problem == KbmSupport.NotInstalled
                    ? "Titanfall 2 VR isn't installed."
                    : "the keyboard and mouse patch doesn't support this Titanfall 2 VR version yet. Turn off keyboard and mouse to play.");
            var cockpit = Path.Combine(Profile(gamePath), "mods", CockpitMod, "mod");
            var missing = PatchSet.cockpitUiFiles.Where(f => !File.Exists(Path.Combine(cockpit, f))).ToArray();
            if (missing.Length > 0) throw new Exception("Titanfall 2 VR is missing files keyboard and mouse needs: " + string.Join(", ", missing));

            var orig = Orig(gamePath);
            if (!File.Exists(orig) || Sha256(File.ReadAllBytes(orig)) != PatchSet.dllSha256) File.WriteAllBytes(orig, untouched);
            WriteIfChanged(Dll(gamePath), Patch(untouched, width, height));

            var minimal = Path.Combine(Profile(gamePath), "mods", PatchSet.modName);
            DeployMod(minimal);
            foreach (var f in PatchSet.cockpitUiFiles)
            {
                var destination = Path.Combine(minimal, "mod", f);
                Directory.CreateDirectory(Path.GetDirectoryName(destination));
                File.Copy(Path.Combine(cockpit, f), destination, true);
            }
            foreach (var edit in PatchSet.menuEdits) EditMenuFile(Path.Combine(minimal, "mod", edit.file), edit);
            SetEnabledMods(gamePath, true);
        }

        public static void Disable(string gamePath)
        {
            var dll = Dll(gamePath);
            var orig = Orig(gamePath);
            if (File.Exists(dll) && File.Exists(orig))
            {
                var saved = File.ReadAllBytes(orig);
                if (Sha256(saved) == PatchSet.dllSha256 && IsPatchedFrom(saved, File.ReadAllBytes(dll))) File.WriteAllBytes(dll, saved);
            }
            if (File.Exists(Path.Combine(Profile(gamePath), "enabledmods.json"))) SetEnabledMods(gamePath, false);
        }

        // launch.json ships "-windowed -w {width} -h {height}"; the patched plugin keeps the window borderless at 0,0
        // the options are ARCHIVE_PLAYERPROFILE convars of TF2VR.Minimal, set on every launch so the launcher's choice wins
        // binds are extra arguments from ApplyBinds
        public static IEnumerable<string> LaunchArguments(IEnumerable<string> arguments, int width, int height, bool barfMode, bool skipCalibration,
            IEnumerable<string> binds = null, bool adsHold = true)
        {
            foreach (var arg in arguments)
            {
                yield return arg.Replace("{width}", width.ToString()).Replace("{height}", height.ToString());
                if (arg == "-windowed") yield return "-noborder";
            }
            foreach (var arg in new[] { "+tf2vr_barf_mode", barfMode ? "1" : "0", "+tf2vr_skip_cal", skipCalibration ? "1" : "0",
                "+tf2vr_ads_hold", adsHold ? "1" : "0" })
                yield return arg;
            foreach (var arg in binds ?? Enumerable.Empty<string>())
                yield return arg;
        }

        // TF2VR.Minimal's console commands the launcher binds, with their default keys (Source key names)
        public static readonly (string command, string defaultKey)[] BindCommands =
        {
            ("tf2vr_recenter", "F9"),
            ("tf2vr_switch_eye", "F7"),
            ("tf2vr_toggle_barf", "F8"),
        };

        // the game's binds and convars, read at startup and written back on exit. Titanfall2VR.dll moves the game's
        // config from Documents\Respawn\Titanfall2 to %LOCALAPPDATA%\Respawn\Titanfall2_VR
        public static string SettingsCfg => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Respawn", "Titanfall2_VR", "local", "settings.cfg");

        static readonly Regex BindLine = new Regex(@"^\s*bind\s+""([^""]*)""\s+""([^""]*)""\s*$");

        // key -> command for every bind in the game's settings.cfg; empty when the game hasn't written it yet
        public static Dictionary<string, string> GameBinds(string settingsCfg)
        {
            var binds = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            if (!File.Exists(settingsCfg)) return binds;
            foreach (var line in File.ReadAllLines(settingsCfg))
            {
                var match = BindLine.Match(line);
                if (match.Success) binds[match.Groups[1].Value] = match.Groups[2].Value;
            }
            return binds;
        }

        // command -> key ("" unbound). Rewrites settings.cfg so each command is bound to its key only, replacing whatever
        // those keys did before; without a settings.cfg (the game never ran) returns +bind launch arguments instead.
        public static IEnumerable<string> ApplyBinds(string settingsCfg, IReadOnlyDictionary<string, string> binds)
        {
            var bound = binds.Where(b => b.Value != "").ToArray();
            if (!File.Exists(settingsCfg)) return bound.SelectMany(b => new[] { "+bind", b.Value, b.Key }).ToArray();
            var text = File.ReadAllText(settingsCfg);
            var newline = text.Contains("\r\n") ? "\r\n" : "\n";
            var lines = text.Replace("\r\n", "\n").TrimEnd('\n').Split('\n').Where(line =>
            {
                var match = BindLine.Match(line);
                return !match.Success || !binds.ContainsKey(match.Groups[2].Value)
                    && !bound.Any(b => string.Equals(b.Value, match.Groups[1].Value, StringComparison.OrdinalIgnoreCase));
            }).Concat(bound.Select(b => $"bind \"{b.Value}\" \"{b.Key}\""));
            WriteIfChanged(settingsCfg, Encoding.ASCII.GetBytes(string.Join(newline, lines) + newline));
            return new string[0];
        }

        public static byte[] Patch(byte[] untouched, int width, int height)
        {
            var data = (byte[])untouched.Clone();
            foreach (var patch in PatchSet.patches) Write(data, patch, Hex(patch.replacement));
            var size = new byte[16];
            Buffer.BlockCopy(new[] { 0, 0, width, height }, 0, size, 0, 16);
            Write(data, PatchSet.window, size);
            return data;
        }

        static void Write(byte[] data, KbmPatch patch, byte[] replacement)
        {
            var offset = RvaToOffset(data, patch.rva);
            var expected = Hex(patch.expected);
            if (!Matches(data, offset, expected))
                throw new Exception($"Titanfall2VR.dll doesn't match the keyboard and mouse patch at {patch.rva:x}");
            Buffer.BlockCopy(replacement, 0, data, offset, replacement.Length);
        }

        // current is untouched with a keyboard and mouse patch on it, from this launcher or an earlier one whose patch
        // sites may differ: same size and only a few KB changed. A Titanfall 2 VR update rebuilds the plugin and changes
        // far more, so its untouched copy is never mistaken for one of ours.
        const int MaxPatchedBytes = 16 * 1024;

        static bool IsPatchedFrom(byte[] untouched, byte[] current)
        {
            if (untouched.Length != current.Length) return false;
            var changed = 0;
            for (var i = 0; i < current.Length; i++)
                if (current[i] != untouched[i] && ++changed > MaxPatchedBytes) return false;
            return true;
        }

        static bool Matches(byte[] data, int offset, byte[] bytes)
        {
            if (offset + bytes.Length > data.Length) return false;
            for (var i = 0; i < bytes.Length; i++)
                if (data[offset + i] != bytes[i]) return false;
            return true;
        }

        static int RvaToOffset(byte[] data, int rva)
        {
            var pe = BitConverter.ToInt32(data, 0x3c);
            var sections = BitConverter.ToUInt16(data, pe + 6);
            var optional = BitConverter.ToUInt16(data, pe + 20);
            var table = pe + 24 + optional;
            for (var i = 0; i < sections; i++)
            {
                var entry = table + i * 40;
                var virtualSize = BitConverter.ToInt32(data, entry + 8);
                var virtualAddress = BitConverter.ToInt32(data, entry + 12);
                var rawSize = BitConverter.ToInt32(data, entry + 16);
                var raw = BitConverter.ToInt32(data, entry + 20);
                if (rva >= virtualAddress && rva < virtualAddress + Math.Max(virtualSize, rawSize)) return raw + rva - virtualAddress;
            }
            throw new Exception($"rva {rva:x} is outside Titanfall2VR.dll");
        }

        // a junction or symlink is a developer checkout (install.py --link); never write into it
        static void DeployMod(string minimal)
        {
            if (Directory.Exists(minimal) && new DirectoryInfo(minimal).Attributes.HasFlag(FileAttributes.ReparsePoint)) return;
            var prefix = Resources + "mod/";
            foreach (var name in Assembly.GetExecutingAssembly().GetManifestResourceNames().Where(n => n.StartsWith(prefix, StringComparison.Ordinal)))
            {
                var destination = Path.Combine(minimal, name.Substring(prefix.Length).Replace('/', Path.DirectorySeparatorChar));
                Directory.CreateDirectory(Path.GetDirectoryName(destination));
                using (var resource = Assembly.GetExecutingAssembly().GetManifestResourceStream(name))
                using (var file = File.Create(destination))
                    resource.CopyTo(file);
            }
        }

        // same edits as install.py's edit_menu; each pattern must match exactly once in Titanfall 2 VR's file
        static void EditMenuFile(string path, KbmMenuEdit edit)
        {
            var raw = File.ReadAllBytes(path);
            var utf16 = raw.Length >= 2 && raw[0] == 0xff && raw[1] == 0xfe;
            var encoding = utf16 ? new UnicodeEncoding(false, true) : (Encoding)new UTF8Encoding(false);
            var text = encoding.GetString(raw, utf16 ? 2 : 0, raw.Length - (utf16 ? 2 : 0));
            var crlf = text.Contains("\r\n");
            text = text.Replace("\r\n", "\n");
            var regex = new Regex(edit.pattern);
            var matches = regex.Matches(text).Count;
            if (matches != 1) throw new Exception($"Titanfall 2 VR's {edit.file} changed ({matches} matches), keyboard and mouse can't add its settings");
            text = regex.Replace(text, _ => edit.replacement);
            if (crlf) text = text.Replace("\n", "\r\n");
            File.WriteAllBytes(path, (utf16 ? encoding.GetPreamble() : new byte[0]).Concat(encoding.GetBytes(text)).ToArray());
        }

        // enabledmods.json: {"Version": 1, "<mod>": {"<version>": true}, ...}; Cockpit off and TF2VR.Minimal on, or back
        static void SetEnabledMods(string gamePath, bool kbm)
        {
            var path = Path.Combine(Profile(gamePath), "enabledmods.json");
            var text = File.ReadAllText(path);
            var cockpit = ModBlock(CockpitMod);
            text = cockpit.IsMatch(text)
                ? cockpit.Replace(text, m => Regex.Replace(m.Value, "true|false", (!kbm).ToString().ToLowerInvariant()))
                : AddMod(text, $"\"{CockpitMod}\": {{ \"1.0.0\": {(!kbm).ToString().ToLowerInvariant()} }}");
            var minimal = $"\"{PatchSet.modName}\": {{ \"{PatchSet.modVersion}\": {kbm.ToString().ToLowerInvariant()} }}";
            var block = ModBlock(PatchSet.modName);
            text = block.IsMatch(text) ? block.Replace(text, _ => minimal) : AddMod(text, minimal);
            WriteIfChanged(path, Encoding.UTF8.GetBytes(text));
        }

        static Regex ModBlock(string mod) => new Regex("\"" + Regex.Escape(mod) + @"""\s*:\s*\{[^}]*\}");

        static string AddMod(string text, string entry)
        {
            var end = text.LastIndexOf('}');
            return text.Substring(0, end).TrimEnd() + ",\n    " + entry + "\n}\n";
        }

        static void WriteIfChanged(string path, byte[] contents)
        {
            if (!File.Exists(path) || !File.ReadAllBytes(path).SequenceEqual(contents)) File.WriteAllBytes(path, contents);
        }

        static string ReadResource(string name)
        {
            using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(Resources + name)
                ?? throw new Exception("launcher is missing its keyboard and mouse patch set"))
            using (var reader = new StreamReader(stream))
                return reader.ReadToEnd();
        }

        static string Sha256(byte[] data)
        {
            using (var sha = SHA256.Create())
                return string.Concat(sha.ComputeHash(data).Select(b => b.ToString("x2")));
        }

        static byte[] Hex(string hex) => Enumerable.Range(0, hex.Length / 2).Select(i => Convert.ToByte(hex.Substring(i * 2, 2), 16)).ToArray();
    }
}
