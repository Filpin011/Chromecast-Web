import { Loader2Icon } from "lucide-react"
import type { ComponentProps } from "react"
import { cn } from "@/lib/utils"

/**
 * The app's one loading spinner. Decorative (hidden from screen readers) unless it gets an `aria-label`,
 * in which case it is announced as an image with that name. Size it with `size-*` like any icon.
 */
function Spinner({ className, "aria-label": label, ...props }: ComponentProps<"svg">) {
  return (
    <Loader2Icon
      data-slot="spinner"
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? "img" : undefined}
      className={cn("size-4 animate-spin", className)}
      {...props}
    />
  )
}

export { Spinner }
