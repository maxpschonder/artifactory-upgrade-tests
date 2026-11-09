# Spec: Artifactory Upgrade-Tests

## Ziel

Eine Testsuite, die eine Artifactory-Instanz vor und nach einem Upgrade prüft. Für jedes Paketformat und jede Repository-Art werden Artefakte hochgeladen und heruntergeladen. Nach dem Upgrade wird geprüft, dass die vorher hochgeladenen Artefakte weiterhin abrufbar sind und Push/Pull unverändert funktioniert. Die Ergebnisse werden übersichtlich und manuell nachvollziehbar aufbereitet.

## Scope

**Formate:** Docker, Maven, npm, PyPI, Helm, Generic.

**Repository-Arten:** Local, Remote, Virtual.

- Local: Push und Pull.
- Remote: Pull eines öffentlichen Upstream-Artefakts über das Remote-Repo (Caching prüfen).
- Virtual: Pull über das Virtual-Repo, das Local und Remote aggregiert; Push über Virtual, sofern ein Default-Deployment-Repo konfiguriert ist.

## Ablauf

1. **Phase `pre`** (vor dem Upgrade): Für jede Kombination Format × Repo-Art Testartefakte mit eindeutiger Run-ID erzeugen, pushen, pullen und per Checksumme (SHA-256) verifizieren. Ein Manifest (JSON) mit allen hochgeladenen Artefakten, Koordinaten und Checksummen wird gespeichert.
2. Upgrade von Artifactory (manuell, außerhalb der Suite).
3. **Phase `post`** (nach dem Upgrade):
   - Alle im Manifest gelisteten Artefakte erneut herunterladen und Checksummen vergleichen.
   - Dieselben Push/Pull-Tests wie in `pre` mit neuer Run-ID ausführen.
4. **Report:** Vergleich `pre` gegen `post`.

## Authentifizierung

- Die Suite erwartet einen Access Token und die Basis-URL als Umgebungsvariablen (`ARTIFACTORY_URL`, `ARTIFACTORY_TOKEN`).
- Repo-Namen pro Format und Art sind konfigurierbar (Config-Datei, z. B. YAML), da sie in der bestehenden Instanz abweichen können.
- Für die lokale Entwicklungsumgebung erzeugt ein Setup-Skript den Token über die Artifactory-API und legt die benötigten Repositories an.

## Technische Umsetzung

- Orchestrierung über Docker Compose; pro Format ein Client-Container mit dem nativen Tool (docker/skopeo, mvn, npm, pip/twine, helm, curl).
- Ein Runner in Python mit pytest steuert die Tests, parametrisiert über Format × Repo-Art.
- Aufruf z. B. `./run.sh pre` bzw. `./run.sh post`.
- Tests sind idempotent; Testartefakte tragen die Run-ID im Namen bzw. in der Version, um Kollisionen zu vermeiden.
- Optionale HTTP-Proxy-Konfiguration (z. B. HTTP\_PROXY/HTTPS\_PROXY) für die Clients vorsehen; Umsetzung später. Die Upstream-Artefakte für Remote-Tests sind konfigurierbar.

## Entwicklungsumgebung

- Separater Compose-Stack mit Artifactory (versionierbar über Variable, z. B. `ARTIFACTORY_VERSION`), damit die Tests selbst entwickelt und getestet werden können.
- Upgrade-Szenario lokal reproduzierbar: Stack mit alter Version starten, `pre` ausführen, Image-Version anheben, Container neu starten (persistentes Volume), `post` ausführen.
- Hinweis: Prüfen, welche Edition (z. B. JFrog Container Registry oder Artifactory Pro/Trial) alle benötigten Formate unterstützt.

## Report

- **HTML-Report** als primäre Ausgabe: Matrix Format × Repo-Art mit Status (grün/rot) für `pre`, `post` und Abrufbarkeit der Altartefakte; Fehlermeldungen und Logs pro Test aufklappbar.
- Zusätzlich **JUnit-XML**, um die Suite später in eine GitLab-Pipeline einzubinden.
- Rohdaten (Manifest, Ergebnisse) als JSON im Ausgabeverzeichnis.

## Akzeptanzkriterien

- `pre` und `post` laufen gegen die lokale Compose-Instanz vollständig durch.
- Ein absichtlich gelöschtes Artefakt wird in `post` als Fehler erkannt.
- Report zeigt alle 18 Kombinationen und ist ohne weitere Tools im Browser lesbar.
- Gegen eine bestehende Instanz reicht das Setzen von URL, Token und Repo-Config.

## Offene Punkte

- Entschieden: Python mit pytest als Runner.
- Entschieden: Instanz hängt ggf. hinter einem HTTP-Proxy; Proxy-Support wird vorgesehen und später eingebaut.
- Entschieden: Tests laufen in eigenen, dedizierten Test-Repos (pro Format × Art), die nach dem Test komplett entfernt werden können.
