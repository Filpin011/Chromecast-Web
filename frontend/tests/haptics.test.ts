import { afterEach, describe, expect, it, vi } from "vitest";
import { haptic } from "@/lib/haptics";

function stubNavigator(userActivation?: { hasBeenActive: boolean }) {
  const vibrate = vi.fn(() => true);
  vi.stubGlobal("navigator", { vibrate, ...(userActivation ? { userActivation } : {}) });
  return vibrate;
}

afterEach(() => vi.unstubAllGlobals());

describe("haptic", () => {
  it("does not call vibrate before the first user gesture (Chromium blocks it and logs an error)", () => {
    const vibrate = stubNavigator({ hasBeenActive: false });
    haptic([10, 40, 10]);
    expect(vibrate).not.toHaveBeenCalled();
  });

  it("vibrates once the user has interacted", () => {
    const vibrate = stubNavigator({ hasBeenActive: true });
    haptic(6);
    expect(vibrate).toHaveBeenCalledWith(6);
  });

  it("vibrates where userActivation is not implemented", () => {
    const vibrate = stubNavigator();
    haptic();
    expect(vibrate).toHaveBeenCalledWith(8);
  });

  it("is a no-op without the Vibration API", () => {
    vi.stubGlobal("navigator", {});
    expect(() => haptic()).not.toThrow();
  });
});
