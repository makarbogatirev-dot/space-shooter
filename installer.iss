; ============================================================
; Space Shooter — Installer Script (Inno Setup)
; ============================================================

[Setup]
AppId={{A3B2C1D4-E5F6-7890-ABCD-EF1234567890}
AppName=Space Shooter
AppVersion=1.0
AppPublisher=Space Shooter Team
AppPublisherURL=https://example.com
AppSupportURL=https://example.com
AppUpdatesURL=https://example.com
DefaultDirName={autopf}\Space Shooter
DefaultGroupName=Space Shooter
OutputDir=installer_output
OutputBaseFilename=SpaceShooter_Setup_v1.0
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

; Иконки и графика
SetupIconFile=installer_icon.ico
UninstallDisplayIcon={app}\SpaceShooter.exe

; Окно с лицензией (можно добавить)
DisableProgramGroupPage=yes

[Languages]
Name: russian; MessagesFile: "C:\Users\Makar\AppData\Local\Programs\Inno Setup 6\Languages\Russian.isl"

[Tasks]
Name: desktopicon; Description: "Создать ярлык на рабочем столе"; Flags: unchecked

[Files]
; Основной exe (с упакованными картинками)
Source: "space_shuter v1.0\dist\SpaceShooter.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "installer_icon.ico"; DestDir: "{app}"; DestName: "space_shuter.ico"; Flags: ignoreversion

; Папка с исходниками (опционально — для разработчиков)
; Source: "space_shuter v1.0\space_shuter.py"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Space Shooter"; Filename: "{app}\SpaceShooter.exe"; IconFilename: "{app}\space_shuter.ico"
Name: "{group}\Удалить Space Shooter"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Space Shooter"; Filename: "{app}\SpaceShooter.exe"; IconFilename: "{app}\space_shuter.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\SpaceShooter.exe"; Description: "Запустить Space Shooter"; Flags: nowait postinstall skipifsilent
