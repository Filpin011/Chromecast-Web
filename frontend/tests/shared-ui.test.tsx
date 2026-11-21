import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AlertTriangle, Star, Trash2 } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { ChipGroup } from "@/components/common/chip-group";
import { ListRow } from "@/components/common/list-row";
import { MediaOverlay } from "@/components/common/media-overlay";
import { SegmentedControl } from "@/components/common/segmented-control";

describe("SegmentedControl", () => {
  const options = [
    { value: "a", label: "Alpha", icon: Star, count: 3 },
    { value: "b", label: "Beta" },
  ] as const;

  it("is a radiogroup by default and reports the picked value", () => {
    const onChange = vi.fn();
    render(<SegmentedControl aria-label="Pick" options={options} value="a" onChange={onChange} />);
    expect(screen.getByRole("radiogroup", { name: "Pick" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Alpha/ })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "Beta" })).toHaveAttribute("aria-checked", "false");
    fireEvent.click(screen.getByRole("radio", { name: "Beta" }));
    expect(onChange).toHaveBeenCalledWith("b");
  });

  it("renders tabs with their count", () => {
    render(<SegmentedControl kind="tab" options={options} value="b" onChange={() => {}} />);
    expect(screen.getByRole("tablist")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Alpha\s*3/ })).toHaveAttribute("aria-selected", "false");
    expect(screen.getByRole("tab", { name: "Beta" })).toHaveAttribute("aria-selected", "true");
  });

  it("selects nothing while the value is unknown and honours disabled", () => {
    render(<SegmentedControl options={options} value={null} onChange={() => {}} disabled />);
    for (const r of screen.getAllByRole("radio")) {
      expect(r).toHaveAttribute("aria-checked", "false");
      expect(r).toBeDisabled();
    }
  });
});

describe("touch targets", () => {
  const css = readFileSync(join(__dirname, "..", "src", "app", "globals.css"), "utf8");

  it("defines a 44px invisible hit area", () => {
    const rule = /@utility hit-area-44 \{[\s\S]*?\n\}/.exec(css)?.[0] ?? "";
    expect(rule).toContain("width: max(100%, 44px)");
    expect(rule).toContain("height: max(100%, 44px)");
  });

  it("gives every segment and chip a 44px hit area, with room for it in the group", () => {
    for (const size of ["sm", "default", "lg"] as const) {
      const { unmount } = render(
        <SegmentedControl size={size} options={[{ value: "a", label: "A" }, { value: "b", label: "B" }]} value="a" onChange={() => {}} />,
      );
      for (const r of screen.getAllByRole("radio")) expect(r).toHaveClass("hit-area-44");
      // the group's 4px padding holds the extension of a 36px / 40px segment
      expect(screen.getByRole("radiogroup")).toHaveClass("p-1");
      unmount();
    }
    render(<ChipGroup aria-label="Groups" options={[{ value: "x", label: "X" }]} value="x" onChange={() => {}} />);
    expect(screen.getByRole("radio", { name: "X" })).toHaveClass("hit-area-44", "h-9");
    expect(screen.getByRole("radiogroup", { name: "Groups" })).toHaveClass("py-1");
  });
});

describe("MediaOverlay", () => {
  it("shows a message and runs its action", () => {
    const onClick = vi.fn();
    render(<MediaOverlay role="alert" tone="solid" size="sm" icon={AlertTriangle} message="Broken" action={{ label: "Retry", onClick }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Broken");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onClick).toHaveBeenCalled();
  });

  it("lets taps through while only loading", () => {
    const { container } = render(<MediaOverlay spinner />);
    expect(container.firstElementChild).toHaveClass("pointer-events-none");
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("ListRow", () => {
  it("taps its main area and opens the menu with its actions", async () => {
    const onClick = vi.fn();
    const onDelete = vi.fn();
    render(
      <ListRow
        leading={<span />}
        title="Item"
        subtitle="Sub"
        label="Open Item"
        onClick={onClick}
        menuLabel="Actions for Item"
        actions={[{ label: "Delete", icon: Trash2, onClick: onDelete, destructive: true }]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Open Item" }));
    expect(onClick).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Actions for Item" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    await waitFor(() => expect(onDelete).toHaveBeenCalled());
  });

  it("has no menu button without a menu label", () => {
    render(<ListRow leading={null} title="Item" label="Open Item" onClick={() => {}} />);
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });
});
