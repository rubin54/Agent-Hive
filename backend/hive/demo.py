"""Recorded example runs for ``hive run --provider mock``.

The mock provider replaces only the model call. Sandbox, tools, budget and loop are the same
as in live operation — real files appear in a real container, and the run verifies its result
with real commands.

The free-form task deliberately needs no package installation so it works with the default
``network="none"``.
"""

from __future__ import annotations

from .harness.providers.mock import MockProvider, call, say

DEMO_GOAL = (
    "Build a small web page with a counter: index.html with a button, counter.js with the "
    "logic. Afterwards verify that the JavaScript file is syntactically valid."
)

INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Counter</title>
  </head>
  <body>
    <h1>Counter</h1>
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

COUNTER_INDEX = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Counter</title>
  </head>
  <body>
    <h1>Counter</h1>
    <output id="value">0</output>
    <button id="increment">+1</button>
    <button id="reset">Reset</button>
    <script src="counter.js"></script>
  </body>
</html>
"""

COUNTER_LOGIC = """const output = document.getElementById("value");

let count = 0;

function render() {
  output.textContent = String(count);
}

document.getElementById("increment").addEventListener("click", () => {
  count += 1;
  render();
});

document.getElementById("reset").addEventListener("click", () => {
  count = 0;
  render();
});

render();
"""


def build_template_demo_provider() -> MockProvider:
    """Recorded solution for the ``counter-page`` template.

    Lets the entire evaluation chain — commands, server, Playwright, screenshots — be
    exercised without an API key and without internet access.
    """
    return MockProvider(
        [
            call("list_files", {"path": "."}),
            call("write_file", {"path": "index.html", "content": COUNTER_INDEX}),
            call("write_file", {"path": "counter.js", "content": COUNTER_LOGIC}),
            call("run_command", {"command": "node --check counter.js && echo SYNTAX_OK"}),
            say(
                "Done. index.html holds the readout and both buttons, counter.js keeps the "
                "state and renders it. The page is served with `node serve.js`."
            ),
        ],
        model_id="mock/counter-page",
    )


def build_demo_provider() -> MockProvider:
    """Script of a complete run including one failed attempt.

    The wrong tool name in step 3 is intentional: it demonstrates that a hallucinated tool
    lands in the conversation as feedback and the run continues instead of dying. That is
    exactly what decides later whether weak scout models are usable at all.
    """
    return MockProvider(
        [
            call("list_files", {"path": "."}),
            call("write_file", {"path": "index.html", "content": INDEX_HTML}),
            call("create_file", {"path": "counter.js"}),  # tool does not exist
            call("write_file", {"path": "counter.js", "content": COUNTER_JS}),
            call("run_command", {"command": "node --check counter.js && echo SYNTAX_OK"}),
            call("list_files", {"path": "."}),
            say(
                "Done. index.html includes counter.js, the button increments the counter. "
                "The syntax check with `node --check` passes without errors. "
                "Opening index.html in a browser is enough to see it."
            ),
        ],
        model_id="mock/demo-scripted",
    )
