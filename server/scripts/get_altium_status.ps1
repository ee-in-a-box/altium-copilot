if (-not (Get-Process -Name "X2" -ErrorAction SilentlyContinue)) {
    '{"running":false}' | Write-Output
    exit 0
}

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.RegularExpressions;

public class AltiumStatus {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc cb, IntPtr l);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr p, EnumWindowsProc cb, IntPtr l);
    [DllImport("user32.dll", CharSet=CharSet.Auto)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll", CharSet=CharSet.Auto)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    public delegate bool EnumWindowsProc(IntPtr h, IntPtr l);

    public static string[] GetStatus() {
        IntPtr altiumHwnd = IntPtr.Zero;
        string projectFile = "";

        EnumWindows((h, l) => {
            var cls   = new StringBuilder(256);
            var title = new StringBuilder(512);
            GetClassName(h, cls, 256);
            GetWindowText(h, title, 512);
            if (cls.ToString() == "TDocumentForm" && title.ToString().Contains("Altium")) {
                altiumHwnd = h;
                var m = Regex.Match(title.ToString(), @"^(.+?\.PrjPcb)\s*-", RegexOptions.IgnoreCase);
                if (m.Success) projectFile = m.Groups[1].Value.Trim();
                return false; // stop — found Altium
            }
            return true;
        }, IntPtr.Zero);

        if (altiumHwnd == IntPtr.Zero)
            return new string[] { "NOT_RUNNING", "", "" };

        string activeTab = "";
        EnumChildWindows(altiumHwnd, (h, l) => {
            var cls = new StringBuilder(256);
            GetClassName(h, cls, 256);
            if (cls.ToString() == "TdxTabSheet" && IsWindowVisible(h)) {
                var title = new StringBuilder(256);
                GetWindowText(h, title, 256);
                if (title.Length > 0) {
                    activeTab = title.ToString();
                    return false; // stop — first visible tab is the active one
                }
            }
            return true;
        }, IntPtr.Zero);

        // Resolve full project path from known Altium documents root
        string projectPath = "";
        if (projectFile != "") {
            string searchRoot = System.IO.Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.CommonDocuments),
                "Altium"
            );
            if (System.IO.Directory.Exists(searchRoot)) {
                foreach (var f in System.IO.Directory.EnumerateFiles(searchRoot, projectFile,
                             System.IO.SearchOption.AllDirectories)) {
                    projectPath = f;
                    break;
                }
            }
        }

        return new string[] { activeTab, projectFile, projectPath };
    }
}
'@

$r = [AltiumStatus]::GetStatus()

if ($r[0] -eq "NOT_RUNNING") {
    '{"running":true,"warning":"no_sheet_open","project_file":"","project_path":"","active_tab":""}' | Write-Output
    exit 0
}

@{
    running      = $true
    active_tab   = $r[0]
    project_file = $r[1]
    project_path = $r[2]
} | ConvertTo-Json -Compress | Write-Output
