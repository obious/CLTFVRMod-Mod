using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace BigWalkVRInstaller.Services
{
    public class AppSettings
    {
        public const string ManifestUrl = "https://raw.githubusercontent.com/CircuitLord/CircuitLordVRModInstaller/main/manifest-v3.json";
        public string GamePath;
        public string BigWalkPath;
        public string Titanfall2Path;
        // selected channel ids, null is stable
        public string BigWalkChannel;
        public string Titanfall2Channel;
        public bool Titanfall2EaSignedIn;
        // keyboard and mouse play (CLTFVRMod-Mod), on unless turned off; the serializer skips initializers
        public bool? Titanfall2Kbm;
        public bool Titanfall2KbmEnabled => Titanfall2Kbm ?? true;
        // mouse up/down tilts the VR view (tf2vr_barf_mode), off unless turned on
        public bool Titanfall2BarfMode;
        // skip the arm-span/height calibration at startup (tf2vr_skip_cal), on unless turned off
        public bool? Titanfall2SkipCalibration;
        public bool Titanfall2SkipCalibrationEnabled => Titanfall2SkipCalibration ?? true;
        // keys for TF2VR.Minimal's commands (TitanfallKbm.BindCommands), Source key names; null is the default, "" unbound
        public Dictionary<string, string> Titanfall2Keys;

        public string Titanfall2Key(string command) =>
            Titanfall2Keys != null && Titanfall2Keys.TryGetValue(command, out var key) ? key
                : Installers.TitanfallKbm.BindCommands.First(b => b.command == command).defaultKey;

        public Dictionary<string, string> Titanfall2Binds() =>
            Installers.TitanfallKbm.BindCommands.ToDictionary(b => b.command, b => Titanfall2Key(b.command));

        static string Dir => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "BigWalkVRInstaller");
        static string FilePath => Path.Combine(Dir, "settings.json");

        public static string LoadError;

        public static AppSettings Load()
        {
            try
            {
                if (File.Exists(FilePath))
                {
                    var settings = JsonUtil.Deserialize<AppSettings>(File.ReadAllText(FilePath)) ?? new AppSettings();
                    if (string.IsNullOrEmpty(settings.BigWalkPath)) settings.BigWalkPath = settings.GamePath;
                    return settings;
                }
            }
            catch (Exception ex)
            {
                LoadError = ex.Message;
            }
            return new AppSettings();
        }

        public void Save()
        {
            Directory.CreateDirectory(Dir);
            File.WriteAllText(FilePath, JsonUtil.Serialize(this));
        }
    }
}
