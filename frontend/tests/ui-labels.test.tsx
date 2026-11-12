/** Accessible labels of the shared UI primitives (dialog/sheet close, toaster) follow the app language. */
import { act, render, screen } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, describe, expect, it } from "vitest";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Toaster } from "@/components/ui/sonner";
import { useLocaleStore, type Locale } from "@/i18n";

const setLocale = (locale: Locale) => act(() => useLocaleStore.setState({ locale, hydrated: true }));

afterEach(() => {
  act(() => toast.dismiss());
  useLocaleStore.setState({ locale: "en", hydrated: false });
});

describe.each([
  ["en", "Close", "Notifications", "Close notification"],
  ["it", "Chiudi", "Notifiche", "Chiudi notifica"],
] as const)("UI primitive labels in %s", (locale, close, region, closeToast) => {
  it("labels the default dialog close button", () => {
    setLocale(locale);
    render(
      <Dialog open>
        <DialogContent>
          <DialogTitle>T</DialogTitle>
        </DialogContent>
      </Dialog>,
    );
    expect(screen.getByRole("button", { name: close })).toBeInTheDocument();
  });

  it("labels the default sheet close button", () => {
    setLocale(locale);
    render(
      <Sheet open>
        <SheetContent>
          <SheetTitle>T</SheetTitle>
        </SheetContent>
      </Sheet>,
    );
    expect(screen.getByRole("button", { name: close })).toBeInTheDocument();
  });

  it("labels the toast region and each toast's close button", async () => {
    setLocale(locale);
    const { container } = render(<Toaster closeButton />);
    const section = container.querySelector("section");
    expect(section?.getAttribute("aria-label")).toMatch(new RegExp(`^${region}\\b`));
    act(() => {
      toast("hello");
    });
    expect(await screen.findByRole("button", { name: closeToast })).toBeInTheDocument();
  });
});
