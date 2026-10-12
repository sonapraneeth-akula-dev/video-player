; Per-user VPlayer installer; built by scripts/package.py with /DAppVersion, /DSourceDir and /DOutputBase.
#ifndef AppVersion
  #error Pass /DAppVersion=<version>
#endif

[Setup]
AppId={{6F2C2E7A-3B0D-4D8E-9C8F-2A1B5E4D7C11}
AppName=VPlayer
AppVersion={#AppVersion}
AppPublisher=VPlayer
DefaultDirName={autopf}\VPlayer
DefaultGroupName=VPlayer
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ChangesAssociations=yes
ChangesEnvironment=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#SourceDir}\..
OutputBaseFilename={#OutputBase}
UninstallDisplayIcon={app}\vplayer.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: addtopath; Description: "Add VPlayer to PATH (run ""vplayer"" from a terminal)"
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\VPlayer"; Filename: "{app}\vplayer.exe"
Name: "{autodesktop}\VPlayer"; Filename: "{app}\vplayer.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Classes\VPlayer.Media"; ValueType: string; ValueData: "VPlayer media file"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\VPlayer.Media\DefaultIcon"; ValueType: string; ValueData: "{app}\vplayer.exe,0"
Root: HKCU; Subkey: "Software\Classes\VPlayer.Media\shell\open\command"; ValueType: string; ValueData: """{app}\vplayer.exe"" ""%1"""
#dim Ext[11] {"mp4", "mkv", "webm", "mov", "avi", "ts", "m4v", "wmv", "flv", "mpg", "mpeg"}
#define I
#sub RegisterExt
Root: HKCU; Subkey: "Software\Classes\.{#Ext[I]}\OpenWithProgids"; ValueType: string; ValueName: "VPlayer.Media"; ValueData: ""; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.{#Ext[I]}\shell\VPlayer.NewWindow"; ValueType: string; ValueData: "Open in new VPlayer window"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\SystemFileAssociations\.{#Ext[I]}\shell\VPlayer.NewWindow\command"; ValueType: string; ValueData: """{app}\vplayer.exe"" --new-window ""%1"""
#endsub
#for {I = 0; I < 11; I++} RegisterExt

[Code]
const
  EnvKey = 'Environment';
  MarkerKey = 'Software\VPlayer';

{ Removes entries equal to Dir without rewriting unrelated PATH separators. }
function StripDir(Path, Dir: String; var Found: Boolean): String;
var
  Item: String;
  StartIndex, EndIndex, P: Integer;
begin
  Result := Path;
  Found := False;
  StartIndex := 1;
  while StartIndex <= Length(Result) do
  begin
    P := Pos(';', Copy(Result, StartIndex, Length(Result)));
    if P = 0 then
      EndIndex := Length(Result) + 1
    else
      EndIndex := StartIndex + P - 1;
    Item := Copy(Result, StartIndex, EndIndex - StartIndex);
    if CompareText(RemoveBackslash(Trim(Item)), RemoveBackslash(Dir)) = 0 then
    begin
      Found := True;
      if EndIndex <= Length(Result) then
        Delete(Result, StartIndex, EndIndex - StartIndex + 1)
      else if StartIndex > 1 then
        Delete(Result, StartIndex - 1, EndIndex - StartIndex + 1)
      else
        Result := '';
    end
    else
    begin
      StartIndex := EndIndex + 1;
    end;
  end;
end;

procedure AddToPath;
var
  Path: String;
  Found: Boolean;
begin
  if not RegQueryStringValue(HKCU, EnvKey, 'Path', Path) then
  begin
    Path := '';
    RegWriteStringValue(HKCU, MarkerKey, 'PathWasAbsent', '1');
  end;
  StripDir(Path, ExpandConstant('{app}'), Found);
  if Found then
    Exit;
  if (Path <> '') and (Path[Length(Path)] = ';') then
    RegWriteStringValue(HKCU, MarkerKey, 'PathHadTrailingSeparator', '1');
  if (Path <> '') and (Path[Length(Path)] <> ';') then
    Path := Path + ';';
  RegWriteExpandStringValue(HKCU, EnvKey, 'Path', Path + ExpandConstant('{app}'));
  RegWriteStringValue(HKCU, MarkerKey, 'PathAdded', '1');
end;

{ Removes only the entry this installer added; a pre-existing entry is left alone. }
procedure RemoveFromPath;
var
  Path, Marker, WasAbsent, HadTrailingSeparator: String;
  Found: Boolean;
begin
  if not RegQueryStringValue(HKCU, MarkerKey, 'PathAdded', Marker) or (Marker <> '1') then
    Exit;
  if RegQueryStringValue(HKCU, EnvKey, 'Path', Path) then
  begin
    Path := StripDir(Path, ExpandConstant('{app}'), Found);
    if Found then
    begin
      if RegQueryStringValue(HKCU, MarkerKey, 'PathHadTrailingSeparator', HadTrailingSeparator)
         and (HadTrailingSeparator = '1') and (Path <> '') and (Path[Length(Path)] <> ';') then
        Path := Path + ';';
      if (Path = '') and RegQueryStringValue(HKCU, MarkerKey, 'PathWasAbsent', WasAbsent)
         and (WasAbsent = '1') then
        RegDeleteValue(HKCU, EnvKey, 'Path')
      else
        RegWriteExpandStringValue(HKCU, EnvKey, 'Path', Path);
    end;
  end;
  RegDeleteValue(HKCU, MarkerKey, 'PathAdded');
  RegDeleteValue(HKCU, MarkerKey, 'PathWasAbsent');
  RegDeleteValue(HKCU, MarkerKey, 'PathHadTrailingSeparator');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    if WizardIsTaskSelected('addtopath') then
      AddToPath
    else
      RemoveFromPath;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RemoveFromPath;
    RegDeleteKeyIncludingSubkeys(HKCU, MarkerKey);
  end;
end;
