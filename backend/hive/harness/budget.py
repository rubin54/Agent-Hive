"""Budget-Durchsetzung.

Harte Grenze, nicht Empfehlung: Ist ein Limit erreicht, endet der Lauf. Ohne das verbrennt
ein zielgetriebener Loop beliebig viel Geld, und genau daran scheitern die meisten
Eigenbau-Harnesse sichtbar.

Kosten werden ausschließlich in ``Decimal`` gerechnet. Bei Preisen um 1e-7 pro Token summieren
sich float-Binärfehler über zehntausende Aufrufe zu sichtbaren Abweichungen — und die
Kostenachse ist in diesem Projekt eine Messgröße, kein Nebenwert.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from ..catalog.models import Pricing
from .messages import Usage


class LimitKind(StrEnum):
    ITERATIONS = "iterations"
    TOKENS = "tokens"
    WALL_CLOCK = "wall_clock"
    COST = "cost"


class BudgetExceeded(Exception):
    """Ein hartes Limit wurde erreicht."""

    def __init__(self, kind: LimitKind, detail: str) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True, slots=True)
class BudgetLimits:
    """Obergrenzen eines Laufs.

    ``max_cost_usd`` ist bewusst die Notbremse und nicht die Vergleichsgröße: Für
    Modell-gegen-Modell wird über Iterationen und Tokens gedeckelt, damit ein billiges
    Modell nicht einfach mehr Versuche bekommt. Erst beim Vergleich Schwarm gegen Solo
    (ab M5) ist Dollar-Parität die richtige Kontrollvariable.
    """

    max_iterations: int = 20
    max_tokens: int | None = 200_000
    max_wall_clock_seconds: float | None = 900.0
    max_cost_usd: Decimal | None = Decimal("5.00")


@dataclass(slots=True)
class BudgetSnapshot:
    iterations: int
    usage: Usage
    cost_usd: Decimal
    elapsed_seconds: float

    def format(self) -> str:
        return (
            f"{self.iterations} Iterationen · {self.usage.total_tokens:,} Token · "
            f"${self.cost_usd:.4f} · {self.elapsed_seconds:.1f}s"
        )


@dataclass(slots=True)
class BudgetTracker:
    limits: BudgetLimits
    pricing: Pricing | None = None
    iterations: int = 0
    usage: Usage = field(default_factory=Usage)
    cost_usd: Decimal = Decimal(0)
    _started_at: float = field(default_factory=time.monotonic)

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._started_at

    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            iterations=self.iterations,
            usage=self.usage,
            cost_usd=self.cost_usd,
            elapsed_seconds=self.elapsed_seconds,
        )

    def cost_of(self, usage: Usage) -> Decimal:
        """Kosten eines Aufrufs aus den Katalogpreisen.

        Ohne bekannte Preise bleibt die Kostenachse bei null — das ist ehrlicher als eine
        geschätzte Zahl, und der Katalog markiert solche Modelle bereits als preislos.
        """
        if self.pricing is None:
            return Decimal(0)
        prompt_price = self.pricing.prompt or Decimal(0)
        completion_price = self.pricing.completion or Decimal(0)
        # Reasoning-Token werden von den Anbietern wie Ausgabe-Token abgerechnet.
        completion_tokens = usage.completion_tokens + usage.reasoning_tokens
        return prompt_price * usage.prompt_tokens + completion_price * completion_tokens

    def record(self, usage: Usage, *, reported_cost_usd: Decimal | None = None) -> Decimal:
        """Verbucht einen Modellaufruf und gibt dessen Kosten zurück."""
        self.usage = self.usage + usage
        # Meldet der Provider echte Kosten, gewinnen diese gegen die eigene Rechnung —
        # sie berücksichtigen Rabatte und Cache-Treffer, die der Katalogpreis nicht kennt.
        cost = reported_cost_usd if reported_cost_usd is not None else self.cost_of(usage)
        self.cost_usd += cost
        return cost

    def start_iteration(self) -> None:
        """Prüft alle Limits und zählt die Iteration hoch. Wirft bei Überschreitung."""
        if self.iterations >= self.limits.max_iterations:
            raise BudgetExceeded(
                LimitKind.ITERATIONS,
                f"Iterationslimit erreicht ({self.limits.max_iterations})",
            )
        if self.limits.max_tokens is not None and self.usage.total_tokens >= self.limits.max_tokens:
            raise BudgetExceeded(
                LimitKind.TOKENS,
                f"Tokenlimit erreicht ({self.usage.total_tokens:,} / {self.limits.max_tokens:,})",
            )
        if (
            self.limits.max_wall_clock_seconds is not None
            and self.elapsed_seconds >= self.limits.max_wall_clock_seconds
        ):
            raise BudgetExceeded(
                LimitKind.WALL_CLOCK,
                f"Zeitlimit erreicht ({self.elapsed_seconds:.0f}s)",
            )
        if self.limits.max_cost_usd is not None and self.cost_usd >= self.limits.max_cost_usd:
            raise BudgetExceeded(
                LimitKind.COST,
                f"Kostenlimit erreicht (${self.cost_usd:.4f} / ${self.limits.max_cost_usd})",
            )
        self.iterations += 1


def estimate_cost(
    pricing: Pricing, *, prompt_tokens: int, completion_tokens: int
) -> Decimal | None:
    """Vorabschätzung für die Sweep-Kostenvorschau (ab M4)."""
    if pricing.prompt is None or pricing.completion is None:
        return None
    return pricing.prompt * prompt_tokens + pricing.completion * completion_tokens
