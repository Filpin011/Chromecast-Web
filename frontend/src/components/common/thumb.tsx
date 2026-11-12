"use client";

import { Film, type LucideIcon } from "lucide-react";
import { useState } from "react";
import { backendUrl } from "@/lib/config";
import { cn } from "@/lib/utils";

/** Square/16:9 thumbnail with graceful fallback icon. */
export function Thumb({
  src,
  alt = "",
  className,
  icon: Icon = Film,
  fit = "cover",
}: {
  src: string | null | undefined;
  alt?: string;
  className?: string;
  icon?: LucideIcon;
  fit?: "cover" | "contain";
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const show = src && failed !== src;
  return (
    <div className={cn("relative grid shrink-0 place-items-center overflow-hidden rounded-lg bg-muted", className)}>
      {show ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={backendUrl(src)}
          alt={alt}
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => setFailed(src)}
          className={cn("size-full", fit === "cover" ? "object-cover" : "object-contain p-1")}
        />
      ) : (
        <Icon className="size-1/2 max-h-6 max-w-6 text-muted-foreground" aria-hidden />
      )}
    </div>
  );
}
