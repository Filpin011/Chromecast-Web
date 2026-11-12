import type { MessageKey } from "@/i18n";
import { Clapperboard, Compass, FolderOpen, Library, ListVideo, Settings, type LucideIcon } from "lucide-react";

export interface NavItem {
  href: string;
  /** Dictionary key of the label. */
  label: MessageKey;
  icon: LucideIcon;
  /** Shown in the mobile tab bar. */
  tab: boolean;
  /** Hidden when the backend has no MEDIA_ROOT. */
  requiresLocal?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "nav.cast", icon: Clapperboard, tab: true },
  { href: "/browser/", label: "nav.browser", icon: Compass, tab: true },
  { href: "/playlists/", label: "nav.playlists", icon: ListVideo, tab: true },
  { href: "/library/", label: "nav.library", icon: Library, tab: true },
  { href: "/files/", label: "nav.files", icon: FolderOpen, tab: false, requiresLocal: true },
  { href: "/settings/", label: "nav.settings", icon: Settings, tab: true },
];

export function isActivePath(pathname: string, href: string): boolean {
  const norm = (p: string) => (p.endsWith("/") ? p : `${p}/`);
  if (href === "/") return pathname === "/" || pathname === "";
  return norm(pathname).startsWith(norm(href));
}
