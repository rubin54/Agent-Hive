"""Aufgezeichneter Beispiellauf für `hive run --provider mock`.

Der Mock-Provider ersetzt nur den Modellaufruf. Sandbox, Werkzeuge, Budget und Loop sind
dieselben wie im Echtbetrieb — es entstehen echte Dateien in einem echten Container, und
der Lauf prüft sein Ergebnis mit echten Befehlen.

Die Aufgabe kommt bewusst ohne Paketinstallation aus, damit sie mit der Voreinstellung
``network="none"`` funktioniert.
"""

from __future__ import annotations

from .harness.providers.mock import MockProvider, call, say

DEMO_GOAL = (
    "Baue eine kleine Web-Seite mit einem Zähler: index.html mit einem Knopf, "
    "counter.js mit der Logik. Prüfe anschließend, dass die JavaScript-Datei syntaktisch "
    "korrekt ist."
)

INDEX_HTML = """<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8" />
    <title>Zähler</title>
  </head>
  <body>
    <h1>Zähler</h1>
    <output id="value">0</output>
    <button id="increment">+1</button>
    <script src="counter.js"></script>
  </body>
</html>
"""

COUNTER_JS = """const output = document.getElementById("value");
const button = document.getElementById("increment");

let count = 0;

button.addEventListener("click", () => {
  count += 1;
  output.textContent = String(count);
});
"""


def build_demo_provider() -> MockProvider:
    """Skript eines vollständigen Laufs inklusive eines Fehlversuchs.

    Der falsche Werkzeugname in Schritt 3 ist Absicht: Er zeigt, dass ein halluziniertes
    Werkzeug als Rückmeldung im Gespräch landet und der Lauf weiterläuft, statt zu sterben.
    Genau das entscheidet später darüber, ob schwache Scout-Modelle überhaupt brauchbar sind.
    """
    return MockProvider(
        [
            call("list_files", {"path": "."}),
            call("write_file", {"path": "index.html", "content": INDEX_HTML}),
            call("erstelle_datei", {"path": "counter.js"}),  # Werkzeug existiert nicht
            call("write_file", {"path": "counter.js", "content": COUNTER_JS}),
            call("run_command", {"command": "node --check counter.js && echo SYNTAX_OK"}),
            call("list_files", {"path": "."}),
            say(
                "Fertig. index.html bindet counter.js ein, der Knopf erhöht den Zähler. "
                "Die Syntaxprüfung mit `node --check` läuft ohne Fehler durch. "
                "Zum Ansehen genügt es, index.html im Browser zu öffnen."
            ),
        ],
        model_id="mock/demo-scripted",
    )
