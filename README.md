# Agent Hive

> Ein heterogener Agenten-Schwarm, dessen Zusammensetzung man aus dem OpenRouter-Katalog baut —
> und der sich gegen Einzelmodelle messen lässt.

**Leitfrage:** Schlägt ein Schwarm aus vielen billigen Modellen ein einzelnes teures Modell
bei gleichem Dollar-Einsatz?

Es gibt reichlich Leaderboards, die Modelle einzeln ranken, und reichlich Multi-Agent-Frameworks,
die Koordination behaupten, ohne sie je zu messen. Dieses Projekt macht beides zusammen und
beantwortet die Frage mit Daten — auch wenn die Antwort „nein" lauten sollte.

Der vollständige Plan mit Methodik und Meilensteinen steht in [PLAN.md](PLAN.md).

---

## Stand

| Meilenstein | Inhalt | Status |
|---|---|---|
| **M0** | Modellkatalog: OpenRouter-Sync, Rollenableitung, Dashboard mit Filtern | fertig |
| **M1** | Harness: Agent-Loop, Werkzeug-Registry, Budget, Provider, Docker-Sandbox | fertig |
| M2 | Task-Templates und automatische Checks | offen |
| M3–M9 | Journal, Sweeps, Schwarm-Engine, Bewertung — siehe [PLAN.md](PLAN.md) | offen |

**Ohne API-Key nutzbar:** Der Modell-Endpunkt von OpenRouter ist öffentlich, ein Katalogstand
liegt dem Repo bei, und der Beispiellauf nutzt einen aufgezeichneten Mock-Provider.

## Der Harness in Aktion

```bash
make demo
```

Spielt einen vollständigen Agentenlauf ab: echter Docker-Container, echte Dateien, echte
Befehle — nur der Modellaufruf ist aufgezeichnet. Der Lauf enthält bewusst einen
halluzinierten Werkzeugnamen, um zu zeigen, dass daraus eine Rückmeldung wird statt eines
Absturzes.

Mit eigenem Key gegen ein echtes Modell:

```bash
HIVE_OPENROUTER_API_KEY=sk-or-... backend/.venv/Scripts/python -m hive.cli run --model anthropic/claude-haiku-4.5 --goal "Baue eine Zähler-Seite" --network bridge
```

## Schnellstart

```bash
make install
```

Backend und Frontend in zwei Terminals:

```bash
make backend
```

```bash
make frontend
```

Dann [http://localhost:5173](http://localhost:5173) öffnen. Ohne `make`:

```bash
python -m venv backend/.venv && backend/.venv/Scripts/python -m pip install -e "backend[dev]" && npm install --prefix frontend
```

Aktuellen Katalogstand holen (überschreibt den mitgelieferten nicht, sondern legt einen neuen
Snapshot an):

```bash
make sync
```

Falls Port 8000 oder 5173 belegt ist: `frontend/.env.local` anlegen mit
`VITE_API_TARGET=http://127.0.0.1:8010` und das Backend mit `API_PORT=8010 make backend` starten.

## Rollen im Schwarm

Die Rollenteilung folgt keiner Entwurfslaune, sondern einer realen Fähigkeitsgrenze: Viele
günstige Modelle beherrschen **kein Tool-Calling**. Statt sie auszuschließen, planen sie als
Scouts in Text — ausführen mit Werkzeugen übernehmen Worker.

| Rolle | Voraussetzung | Aufgabe |
|---|---|---|
| **Scout** | keine | Lösungsraum absuchen, Kandidaten vorschlagen |
| **Worker** | Tool-Calling | Kandidaten in der Sandbox ausarbeiten |
| **Inspector** | Bildverständnis | Ergebnisse prüfen und abstimmen |
| **Queen** | Tool-Calling | Synthese, Patt-Auflösung, Abbruch |

Das Dashboard leitet die Eignung aus `supported_parameters` und `architecture.input_modalities`
ab. Modelle, die für einen vollen Schwarmlauf ausfallen, werden **gedämpft mit Begründung**
angezeigt statt stillschweigend gefiltert.

## Entwurfsentscheidungen, die man im Code sieht

**Preise sind `Decimal`, nie `float`.** OpenRouter liefert Beträge wie `0.00000014` pro Token.
Über zehntausende Aufrufe summieren sich Binärfehler zu sichtbaren Abweichungen. Auf `float`
umgestellt wird ausschließlich für die Anzeige (`query.py`).

**Unbekannter Preis ≠ kostenlos.** OpenRouter nutzt `-1` für variable Tarife. Diese Modelle
fallen aus jedem Preisfilter heraus, statt als „gratis" durchzurutschen und später jede
Kostenschätzung zu unterlaufen.

**Snapshots sind unveränderlich.** Jeder Sync legt einen neuen, zeitgestempelten Stand ab und
speichert die **Rohdaten** mit. Ein Benchmark-Ergebnis muss auf den Modell- und Preisstand von
damals verweisen können, und ältere Snapshots bleiben mit später ergänzten Feldern auswertbar.

**Pydantic ist die einzige Schema-Quelle.** Die TypeScript-Typen entstehen per
`make types` aus dem OpenAPI-Schema von FastAPI. Bei getrenntem Python/TS-Stack ist
Schema-Drift das Standardproblem — CI prüft, dass sich das Schema reproduzierbar erzeugen lässt.

**Werkzeugfehler sind Rückmeldung, kein Absturz.** Ein halluzinierter Werkzeugname liefert dem
Modell die Liste der verfügbaren Werkzeuge, ungültige Argumente liefern den Validierungsfehler,
kaputtes JSON in den Argumenten wird zu leeren Argumenten. Nur so übersteht der Loop schwache
Modelle — und die sollen im Schwarm gerade die Mehrheit stellen. Eine Reißleine nach fünf
Iterationen ohne einen einzigen erfolgreichen Werkzeugaufruf verhindert, dass sich ein Modell
im selben Fehler festbeißt.

**Der Agent-Loop ist die Kontrollvariable.** Jedes Modell und später jede Schwarm-Rolle läuft
durch exakt denselben Code. Werkzeuge laufen bewusst sequenziell: Sie teilen sich einen
Dateibaum, und paralleles Schreiben würde Ergebnisse von der Aufrufreihenfolge abhängig machen.

**Budgets sind harte Grenzen.** Iterationen, Tokens, Laufzeit und Kosten werden durchgesetzt,
nicht empfohlen. Für Modell-gegen-Modell wird über Iterationen und Tokens gedeckelt — ein
Dollar-Deckel gäbe billigen Modellen mehr Versuche. Erst beim Vergleich Schwarm gegen Solo
ist Dollar-Parität die richtige Kontrollvariable.

## Sandbox

Modelle schreiben und **führen** Code aus, deshalb ist die Isolation Pflicht:

- ein Container pro Lauf, Nutzer ohne Root, `cap_drop: ALL`, `no-new-privileges`
- keine Host-Mounts — der Arbeitsbereich verlässt den Container nur durch ausdrückliches Lesen
- Grenzen für Speicher, CPU, Prozesse und Laufzeit je Befehl (`timeout` läuft *im* Container
  und beendet den Prozess wirklich)
- gekappte Werkzeugausgaben, damit ein Build-Log nicht das Kontextfenster sprengt
- Pfadnormalisierung mit `PurePosixPath`: `Path.resolve()` würde auf einem Windows-Host gegen
  das Host-Dateisystem auflösen und den Ausbruchsschutz aushebeln

Diese Zusagen werden getestet, nicht behauptet — `tests/test_sandbox.py` prüft Nutzer, Netzwerk,
Rechteausweitung, Zeitlimit und Ausgabekappung im echten Container.

**Bekannte Lücke:** Das Netzwerk ist derzeit nur ganz an (`bridge`) oder ganz aus (`none`,
Voreinstellung). Der im Plan vorgesehene Egress-Proxy mit Allowlist für Paketregistries fehlt
noch und muss vor dem Einsatz mit fremdem Code kommen.

## Entwicklung

```bash
make check
```

Führt Lint, Typecheck und Tests für beide Seiten aus: `ruff`, `mypy --strict`, `pytest`
(92 Tests), `tsc --noEmit`, `vitest`. Die Backend-Tests laufen **ohne Netz und ohne Key** —
HTTP wird mit `respx` abgefangen, der Katalog kommt aus der Fixture. Die Sandbox-Tests
überspringen sich selbst, wenn kein Docker-Daemon erreichbar ist.

```
backend/hive/
  catalog/     OpenRouter-Sync, Fähigkeitsableitung, Snapshots, Filterung
  harness/     Agent-Loop, Werkzeug-Registry, Budget, Ereignisse, Provider
  sandbox/     Docker-Container, Werkzeuge auf dem Arbeitsbereich
  api/         FastAPI: REST-Endpunkte
  cli.py       hive catalog sync | show, hive run, hive openapi
docker/        Sandbox-Image
frontend/src/
  api/         Client und Typen
  features/catalog/   Kachelraster, Filter, Detailpanel
  lib/         Anzeigeformatierung
```

## Lizenz

MIT
