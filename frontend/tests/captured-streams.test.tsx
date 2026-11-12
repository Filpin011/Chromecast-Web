import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CapturedList } from "@/components/browser/captured-list";
import { KeyboardBar } from "@/components/browser/keyboard-bar";
import { StreamPanel, type StreamPanelProps } from "@/components/browser/stream-panel";
import { rankCaptured } from "@/lib/captured";
import { makeCaptured } from "./fixtures";

const best = makeCaptured({ id: "hd", height: 1080, score: 20, title: "Finale in diretta" });
const other = makeCaptured({ id: "mp4", kind: "progressive", is_master: null, is_live: false, height: 480, score: 1, title: null });

function renderPanel(over: Partial<StreamPanelProps> = {}) {
  const props: StreamPanelProps = {
    streams: rankCaptured([other, best]),
    selectedId: null,
    onSelect: vi.fn(),
    snapshots: {},
    pageTitle: "Pagina sport",
    onDismiss: vi.fn(),
    onCast: vi.fn(),
    onQueue: vi.fn(),
    onPlay: vi.fn(),
    onBookmark: vi.fn(),
    ...over,
  };
  render(<StreamPanel {...props} />);
  return props;
}

describe("StreamPanel", () => {
  it("shows the best stream with title, quality and live badge", () => {
    renderPanel();
    expect(screen.getByTestId("stream-title")).toHaveTextContent("Finale in diretta");
    expect(screen.getAllByText("1080p FHD").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Live").length).toBeGreaterThan(0);
    expect(screen.getByTestId("kind-badge")).toHaveTextContent("HLS master");
  });

  it("fires Cast / Queue / Play / Bookmark with the selected stream", () => {
    const p = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Cast" }));
    fireEvent.click(screen.getByRole("button", { name: "Coda" }));
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    fireEvent.click(screen.getByRole("button", { name: "Salva" }));
    expect(p.onCast).toHaveBeenCalledWith(best);
    expect(p.onQueue).toHaveBeenCalledWith(best);
    expect(p.onPlay).toHaveBeenCalledWith(best);
    expect(p.onBookmark).toHaveBeenCalledWith(best);
  });

  it("switches between streams and falls back to the page title", () => {
    const p = renderPanel({ selectedId: "mp4" });
    expect(screen.getByTestId("stream-title")).toHaveTextContent("Pagina sport");
    const tabs = screen.getAllByRole("tab");
    expect(tabs).toHaveLength(2);
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
    fireEvent.click(tabs[0]);
    expect(p.onSelect).toHaveBeenCalledWith("hd");
  });

  it("can be dismissed", () => {
    const p = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Chiudi pannello" }));
    expect(p.onDismiss).toHaveBeenCalled();
  });
});

describe("CapturedList", () => {
  it("shows a listening state when empty", () => {
    render(<CapturedList streams={[]} onPreview={vi.fn()} onCast={vi.fn()} />);
    expect(screen.getByText(/In ascolto del traffico/)).toBeInTheDocument();
  });

  it("lists streams with kind badges and actions", () => {
    const onCast = vi.fn();
    const onPreview = vi.fn();
    render(<CapturedList streams={[best, other]} onPreview={onPreview} onCast={onCast} />);
    const badges = screen.getAllByTestId("kind-badge").map((b) => b.textContent);
    expect(badges).toEqual(["HLS master", "MP4"]);
    fireEvent.click(screen.getAllByRole("button", { name: /^Trasmetti/ })[1]);
    fireEvent.click(screen.getAllByRole("button", { name: /^Anteprima/ })[0]);
    expect(onCast).toHaveBeenCalledWith(other);
    expect(onPreview).toHaveBeenCalledWith(best);
  });

  it("also offers Queue and Bookmark (tablet/desktop side list and the mobile drawer)", () => {
    const onQueue = vi.fn();
    const onBookmark = vi.fn();
    render(<CapturedList streams={[best, other]} onPreview={vi.fn()} onCast={vi.fn()} onQueue={onQueue} onBookmark={onBookmark} />);
    fireEvent.click(screen.getAllByRole("button", { name: /^Aggiungi alla coda/ })[0]);
    fireEvent.click(screen.getAllByRole("button", { name: /^Aggiungi ai preferiti/ })[1]);
    expect(onQueue).toHaveBeenCalledWith(best);
    expect(onBookmark).toHaveBeenCalledWith(other);
  });
});

describe("KeyboardBar", () => {
  it("sends text + Enter on submit and Backspace on demand", () => {
    const send = vi.fn().mockReturnValue(true);
    render(<KeyboardBar send={send} />);
    fireEvent.change(screen.getByLabelText("Testo da inviare alla pagina"), { target: { value: "ciao" } });
    fireEvent.click(screen.getByRole("button", { name: "Invio" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancella carattere" }));
    expect(send.mock.calls.map((c) => c[0])).toEqual([
      { type: "text", text: "ciao" },
      { type: "key", key: "Enter" },
      { type: "key", key: "Backspace" },
    ]);
  });
});
