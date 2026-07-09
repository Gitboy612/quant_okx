; QuantOKX Desktop Inno Setup 安装脚本
; 配合 PyInstaller onedir 产物（dist\QuantOKX-Desktop\*）使用
; 桌面版（PySide6/QML 客户端），不含前端 dist（web 版才用 React 前端）

[Setup]
AppName=QuantOKX Desktop
AppVersion=1.0.0
AppPublisher=QuantOKX
DefaultDirName={autopf}\QuantOKX Desktop
DefaultGroupName=QuantOKX Desktop
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=QuantOKX-Desktop-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
; 安装包图标 + 安装程序图标：桌面端 app.ico
SetupIconFile=..\desktop\resources\icons\app.ico
UninstallDisplayIcon={app}\QuantOKX-Desktop.exe

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项: "; Flags: checkedonce
Name: "startup"; Description: "开机自动启动"; GroupDescription: "附加选项: "; Flags: unchecked

[Files]
Source: "..\dist\QuantOKX-Desktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\QuantOKX Desktop"; Filename: "{app}\QuantOKX-Desktop.exe"; WorkingDir: "{app}"
Name: "{group}\卸载 QuantOKX Desktop"; Filename: "{uninstallexe}"
Name: "{commondesktop}\QuantOKX Desktop"; Filename: "{app}\QuantOKX-Desktop.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{commonstartup}\QuantOKX Desktop"; Filename: "{app}\QuantOKX-Desktop.exe"; WorkingDir: "{app}"; Tasks: startup

[Run]
Filename: "{app}\QuantOKX-Desktop.exe"; Description: "立即启动 QuantOKX Desktop"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
