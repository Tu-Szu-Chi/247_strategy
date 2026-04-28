import { describe, expect, it } from "vitest";
import {
  deriveBiasValue,
  deriveSignalStateValue,
  resolvePressureSide,
  resolvePressureSlope,
} from "./OptionPowerResearchWorkspace";

describe("option power research signal helpers", () => {
  it("classifies negative-but-rising pressure as easing inside a still-negative zone", () => {
    expect(resolvePressureSide(-15)).toBe(-1);
    expect(resolvePressureSlope(-15, -20)).toBe(1);
    expect(
      deriveBiasValue({
        pressureIndex: -15,
        previousPressureIndex: -20,
        regimeState: -1,
        structureState: -1,
        intensityRatio: 1.1,
      }),
    ).toBe(-1);
  });

  it("blocks signal output when chop score is above the noise threshold", () => {
    expect(
      deriveSignalStateValue({
        biasValue: 1,
        regimeState: 1,
        structureState: 1,
        intensityRatio: 1.2,
        chopScore: 31,
        pressureIndex: 18,
        previousPressureIndex: 12,
        rawPressure: 20,
        adxValue: 24,
        choppinessValue: 40,
        diBiasValue: 12,
        cvdSlopeValue: 3,
        cvdAlignmentValue: 1,
        cvdDivergenceValue: 0,
        rangeStateValue: 1,
        strongPressureThreshold: 8,
        rawPressureThreshold: 8,
        flowThreshold: 1,
      }),
    ).toBe(0);
  });
});
