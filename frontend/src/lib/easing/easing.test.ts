import { describe, expect, it } from "vitest";

import {
  EASING_FUNCTIONS,
  easeInOutCubic,
  easeInOutSine,
  easeOutCubic,
  interpolate,
  linear,
  type EasingName,
} from "./easing";

const NAMES: EasingName[] = [
  "linear",
  "easeOutCubic",
  "easeInOutCubic",
  "easeInOutSine",
];

describe("easing functions", () => {
  it.each(NAMES)("%s maps t=0 to 0 and t=1 to 1", (name) => {
    const fn = EASING_FUNCTIONS[name];
    expect(fn(0)).toBeCloseTo(0, 10);
    expect(fn(1)).toBeCloseTo(1, 10);
  });

  it.each(NAMES)("%s clamps inputs outside [0,1]", (name) => {
    const fn = EASING_FUNCTIONS[name];
    expect(fn(-2)).toBeCloseTo(0, 10);
    expect(fn(5)).toBeCloseTo(1, 10);
  });

  it.each(NAMES)("%s treats NaN as 0", (name) => {
    const fn = EASING_FUNCTIONS[name];
    expect(fn(Number.NaN)).toBeCloseTo(0, 10);
  });

  it.each(NAMES)("%s is monotonic non-decreasing on 21 samples", (name) => {
    const fn = EASING_FUNCTIONS[name];
    let last = -Infinity;
    for (let i = 0; i <= 20; i += 1) {
      const value = fn(i / 20);
      expect(value).toBeGreaterThanOrEqual(last - 1e-9);
      last = value;
    }
  });

  it("linear is the identity over [0,1]", () => {
    for (let i = 0; i <= 10; i += 1) {
      expect(linear(i / 10)).toBeCloseTo(i / 10, 10);
    }
  });

  it("easeInOutCubic is symmetric around t=0.5", () => {
    expect(easeInOutCubic(0.5)).toBeCloseTo(0.5, 10);
  });

  it("easeInOutSine is symmetric around t=0.5", () => {
    expect(easeInOutSine(0.5)).toBeCloseTo(0.5, 10);
  });

  it("easeOutCubic decelerates over time (slope first half > slope second half)", () => {
    const slopeFirst = (easeOutCubic(0.5) - easeOutCubic(0)) / 0.5;
    const slopeSecond = (easeOutCubic(1) - easeOutCubic(0.5)) / 0.5;
    expect(slopeFirst).toBeGreaterThan(slopeSecond);
  });
});

describe("interpolate", () => {
  it("returns start at t=0 and end at t=1", () => {
    expect(interpolate(100, 500, 0)).toBeCloseTo(100, 10);
    expect(interpolate(100, 500, 1)).toBeCloseTo(500, 10);
  });

  it("uses linear easing without distortion", () => {
    expect(interpolate(0, 100, 0.5, "linear")).toBeCloseTo(50, 10);
  });

  it("clamps t when outside [0,1]", () => {
    expect(interpolate(0, 100, -1, "linear")).toBeCloseTo(0, 10);
    expect(interpolate(0, 100, 5, "linear")).toBeCloseTo(100, 10);
  });

  it("throws for unknown easing names", () => {
    expect(() =>
      // @ts-expect-error testing runtime validation
      interpolate(0, 1, 0.5, "bouncy"),
    ).toThrow(/Unknown easing/);
  });
});
