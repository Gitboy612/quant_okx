; QuantOKX Inno Setup 安装脚本
; 配合 PyInstaller onedir 产物（dist\QuantOKX\*）使用

[Setup]
AppName=QuantOKX
AppVersion=1.0.0
AppPublisher=QuantOKX
DefaultDirName={autopf}\QuantOKX
DefaultGroupName=QuantOKX
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=QuantOKX-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
; SetupIconFile=assets\quantokx.ico
UninstallDisplayIcon={app}\QuantOKX.exe

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项: "; Flags: checkedonce
Name: "startup"; Description: "开机自动启动"; GroupDescription: "附加选项: "; Flags: unchecked

[Files]
Source: "..\dist\QuantOKX\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\QuantOKX"; Filename: "{app}\QuantOKX.exe"; WorkingDir: "{app}"
Name: "{group}\卸载 QuantOKX"; Filename: "{uninstallexe}"
Name: "{commondesktop}\QuantOKX"; Filename: "{app}\QuantOKX.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{commonstartup}\QuantOKX"; Filename: "{app}\QuantOKX.exe"; WorkingDir: "{app}"; Tasks: startup

[Run]
Filename: "{app}\QuantOKX.exe"; Description: "立即启动 QuantOKX"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
