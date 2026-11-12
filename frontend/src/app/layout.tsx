import type { Metadata, Viewport } from "next";
import { AppShell } from "@/components/app/app-shell";
import { Providers } from "@/components/app/providers";
import { LOCALE_BOOTSTRAP_SCRIPT, LOCALE_PENDING_CLASS } from "@/i18n/locale-bootstrap";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Chromecast Web", template: "%s · Chromecast Web" },
  description: "Control your Chromecast from any phone on your home network.",
  applicationName: "Chromecast Web",
  appleWebApp: { capable: true, title: "Cast", statusBarStyle: "black-translucent" },
  icons: {
    // favicon.ico (16/32/48) is picked up from src/app; sources and renderer: docs/assets, backend/scripts/brand.py
    icon: [
      { url: "/icons/icon.svg", type: "image/svg+xml" },
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
    ],
    apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180" }],
  },
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0d0d14" },
    { media: "(prefers-color-scheme: light)", color: "#fafafc" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning className="h-full antialiased">
      <head>
        {/* The static HTML is English: apply the saved / browser locale to <html lang> and keep the
            page hidden until LocaleSync has translated it, so Italian users never see English flash. */}
        <style>{`html.${LOCALE_PENDING_CLASS} body{visibility:hidden}`}</style>
        <script dangerouslySetInnerHTML={{ __html: LOCALE_BOOTSTRAP_SCRIPT }} />
      </head>
      <body className="min-h-dvh">
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  );
}
