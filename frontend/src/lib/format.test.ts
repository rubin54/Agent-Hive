import { describe, expect, it } from "vitest";

import { formatContext, formatPricePerMTok } from "./format";

describe("formatPricePerMTok", () => {
  it("distinguishes unknown from free", () => {
    // This distinction must never blur: showing a model on a variable rate as "free" would
    // undermine every cost estimate.
    expect(formatPricePerMTok(null)).toBe("unknown");
    expect(formatPricePerMTok(0)).toBe("free");
  });

  it("keeps enough decimals for very small prices", () => {
    expect(formatPricePerMTok(0.0014)).toBe("$0.0014");
    expect(formatPricePerMTok(0.14)).toBe("$0.140");
    expect(formatPricePerMTok(15)).toBe("$15.00");
  });
});

describe("formatContext", () => {
  it("shortens large context windows readably", () => {
    expect(formatContext(null)).toBe("—");
    expect(formatContext(512)).toBe("512");
    expect(formatContext(128_000)).toBe("128K");
    expect(formatContext(1_000_000)).toBe("1M");
    expect(formatContext(1_048_576)).toBe("1.0M");
  });
});
