"use client";

import { CornerDownLeft, Delete, Send } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import type { BrowserClientMsg } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/** Text bar that drives the remote page's keyboard (opens the phone's virtual keyboard). */
export function KeyboardBar({
  send,
  className,
  autoFocus,
}: {
  send: (msg: BrowserClientMsg) => boolean;
  className?: string;
  autoFocus?: boolean;
}) {
  const [text, setText] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text) send({ type: "text", text });
    send({ type: "key", key: "Enter" });
    setText("");
  };
  return (
    <form onSubmit={submit} className={cn("flex items-center gap-1.5 border-t bg-background px-2 py-1.5", className)}>
      <Button type="button" variant="ghost" size="icon" aria-label="Cancella carattere" onClick={() => send({ type: "key", key: "Backspace" })}>
        <Delete className="size-4" />
      </Button>
      <input
        aria-label="Testo da inviare alla pagina"
        value={text}
        autoFocus={autoFocus}
        onChange={(e) => setText(e.target.value)}
        placeholder="Scrivi nella pagina…"
        autoCapitalize="off"
        autoCorrect="off"
        enterKeyHint="send"
        className="h-10 min-w-0 flex-1 rounded-full bg-muted px-4 text-base outline-none focus:ring-2 focus:ring-primary/40"
      />
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label="Scrivi senza invio"
        disabled={!text}
        onClick={() => {
          send({ type: "text", text });
          setText("");
        }}
      >
        <Send className="size-4" />
      </Button>
      <Button type="submit" size="icon" aria-label="Invio">
        <CornerDownLeft className="size-4" />
      </Button>
    </form>
  );
}
