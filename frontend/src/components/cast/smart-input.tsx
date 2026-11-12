"use client";

import { ArrowRight, ClipboardPaste, Link2, ListVideo, Loader2, MonitorPlay, Radio, X, type LucideIcon } from "lucide-react";
import { useRef, useSyncExternalStore, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { detectInput, INPUT_KIND_LABEL, type InputKind } from "@/lib/input-detect";
import { haptic } from "@/lib/haptics";
import { cn } from "@/lib/utils";

const KIND_ICON: Partial<Record<InputKind, LucideIcon>> = {
  url: Link2,
  m3u: ListVideo,
  youtube: MonitorPlay,
  stream: Radio,
};

const noopSubscribe = () => () => {};

/**
 * `navigator.clipboard` only exists in a secure context (https / localhost). The app is served
 * over plain HTTP on the LAN, so on a phone the API is usually missing: then the "Incolla" button
 * is hidden and the user pastes with a long-press in the field. Server snapshot is `false` so the
 * prerendered HTML never shows a button that would not work.
 */
export function canReadClipboard(): boolean {
  if (typeof window === "undefined" || !window.isSecureContext) return false;
  return typeof navigator.clipboard?.readText === "function";
}

function useClipboardAvailable() {
  return useSyncExternalStore(noopSubscribe, canReadClipboard, () => false);
}

export type InputSource = "type" | "paste";

export interface SmartInputProps {
  value: string;
  /** `source` is "paste" for a clipboard paste (complete input: can be resolved at once). */
  onChange: (value: string, source: InputSource) => void;
  /** Called on Enter / arrow button with the trimmed value. */
  onSubmit: (value: string) => void;
  loading?: boolean;
  autoFocus?: boolean;
  /** Shown under the field, e.g. "press Enter to analyse". */
  hint?: string | null;
}

/** One input for everything: URL, M3U link, YouTube, raw #EXTM3U text. */
export function SmartInput({ value, onChange, onSubmit, loading, autoFocus, hint }: SmartInputProps) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const pasting = useRef(false);
  const detected = detectInput(value);
  const Icon = KIND_ICON[detected.kind];
  const canSubmit = detected.kind !== "empty" && detected.kind !== "invalid";
  const clipboard = useClipboardAvailable();

  const paste = async () => {
    haptic();
    try {
      const text = await navigator.clipboard.readText();
      if (!text.trim()) {
        toast("Gli appunti sono vuoti");
        return;
      }
      onChange(text.trim(), "paste");
      inputRef.current?.focus();
    } catch {
      toast.error("Accesso agli appunti negato", { description: "Incolla manualmente nel campo." });
      inputRef.current?.focus();
    }
  };

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (canSubmit) onSubmit(value.trim());
  };

  return (
    <form onSubmit={submit} className="group relative">
      <div
        className={cn(
          "flex items-start gap-2 rounded-2xl border bg-card p-2 shadow-sm transition-all",
          "focus-within:border-primary/60 focus-within:ring-4 focus-within:ring-primary/15",
        )}
      >
        <textarea
          ref={inputRef}
          aria-label="URL, playlist o link video"
          value={value}
          autoFocus={autoFocus}
          rows={1}
          placeholder="Incolla un link: stream, pagina web, YouTube, M3U…"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          inputMode="url"
          enterKeyHint="go"
          onPaste={() => {
            pasting.current = true;
          }}
          onChange={(e) => {
            const source: InputSource = pasting.current ? "paste" : "type";
            pasting.current = false;
            onChange(e.target.value, source);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          className="field-sizing-content max-h-40 min-h-11 flex-1 resize-none bg-transparent px-2 py-2.5 text-base leading-6 outline-none placeholder:text-muted-foreground"
        />
        {value ? (
          <Button type="button" variant="ghost" size="icon" aria-label="Cancella" onClick={() => onChange("", "type")}>
            <X className="size-4" />
          </Button>
        ) : clipboard ? (
          <Button type="button" variant="secondary" onClick={paste} className="gap-1.5 rounded-xl">
            <ClipboardPaste className="size-4" />
            Incolla
          </Button>
        ) : null}
        {value && (
          <Button type="submit" size="icon" aria-label="Analizza" disabled={!canSubmit || loading} className="rounded-xl">
            {loading ? <Loader2 className="size-4 animate-spin" /> : <ArrowRight className="size-4" />}
          </Button>
        )}
      </div>
      <div className="mt-2 flex h-5 items-center gap-1.5 px-2 text-xs">
        {detected.kind === "empty" && !clipboard && (
          <span data-testid="paste-hint" className="truncate text-muted-foreground">
            Tieni premuto nel campo e scegli «Incolla»
          </span>
        )}
        {detected.kind !== "empty" && (
          <span
            data-testid="input-kind"
            className={cn(
              "inline-flex items-center gap-1 font-medium",
              detected.kind === "invalid" ? "text-destructive" : "text-primary",
            )}
          >
            {Icon && <Icon className="size-3.5" />}
            {INPUT_KIND_LABEL[detected.kind]}
          </span>
        )}
        {hint && detected.kind !== "empty" && detected.kind !== "invalid" && (
          <span data-testid="input-hint" className="truncate text-muted-foreground">
            · {hint}
          </span>
        )}
      </div>
    </form>
  );
}
