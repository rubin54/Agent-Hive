# Agent Hive

> A heterogeneous agent swarm whose composition you assemble from the OpenRouter catalog —
> and which can be measured against single models.

**The question:** does a swarm of many cheap models beat a single expensive one at equal
dollar spend?

There is no shortage of leaderboards ranking models individually, and no shortage of
multi-agent frameworks claiming coordination without ever measuring it. This project does both
at once and answers the question with data — even if the answer turns out to be "no".

The full plan with methodology and milestones lives in [PLAN.md](PLAN.md).

---

## Status

| Milestone | Contents | State |
|---|---|---|
| **M0** | Model catalog: OpenRouter sync, role derivation, dashboard with filters | done |
| **M1** | Harness: agent loop, tool registry, budget, providers, Docker sandbox | done |
| **M2** | Versioned task templates, mechanical checks, Playwright, screenshots | done |
| M3–M9 | Journal, sweeps, swarm engine, scoring — see [PLAN.md](PLAN.md) | open |

**Usable without an API key:** the OpenRouter model endpoint is public, a catalog snapshot
ships with the repository, and the example runs use a recorded mock provider.

## The harness in action

```bash
make demo
```

Plays back a full agent run: real Docker container, real files, real commands — only the model
call is recorded. The run deliberately contains a hallucinated tool name to show that this
becomes feedback rather than a crash.

The complete evaluation chain on a real task:

```bash
backend/.venv/Scripts/python -m hive.cli run --template minecraft-clone --provider mock
```

Installs three.js and Vite inside the container, builds, starts the preview server, checks in a
browser and stores screenshots of the rendered voxel scene — all without an API key.

Against a real model with your own key:

```bash
HIVE_OPENROUTER_API_KEY=sk-or-... backend/.venv/Scripts/python -m hive.cli run --template minecraft-clone --model anthropic/claude-haiku-4.5
```

## Quickstart

```bash
make install
```

Backend and frontend in two terminals:

```bash
make backend
```

```bash
make frontend
```

Then open [http://localhost:5173](http://localhost:5173). Without `make`:

```bash
python -m venv backend/.venv && backend/.venv/Scripts/python -m pip install -e "backend[dev]" && npm install --prefix frontend
```

Fetch the current catalog state (this does not overwrite the bundled one, it adds a new
snapshot):

```bash
make sync
```

If port 8000 or 5173 is taken: create `frontend/.env.local` with
`VITE_API_TARGET=http://127.0.0.1:8010` and start the backend with `API_PORT=8010 make backend`.

## Roles in the swarm

The division of labour follows no design whim but a real capability boundary: many cheap models
cannot call tools. Rather than excluding them, they plan as scouts in text — workers do the
execution with tools.

| Role | Requirement | Task |
|---|---|---|
| **Scout** | none | Explore the solution space, propose candidates |
| **Worker** | tool calling | Elaborate candidates in the sandbox |
| **Inspector** | image understanding | Verify results and vote |
| **Queen** | tool calling | Synthesis, tie-breaking, termination |

The dashboard derives eligibility from `supported_parameters` and
`architecture.input_modalities`. Models that cannot run a full swarm are shown **dimmed with a
reason** rather than filtered out silently.

## Task templates

A template is the object under measurement: prompt, starter files, budget, checks and scoring
rubric in one versioned YAML. It is **immutable** — a change produces a new version and older
runs keep their reference version. Every loaded template also carries a content hash so that
editing the file without bumping the version becomes visible.

```bash
backend/.venv/Scripts/python -m hive.cli template list
```

Everything that influences the comparison — prompt, budget, network mode, image — comes from
the template and not from the command line. Otherwise the control variable would be adjustable
by accident.

Three check kinds: `command` (build, tests, linter), `serve` (starts a server and waits for
readiness) and `playwright` (browser behaviour and screenshots) — each with `required`, so a
finding does not necessarily abort the chain. After a blocking failure the remaining checks are
skipped rather than run pointlessly.

## Design decisions visible in the code

**Prices are `Decimal`, never `float`.** OpenRouter returns amounts like `0.00000014` per
token. Across tens of thousands of calls, binary rounding errors accumulate into visible drift.
The conversion to `float` happens for display only (`query.py`).

**Unknown price ≠ free.** OpenRouter uses `-1` for variable rates. Those models drop out of
every price filter instead of slipping through as "free" and undermining cost estimation later.

**Snapshots are immutable.** Every sync stores a new, timestamped state including the **raw
payload**. A benchmark result must be traceable to the model and price state it was produced
under, and older snapshots stay analysable when new fields appear.

**Pydantic is the single schema source.** The TypeScript types are generated from FastAPI's
OpenAPI schema via `make types`. With a split Python/TS stack, schema drift is the default
failure mode; CI verifies the schema can be regenerated reproducibly.

**Tool failures are feedback, not crashes.** A hallucinated tool name returns the list of
available tools, invalid arguments return the validation error, broken JSON in the arguments
becomes empty arguments. That is the only way the loop survives weak models — and those are
meant to be the majority in a swarm. A rip cord after five iterations without a single
successful tool call stops a model from getting stuck on the same error.

**The agent loop is the control variable.** Every model, and later every swarm role, runs
through exactly the same code. Tools run sequentially on purpose: they share one file tree, and
parallel writes would make results depend on invocation order.

**Budgets are hard limits.** Iterations, tokens, wall clock and cost are enforced, not
suggested. Model-versus-model is capped by iterations and tokens — a dollar cap would give
cheap models more attempts. Only for swarm-versus-solo is dollar parity the right control.

## Sandbox

Models write and **execute** code, so isolation is mandatory:

- one container per run, non-root user, `cap_drop: ALL`, `no-new-privileges`
- no host mounts — the workspace only leaves the container through explicit reads
- limits on memory, CPU, processes and per-command runtime (`timeout` runs *inside* the
  container and really terminates the process)
- capped tool output so a build log cannot blow up the context window
- path normalisation with `PurePosixPath`: `Path.resolve()` on a Windows host would resolve
  against the host filesystem and defeat the escape guard

These promises are tested, not asserted in prose — `tests/test_sandbox.py` verifies user,
network, privilege escalation, time limit and output capping inside a real container.

### Network modes

| Mode | Meaning |
|---|---|
| `none` | No network interface. Strongest isolation, but **cannot** be extended later |
| `internal` | Dedicated Docker network with `internal=True`: containers reach each other, not the internet |
| `bridge` | Open network |

`internal` is the interesting case: the checker container reaches the application, the
application does not reach the internet. Exactly that combination allows browser checks without
granting the subject network access. For `npm install`, `bridge` is attached **selectively** and
revoked afterwards.

Docker does not allow attaching a container started with `network_mode=none` to a network
later. Templates with network needs must therefore request `internal` — the template schema
checks this on load, not after the expensive agent phase.

**Known gap:** the egress proxy with an allowlist for package registries planned in
[PLAN.md](PLAN.md) is still missing. Selective access is tighter than "network on for the whole
run", but during an `npm install` the container has the open internet available.

### A lesson from building the checks

The first Playwright check for the 3D scene read pixels *inside the page*
(`context.drawImage(canvas, …)`). With WebGL that returns an empty buffer once the browser
discards the drawing buffer after compositing — the default. The check failed a perfectly
correct voxel scene. The alternative would have been to prescribe `preserveDrawingBuffer: true`
to the model — precisely the implementation coupling this benchmark aims to avoid. Playwright
screenshots are used now, which go through the compositor. A test pins the mistake down so it
cannot return.

## Development

```bash
make check
```

Runs lint, typecheck and tests for both sides: `ruff`, `mypy --strict`, `pytest` (121 tests),
`tsc --noEmit`, `vitest`. The fast part runs **without network and without a key** — HTTP is
intercepted with `respx`, the catalog comes from the fixture. Container tests skip themselves
when no Docker daemon is reachable.

```
backend/hive/
  catalog/     OpenRouter sync, capability derivation, snapshots, filtering
  harness/     agent loop, tool registry, budget, events, providers, runner
  sandbox/     Docker container, network modes, workspace tools
  templates/   versioned task definitions, loading and validation
  checks/      command, serve and Playwright checks
  api/         FastAPI REST endpoints
  cli.py       hive catalog | template | run | openapi
docker/        sandbox image and checker image
templates/     counter-page, minecraft-clone
frontend/src/
  api/         client and types
  features/catalog/   tile grid, filters, detail panel
  lib/         display formatting
```

## License

MIT
