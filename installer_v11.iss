; ============================================================
; Space Shooter v1.1 — Installer Script (Inno Setup)
; Одиночный установщик финальной v1.1.
; ============================================================

[Setup]
AppId={{A3B2C1D4-E5F6-7890-ABCD-EF1234567892}
AppName=Space Shooter
AppVersion=1.1.0
AppPublisher=Space Shooter Team
AppPublisherURL=https://github.com/makarbogatirev-dot/space-shooter
AppSupportURL=https://github.com/makarbogatirev-dot/space-shooter
AppUpdatesURL=https://github.com/makarbogatirev-dot/space-shooter
DefaultDirName={autopf}\Space Shooter
DefaultGroupName=Space Shooter
OutputDir=installer_output
OutputBaseFilename=SpaceShooter_Setup_v1.1
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

; Иконки и графика
SetupIconFile=installer_icon.ico
UninstallDisplayIcon={app}\space_shuter.ico

DisableProgramGroupPage=yes

[Languages]
Name: russian; MessagesFile: "C:\Users\Makar\AppData\Local\Programs\Inno Setup 6\Languages\Russian.isl"

[Tasks]
Name: desktopicon; Description: "Создать ярлык на рабочем столе"; Flags: unchecked

[Files]
; все ресурсы (картинки, звуки, шрифт) уже упакованы внутрь exe PyInstaller
Source: "space_shuter v1.1\dist\SpaceShooter.exe"; DestDir: "{app}"; DestName: "SpaceShooter.exe"; Flags: ignoreversion
Source: "installer_icon.ico"; DestDir: "{app}"; DestName: "space_shuter.ico"; Flags: ignoreversion

[Icons]
Name: "{group}\Space Shooter (v1.1)"; Filename: "{app}\SpaceShooter.exe"; IconFilename: "{app}\space_shuter.ico"
Name: "{group}\Удалить Space Shooter"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Space Shooter (v1.1)"; Filename: "{app}\SpaceShooter.exe"; IconFilename: "{app}\space_shuter.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\SpaceShooter.exe"; Description: "Запустить Space Shooter v1.1"; Flags: nowait postinstall skipifsilent
