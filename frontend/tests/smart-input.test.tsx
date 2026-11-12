import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("sonner", () => {
  const toast = Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() });
  return { toast };
});

import { toast } from "sonner";
import { SmartInput } from "@/components/cast/smart-input";
import { autoResolvesWhileTyping, detectInput } from "@/lib/input-detect";

function Harness({ onSubmit }: { onSubmit: (v: string) => void }) {
  const [v, setV] = useState("");
  return <SmartInput value={v} onChange={(x) => setV(x)} onSubmit={onSubmit} />;
}

function setClipboard(secure: boolean, readText?: () => Promise<string>) {
  Object.defineProperty(window, "isSecureContext", { value: secure, configurable: true });
  Object.defineProperty(navigator, "clipboard", {
    value: readText ? { readText } : undefined,
    configurable: true,
  });
}

afterEach(() => setClipboard(false));

describe("SmartInput", () => {
  it("detects the kind of input while typing", () => {
    render(<Harness onSubmit={vi.fn()} />);
    const box = screen.getByLabelText("URL, playlist o link video");
    fireEvent.change(box, { target: { value: "https://youtu.be/dQw4w9WgXcQ" } });
    expect(screen.getByTestId("input-kind")).toHaveTextContent("YouTube");
    fireEvent.change(box, { target: { value: "http://x/live.m3u8" } });
    expect(screen.getByTestId("input-kind")).toHaveTextContent("Stream diretto");
    fireEvent.change(box, { target: { value: "boh" } });
    expect(screen.getByTestId("input-kind")).toHaveTextContent("Non riconosciuto");
    expect(screen.getByRole("button", { name: "Analizza" })).toBeDisabled();
  });

  it("submits on Enter with the trimmed value", () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);
    const box = screen.getByLabelText("URL, playlist o link video");
    fireEvent.change(box, { target: { value: "  https://a.b/c.m3u  " } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledWith("https://a.b/c.m3u");
  });

  it("does not submit invalid input", () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);
    const box = screen.getByLabelText("URL, playlist o link video");
    fireEvent.change(box, { target: { value: "not a url" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("pastes from the clipboard and can clear", async () => {
    setClipboard(true, vi.fn().mockResolvedValue(" https://www.youtube.com/watch?v=1 "));
    render(<Harness onSubmit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Incolla/ }));
    const box = screen.getByLabelText<HTMLTextAreaElement>("URL, playlist o link video");
    await waitFor(() => expect(box.value).toBe("https://www.youtube.com/watch?v=1"));
    fireEvent.click(screen.getByRole("button", { name: "Cancella" }));
    expect(box.value).toBe("");
  });

  it("explains when clipboard access is denied", async () => {
    setClipboard(true, vi.fn().mockRejectedValue(new Error("denied")));
    render(<Harness onSubmit={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Incolla/ }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("hides the paste button on plain-HTTP LAN origins (no Clipboard API) and hints a long-press", () => {
    // http://192.168.x.y:8000 is not a secure context: navigator.clipboard is undefined there
    setClipboard(false);
    render(<Harness onSubmit={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Incolla/ })).not.toBeInTheDocument();
    expect(screen.getByTestId("paste-hint")).toHaveTextContent("Tieni premuto");
  });

  it("hides the paste button when the API is missing even in a secure context", () => {
    setClipboard(true);
    render(<Harness onSubmit={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Incolla/ })).not.toBeInTheDocument();
  });
});

describe("auto-resolve policy", () => {
  it("auto-resolves only cheap inputs while typing", () => {
    expect(autoResolvesWhileTyping(detectInput("http://x/live.m3u8"))).toBe(true);
    expect(autoResolvesWhileTyping(detectInput("https://a.b/list.m3u"))).toBe(true);
    // half-typed page / yt-dlp URLs would start an expensive server-side resolve
    expect(autoResolvesWhileTyping(detectInput("https://site.com/pag"))).toBe(false);
    expect(autoResolvesWhileTyping(detectInput("https://youtu.be/dQw4"))).toBe(false);
  });

  it("reports pastes separately from typing", () => {
    const onChange = vi.fn();
    render(<SmartInput value="" onChange={onChange} onSubmit={vi.fn()} />);
    const box = screen.getByLabelText("URL, playlist o link video");
    fireEvent.change(box, { target: { value: "h" } });
    expect(onChange).toHaveBeenLastCalledWith("h", "type");
    fireEvent.paste(box);
    fireEvent.change(box, { target: { value: "https://site.com/page" } });
    expect(onChange).toHaveBeenLastCalledWith("https://site.com/page", "paste");
  });
});
