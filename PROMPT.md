Du bist mein Software-Planer und -Architekt fuer das Projekt `WinVPN-Manager` (Windows GUI, Python + PySide6).

Ziel: Die App soll neben dem bestehenden Listing + Connect/Disconnect auch Windows-VPN-Profile erstellen, updaten und loeschen koennen. Credentials werden NICHT von der App verwaltet; das macht Windows (User soll einmal ueber Windows VPN Settings verbinden und "Credentials speichern").

Rahmenbedingungen
- Nutze nur Windows-Bordmittel (Windows Defaults): PowerShell `VpnClient` Cmdlets und `rasdial.exe`.
- Kein Import/Export von Templates.
- CRUD muss sowohl fuer User-Profile (ohne Admin) als auch optional fuer systemweite Profile (`-AllUserConnection`, Admin) funktionieren.
- Wichtig: gleiche Profilnamen koennen in User- und All-User-Scope existieren -> Identitaet ist `(name, scope)`, niemals nur `name` deduplizieren.

MVP Scope
- Profile-Liste anzeigen inkl. Scope-Spalte (User/System) und Status.
- Profil erstellen: minimal `Name`, `ServerAddress`, `TunnelType` (Default/Windows: `Automatic`), Scope Toggle (User/Systemweit).
- Profil updaten: minimal `ServerAddress` und `TunnelType` (kein Rename im MVP).
- Profil loeschen: mit Sicherheitsabfrage.
- Connect/Disconnect bleibt wie vorhanden; muss mit Scope korrekt arbeiten.

Technische Umsetzung (Cmdlets)
- List:
  - User: `Get-VpnConnection | Select-Object Name,ServerAddress,TunnelType,AuthenticationMethod,ConnectionStatus`
  - All-User: `Get-VpnConnection -AllUserConnection | Select-Object ...`
- Create:
  - `Add-VpnConnection -Name 'X' -ServerAddress 'Y' -TunnelType Automatic [-AllUserConnection]`
- Update:
  - `Set-VpnConnection -Name 'X' -ServerAddress 'Y' -TunnelType Automatic [-AllUserConnection]`
- Delete:
  - `Remove-VpnConnection -Name 'X' [-AllUserConnection] -Force`
- Status:
  - `Get-VpnConnection -Name 'X' [-AllUserConnection] | Select-Object ConnectionStatus`
- Admin-Handling: Wenn `-AllUserConnection` angefordert, vorher Admin-Check; sonst klare Fehlermeldung.
- Ergebnisse: Einheitliche `OperationResult` Rueckgabe (stdout/stderr in `details`, keine Secrets loggen).

Backend API (Erweiterung)
- `create_profile(spec, all_users: bool) -> OperationResult`
- `update_profile(name, spec, all_users: bool) -> OperationResult`
- `delete_profile(name, all_users: bool) -> OperationResult`
- `get_status(name: str, all_users: bool) -> str`

UI/UX (PySide6)
- Tabelle: neue Spalte `Scope`.
- Buttons: `New...`, `Edit...`, `Delete` zusaetzlich zu `Connect/Disconnect`.
- Dialog "New/Edit Profile" (minimal):
  - Name (bei Edit read-only), Server Address, Tunnel Type (Combo; Default `Automatic`), Checkbox "Systemweit (Admin)".
- Delete-Flow: Confirm-Dialog; danach Refresh (Selektion moeglichst beibehalten).

Akzeptanzkriterien (DoD)
- Create: Profil erscheint in Windows (`Get-VpnConnection` bzw. `-AllUserConnection`) und in der App-Liste mit korrektem Scope.
- Update: Aenderungen sind in Windows sichtbar und ueberleben Neustart.
- Delete: Profil ist weg aus Windows und App.
- Keine Verwechslung bei gleichen Namen in unterschiedlichen Scopes.
- Keine Credential-Verwaltung in der App; Hinweise/Fehlertexte verweisen auf Windows UI.

Arbeitsplan (Inkremente)
1) Modell+Scope: `VpnProfile` um `all_users` erweitern; keine Name-only-Deduplizierung; Status/Connect/Disconnect scope-faehig.
2) CRUD Backend: Add/Set/Remove implementieren + Admin-Fehler + OperationResult.
3) CRUD UI: Dialoge/Buttons/Validierung + Refresh/Selection + saubere Fehlermeldungen.
