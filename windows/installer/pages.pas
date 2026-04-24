[Code]

var
  DataDir: string;
  DataDirPage: TInputDirWizardPage;

procedure InitializeWizard();
begin
  DataDirPage := CreateInputDirPage(
    wpSelectDir,
    'Select Data Directory',
    'Where should NinjaFuturesLogger keep your trade data?',
    'Your SQLite database, imported CSVs, archive, and logs will be stored here.' + #13#10 +
    'You can accept the default or choose a custom location (e.g., a secondary drive).',
    False,
    ''
  );
  DataDirPage.Add('Data directory:');
  DataDirPage.Values[0] := ExpandConstant('{localappdata}\NinjaFuturesLogger\data');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = DataDirPage.ID) then
  begin
    DataDir := DataDirPage.Values[0];
    if not ForceDirectories(DataDir) then
    begin
      MsgBox('Could not create data directory: ' + DataDir, mbError, MB_OK);
      Result := False;
    end
    else
    begin
      ForceDirectories(DataDir + '\config');
      ForceDirectories(DataDir + '\inbox');
      ForceDirectories(DataDir + '\archive');
      ForceDirectories(DataDir + '\logs');
    end;
  end;
end;

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
    // Note: at uninstall time we can't easily read the registry (it's
    // already removed by uninsdeletevalue). Prompt based on the default
    // location only. Users with custom paths will need to remove those
    // manually — documented in windows/README.md.
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
