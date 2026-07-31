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

## Stand: M0 — Modellkatalog

Erledigt ist der Katalog: OpenRouter-Sync, Ableitung der Schwarm-Rollentauglichkeit und ein
Dashboard mit Filtern. **Läuft ohne API-Key** — der Modell-Endpunkt von OpenRouter ist öffentlich,
und ein Katalogstand liegt dem Repo bei.

Die Schwarm-Engine (M5) und der Benchmark (M4/M7) folgen; siehe Meilensteine im Plan.

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

## Entwicklung

```bash
make check
```

Führt Lint, Typecheck und Tests für beide Seiten aus: `ruff`, `mypy --strict`, `pytest`
(33 Tests), `tsc --noEmit`, `vitest`. Die Backend-Tests laufen **ohne Netz** — HTTP wird mit
`respx` abgefangen, der Katalog kommt aus der Fixture.

```
backend/hive/
  catalog/     OpenRouter-Sync, Fähigkeitsableitung, Snapshots, Filterung
  api/         FastAPI: REST-Endpunkte
  cli.py       hive catalog sync | show, hive openapi
frontend/src/
  api/         Client und Typen
  features/catalog/   Kachelraster, Filter, Detailpanel
  lib/         Anzeigeformatierung
```

## Lizenz

MIT
