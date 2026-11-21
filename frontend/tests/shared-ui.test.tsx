import { fireEvent, render, screen } from "@testing-library/react";
import { Star } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
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
