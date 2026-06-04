; Inno Setup 安装器配置 —— 一键安装版「Select」。
;
; 构建：装好 Inno Setup 后运行  iscc TranslatePopup.iss
; 产物：installer\TranslatePopup-Setup.exe（用户双击 → 选目录 → 装好 → 立刻能用）。
; 安装内容只有一个 ~26MB 的 onefile exe，自动加 Start 菜单项与卸载入口；
; 「开机自启」是可选项，默认不勾，符合"用户最小同意"原则。

#define MyAppName "Select"
#define MyAppNameEng "Select"
#define MyAppVersion "1.3.1"
#define MyAppPublisher "translate-popup"
#define MyAppExeName "TranslatePopup.exe"
#define MyAppURL "https://translate-omega-livid.vercel.app/"

[Setup]
AppId={{4A2D8E9F-3B1C-4D5E-6F7A-8B9C0D1E2F3A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppNameEng}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
OutputDir=installer
OutputBaseFilename=TranslatePopup-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
DisableReadyPage=no
; 普通用户权限即可安装到用户目录，无需管理员
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
CloseApplications=force
RestartApplications=no

[Languages]
; Inno Setup 6 不官方提供简体中文。沿用英文向导,但任务描述用中文（CustomMessages）。
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "autostart"; Description: "{cm:AutoStartDesc}"; GroupDescription: "{cm:StartupOptions}"; Flags: unchecked

[CustomMessages]
AutoStartDesc=开机自动启动「Select」
StartupOptions=启动选项：

[Files]
Source: "dist\TranslatePopup.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; 开机自启走 HKCU\...\Run（无需管理员），卸载时自动清理
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "TranslatePopup"; \
    ValueData: """{app}\{#MyAppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 用户配置目录不动；如要彻底清，下面这一行取消注释
; Type: filesandordirs; Name: "{userappdata}\..\..\.translate-popup"
