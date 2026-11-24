; ============================================================
; Space Shooter — Installer Script (Inno Setup)
; ============================================================

[Setup]
AppId={{A3B2C1D4-E5F6-7890-ABCD-EF1234567891}
AppName=Space Shooter
AppVersion=1.1.0
AppPublisher=Space Shooter Team
AppPublisherURL=https://github.com/makarbogatirev-dot/space-shooter
AppSupportURL=https://github.com/makarbogatirev-dot/space-shooter
AppUpdatesURL=https://github.com/makarbogatirev-dot/space-shooter
DefaultDirName={autopf}\Space Shooter
DefaultGroupName=Space Shooter
OutputDir=installer_output
OutputBaseFilename=SpaceShooter_Setup_Universal
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
Name: desktopicon; Description: "Создать ярлыки на рабочем столе"; Flags: unchecked

[Components]
; Универсальный установщик Space Shooter: v1.1 (финальная) и v1.0.
; Пользователь выбирает одну или обе версии при установке.
Name: "v11"; Description: "Space Shooter v1.1 — аккаунты, друзья, таблица лидеров, бонусы (рекомендуется)"; Flags: checkablealone
Name: "v10"; Description: "Space Shooter v1.0 — первый релиз, без аккаунтов"; Flags: checkablealone

[Files]
; exe каждой версии в свою подпапку (обе называются SpaceShooter.exe);
; все ресурсы (картинки, звуки, шрифт) уже упакованы внутрь exe PyInstaller
Source: "space_shuter v1.1\dist\SpaceShooter.exe"; DestDir: "{app}\v1.1"; DestName: "SpaceShooter.exe"; Components: v11; Flags: ignoreversion
Source: "space_shuter v1.0\dist\SpaceShooter.exe"; DestDir: "{app}\v1.0"; DestName: "SpaceShooter.exe"; Components: v10; Flags: ignoreversion
Source: "installer_icon.ico"; DestDir: "{app}"; DestName: "space_shuter.ico"; Flags: ignoreversion

[Icons]
Name: "{group}\Space Shooter (v1.1)"; Filename: "{app}\v1.1\SpaceShooter.exe"; IconFilename: "{app}\space_shuter.ico"; Components: v11
Name: "{group}\Space Shooter (v1.0)"; Filename: "{app}\v1.0\SpaceShooter.exe"; IconFilename: "{app}\space_shuter.ico"; Components: v10
Name: "{group}\Удалить Space Shooter"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Space Shooter (v1.1)"; Filename: "{app}\v1.1\SpaceShooter.exe"; IconFilename: "{app}\space_shuter.ico"; Tasks: desktopicon; Components: v11
Name: "{userdesktop}\Space Shooter (v1.0)"; Filename: "{app}\v1.0\SpaceShooter.exe"; IconFilename: "{app}\space_shuter.ico"; Tasks: desktopicon; Components: v10

[Run]
Filename: "{app}\v1.1\SpaceShooter.exe"; Description: "Запустить Space Shooter v1.1"; Flags: nowait postinstall skipifsilent; Components: v11
Filename: "{app}\v1.0\SpaceShooter.exe"; Description: "Запустить Space Shooter v1.0"; Flags: nowait postinstall skipifsilent; Components: v10
