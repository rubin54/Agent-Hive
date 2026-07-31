import { describe, expect, it } from "vitest";

import { formatContext, formatPricePerMTok } from "./format";

describe("formatPricePerMTok", () => {
  it("unterscheidet unbekannt von gratis", () => {
    // Diese Unterscheidung darf nie verwischen: ein Modell mit variablem Tarif
    // als "gratis" anzuzeigen würde jede Kostenschätzung unterlaufen.
    expect(formatPricePerMTok(null)).toBe("unbekannt");
    expect(formatPricePerMTok(0)).toBe("gratis");
  });

  it("zeigt bei sehr kleinen Preisen genug Nachkommastellen", () => {
    expect(formatPricePerMTok(0.0014)).toBe("$0.0014");
    expect(formatPricePerMTok(0.14)).toBe("$0.140");
    expect(formatPricePerMTok(15)).toBe("$15.00");
  });
});

describe("formatContext", () => {
  it("kürzt große Kontextfenster lesbar", () => {
    expect(formatContext(null)).toBe("—");
    expect(formatContext(512)).toBe("512");
    expect(formatContext(128_000)).toBe("128K");
    expect(formatContext(1_000_000)).toBe("1M");
    expect(formatContext(1_048_576)).toBe("1.0M");
  });
});
