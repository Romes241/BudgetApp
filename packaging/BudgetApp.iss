#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#ifndef SourceDir
  #define SourceDir "..\dist\BudgetApp"
#endif

[Setup]
AppId={{B71B3EA6-7E29-4C7E-BB54-61B9CC6A4D17}
AppName=BudgetApp
AppVersion={#AppVersion}
AppPublisher=Romeo Mondeke
DefaultDirName={localappdata}\Programs\BudgetApp
DefaultGroupName=BudgetApp
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=BudgetApp-Setup-{#AppVersion}
UninstallDisplayIcon={app}\BudgetApp.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\src\budget_app\assets\BudgetApp.ico

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\BudgetApp"; Filename: "{app}\BudgetApp.exe"
Name: "{autodesktop}\BudgetApp"; Filename: "{app}\BudgetApp.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BudgetApp.exe"; Description: "Launch BudgetApp"; Flags: nowait postinstall skipifsilent
