import { Clapperboard, Compass, FolderOpen, Library, ListVideo, Settings, type LucideIcon } from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Shown in the mobile tab bar. */
  tab: boolean;
  /** Hidden when the backend has no MEDIA_ROOT. */
  requiresLocal?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Cast", icon: Clapperboard, tab: true },
  { href: "/browser/", label: "Browser", icon: Compass, tab: true },
  { href: "/playlists/", label: "Playlist", icon: ListVideo, tab: true },
  { href: "/library/", label: "Libreria", icon: Library, tab: true },
  { href: "/files/", label: "File locali", icon: FolderOpen, tab: false, requiresLocal: true },
  { href: "/settings/", label: "Impostazioni", icon: Settings, tab: true },
];

export function isActivePath(pathname: string, href: string): boolean {
  const norm = (p: string) => (p.endsWith("/") ? p : `${p}/`);
  if (href === "/") return pathname === "/" || pathname === "";
  return norm(pathname).startsWith(norm(href));
}
