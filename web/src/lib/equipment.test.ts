import { describe, expect, it } from "vitest";
import { computeEffectiveLoad, epley1Rm, platesPerSide } from "./equipment";

function base(overrides: Partial<Parameters<typeof computeEffectiveLoad>[0]> = {}) {
  return {
    equipmentType: "barbell" as const,
    loadKg: 60,
    barWeightKg: null,
    pulleyMultiplier: null,
    addedWeightKg: null,
    assistanceKg: null,
    bilateral: true,
    bandTag: null,
    stationConfig: null,
    bodyweightKg: null,
    ...overrides,
  };
}

describe("computeEffectiveLoad", () => {
  it("barbell defaults to a 20kg bar", () => {
    expect(computeEffectiveLoad(base()).effectiveLoadKg).toBe(80);
  });

  it("barbell uses a custom bar weight", () => {
    expect(computeEffectiveLoad(base({ barWeightKg: 15 })).effectiveLoadKg).toBe(75);
  });

  it("smith with unknown bar weight is estimated", () => {
    const r = computeEffectiveLoad(base({ equipmentType: "smith", loadKg: 50, barWeightKg: null }));
    expect(r.isEstimated).toBe(true);
    expect(r.effectiveLoadKg).toBe(60);
  });

  it("smith with a known counterbalanced bar weight", () => {
    const r = computeEffectiveLoad(base({ equipmentType: "smith", loadKg: 50, barWeightKg: 8 }));
    expect(r.isEstimated).toBe(false);
    expect(r.effectiveLoadKg).toBe(58);
  });

  it("dumbbell bilateral doubles per-hand load", () => {
    expect(computeEffectiveLoad(base({ equipmentType: "dumbbell", loadKg: 20, bilateral: true })).effectiveLoadKg).toBe(40);
  });

  it("dumbbell unilateral keeps a single hand's load", () => {
    expect(computeEffectiveLoad(base({ equipmentType: "dumbbell", loadKg: 20, bilateral: false })).effectiveLoadKg).toBe(20);
  });

  it("cable applies the pulley multiplier", () => {
    expect(computeEffectiveLoad(base({ equipmentType: "cable", loadKg: 40, pulleyMultiplier: 0.5 })).effectiveLoadKg).toBe(20);
  });

  it("selectorized machine applies a stack calibration", () => {
    const r = computeEffectiveLoad(
      base({ equipmentType: "machine_selectorized", loadKg: 12, stationConfig: { stack_kg_per_increment: 2.27 } }),
    );
    expect(r.effectiveLoadKg).toBeCloseTo(27.24, 2);
  });

  it("bodyweight requires a known weight", () => {
    const r = computeEffectiveLoad(base({ equipmentType: "bodyweight", loadKg: null, bodyweightKg: null }));
    expect(r.effectiveLoadKg).toBeNull();
    expect(r.isEstimated).toBe(true);
  });

  it("weighted adds to bodyweight", () => {
    const r = computeEffectiveLoad(base({ equipmentType: "weighted", bodyweightKg: 75, addedWeightKg: 10 }));
    expect(r.effectiveLoadKg).toBe(85);
  });

  it("assisted subtracts from bodyweight and never goes negative", () => {
    expect(computeEffectiveLoad(base({ equipmentType: "assisted", bodyweightKg: 75, assistanceKg: 20 })).effectiveLoadKg).toBe(55);
    expect(computeEffectiveLoad(base({ equipmentType: "assisted", bodyweightKg: 75, assistanceKg: 200 })).effectiveLoadKg).toBe(0);
  });

  it("band tag lookup is approximate", () => {
    const r = computeEffectiveLoad(base({ equipmentType: "band", bandTag: "medium" }));
    expect(r.effectiveLoadKg).toBe(20);
    expect(r.isEstimated).toBe(true);
  });
});

describe("platesPerSide", () => {
  it("prefers the fewest large plates", () => {
    const { plates, remainder } = platesPerSide(100); // 50kg/side
    expect(plates).toEqual([25, 25]);
    expect(remainder).toBe(0);
  });

  it("reports a remainder when the target can't be hit exactly", () => {
    const { plates, remainder } = platesPerSide(101, [25, 20, 10]); // 50.5kg/side
    expect(plates.reduce((a, b) => a + b, 0)).toBe(50);
    expect(remainder).toBe(0.5);
  });
});

describe("epley1Rm", () => {
  it("caps the rep count at 10", () => {
    expect(epley1Rm(50, 15)).toBe(epley1Rm(50, 10));
  });

  it("matches the standard formula below the cap", () => {
    expect(epley1Rm(100, 5)).toBeCloseTo(100 * (1 + 5 / 30), 6);
  });
});
