import { describe, expect, it } from "vitest";
import { OPTION_POWER_RESEARCH_SERIES } from "./OptionPowerResearchWorkspace";

describe("option power research series contract", () => {
  it("requests backend-derived decision series instead of deriving them in the UI", () => {
    expect(OPTION_POWER_RESEARCH_SERIES).toEqual(
      expect.arrayContaining([
        "trend_quality_score",
        "trend_bias_state",
        "flow_impulse_score",
        "flow_state",
        "range_state",
        "mtx_up_50_in_10m_probability",
        "mtx_down_50_in_10m_probability",
        "mtx_expected_close_delta_10m",
      ]),
    );
  });
});
