"use client"

import { useTheme } from "next-themes"
import { Toaster as Sonner, type ToasterProps } from "sonner"
import { useT } from "@/i18n"
import { CircleCheckIcon, InfoIcon, TriangleAlertIcon, OctagonXIcon, Loader2Icon } from "lucide-react"

const Toaster = ({ toastOptions, ...props }: ToasterProps) => {
  const { theme = "system" } = useTheme()
  const t = useT()

  return (
    <Sonner
      theme={theme as ToasterProps["theme"]}
      className="toaster group"
      icons={{
        success: (
          <CircleCheckIcon className="size-4" />
        ),
        info: (
          <InfoIcon className="size-4" />
        ),
        warning: (
          <TriangleAlertIcon className="size-4" />
        ),
        error: (
          <OctagonXIcon className="size-4" />
        ),
        loading: (
          <Loader2Icon className="size-4 animate-spin" />
        ),
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "var(--radius)",
          // richColors from the app's tokens (sonner's own greens/reds/blues otherwise)
          "--success-bg": "color-mix(in oklch, var(--success) 12%, var(--popover))",
          "--success-border": "color-mix(in oklch, var(--success) 30%, var(--popover))",
          "--success-text": "color-mix(in oklch, var(--success) 75%, var(--foreground))",
          "--error-bg": "color-mix(in oklch, var(--destructive) 12%, var(--popover))",
          "--error-border": "color-mix(in oklch, var(--destructive) 30%, var(--popover))",
          "--error-text": "color-mix(in oklch, var(--destructive) 75%, var(--foreground))",
          "--warning-bg": "color-mix(in oklch, var(--warning) 12%, var(--popover))",
          "--warning-border": "color-mix(in oklch, var(--warning) 30%, var(--popover))",
          "--warning-text": "color-mix(in oklch, var(--warning) 75%, var(--foreground))",
          "--info-bg": "color-mix(in oklch, var(--primary) 12%, var(--popover))",
          "--info-border": "color-mix(in oklch, var(--primary) 30%, var(--popover))",
          "--info-text": "color-mix(in oklch, var(--primary) 75%, var(--foreground))",
        } as React.CSSProperties
      }
      containerAriaLabel={t("common.notifications")}
      toastOptions={{
        closeButtonAriaLabel: t("common.closeNotification"),
        ...toastOptions,
        classNames: {
          toast: "cn-toast",
          ...toastOptions?.classNames,
        },
      }}
      {...props}
    />
  )
}

export { Toaster }
