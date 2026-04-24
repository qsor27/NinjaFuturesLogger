[Code]

var
  DataDir: string;

function GetDataDir(Param: string): string;
begin
  if DataDir = '' then
    DataDir := ExpandConstant('{localappdata}\NinjaFuturesLogger\data');
  Result := DataDir;
end;

function NeedsWebView2(): Boolean;
var
  Version: string;
begin
  Result := True;
  if RegQueryStringValue(HKLM,
      'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
      'pv', Version) then
  begin
    if Version <> '' then Result := False;
  end;
  if Result and RegQueryStringValue(HKCU,
      'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
      'pv', Version) then
  begin
    if Version <> '' then Result := False;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  UserDataDir: string;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    UserDataDir := ExpandConstant('{localappdata}\NinjaFuturesLogger\data');
    if DirExists(UserDataDir) then
    begin
      if MsgBox(
          'Also delete your trade data and logs?' + #13#10 + #13#10 +
          'This will permanently remove ' + UserDataDir + ',' + #13#10 +
          'including your SQLite database, imported CSVs, and all logs.' + #13#10 + #13#10 +
          'This cannot be undone.',
          mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      begin
        DelTree(UserDataDir, True, True, True);
      end;
    end;
  end;
end;
