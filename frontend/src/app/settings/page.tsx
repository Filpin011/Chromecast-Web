"use client";

import { Check, ImageIcon, Info, Languages, Loader2, MonitorSmartphone, Network, Palette, ShieldCheck, Tv } from "lucide-react";
import { useState, type ReactNode } from "react";
import { toast } from "sonner";
import { ThemeToggle } from "@/components/app/theme-toggle";
import { PageBody, PageHeader } from "@/components/common/page-header";
import { AdblockSettings } from "@/components/settings/adblock-settings";
import { Thumb } from "@/components/common/thumb";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useHealth, useSettings, useUpdateSettings } from "@/hooks/queries";
import { useActiveDevice, useConnection, useDevices } from "@/hooks/use-app-state";
import { api } from "@/lib/api";
import type { Settings } from "@/lib/api/types";
import { LanguagePicker } from "@/components/settings/language-picker";
import { useT } from "@/i18n";
import { errorMessage } from "@/lib/query";
import { useAppStore } from "@/stores/app-store";

function Section({ title, icon: Icon, children }: { title: string; icon: typeof Tv; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="flex items-center gap-2 px-1 text-sm font-semibold text-muted-foreground">
        <Icon className="size-4" /> {title}
      </h2>
      <div className="divide-y overflow-hidden rounded-2xl border bg-card">{children}</div>
    </section>
  );
}

function Row({ label, description, children, htmlFor }: { label: string; description?: ReactNode; children?: ReactNode; htmlFor?: string }) {
  return (
    <div className="flex min-h-14 items-center gap-3 px-4 py-3">
      <div className="min-w-0 flex-1">
        <label htmlFor={htmlFor} className="block text-sm font-medium">
          {label}
        </label>
        {description && <p className="text-xs text-muted-foreground">{description}</p>}
      </div>
      {children}
    </div>
  );
}

function ToggleRow({ id, label, description, field, settings, onChange }: {
  id: string;
  label: string;
  description?: string;
  field: "show_idle_on_connect" | "show_idle_on_stop" | "force_proxy";
  settings: Settings | undefined;
  onChange: (patch: Partial<Settings>) => void;
}) {
  return (
    <Row label={label} description={description} htmlFor={id}>
      <Switch
        id={id}
        checked={settings?.[field] ?? false}
        disabled={!settings}
        onCheckedChange={(v) => onChange({ [field]: v } as Partial<Settings>)}
      />
    </Row>
  );
}

/** Text field that saves on blur / Enter (null when empty). */
function TextSetting({
  id,
  value,
  placeholder,
  describedBy,
  onSave,
  inputMode = "url",
}: {
  id: string;
  value: string | null;
  placeholder?: string;
  describedBy?: string;
  onSave: (v: string | null) => void;
  inputMode?: "url" | "text";
}) {
  const t = useT();
  const [draft, setDraft] = useState(value ?? "");
  const dirty = draft.trim() !== (value ?? "");
  const save = () => {
    if (dirty) onSave(draft.trim() || null);
  };
  return (
    <div className="flex gap-2 px-4 pb-3">
      <input
        id={id}
        value={draft}
        placeholder={placeholder}
        aria-describedby={describedBy}
        inputMode={inputMode}
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            save();
          }
        }}
        className="h-11 min-w-0 flex-1 rounded-xl bg-muted px-3 text-base outline-none focus:ring-2 focus:ring-primary/40"
      />
      <Button variant="secondary" size="icon" aria-label={t("common.save")} disabled={!dirty} onClick={save}>
        <Check className="size-4" />
      </Button>
    </div>
  );
}

export default function SettingsPage() {
  const t = useT();
  const settings = useSettings();
  const update = useUpdateSettings();
  const devices = useDevices();
  const active = useActiveDevice();
  const health = useHealth();
  const connection = useConnection();
  const s = settings.data;
  const save = (patch: Partial<Settings>) => update.mutate(patch);

  const showIdleNow = async () => {
    if (!active) {
      toast.error(t("settings.connectFirst"));
      return;
    }
    try {
      useAppStore.getState().applyPlayer(await api.player.showIdle(active.id));
      toast.success(t("settings.idleShown"));
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };

  return (
    <>
      <PageHeader
        title={t("settings.title")}
        actions={update.isPending ? <Loader2 className="size-5 animate-spin text-muted-foreground" aria-label={t("common.saving")} /> : null}
      />
      <PageBody className="space-y-6 pt-2">
        <Section title={t("settings.device")} icon={Tv}>
          <Row label={t("settings.defaultDevice")} description={t("settings.defaultDeviceHint")} htmlFor="default-device">
            <select
              id="default-device"
              value={s?.default_device_id ?? ""}
              disabled={!s}
              onChange={(e) => save({ default_device_id: e.target.value || null })}
              className="h-10 max-w-[45%] rounded-xl bg-muted px-3 text-sm outline-none focus:ring-2 focus:ring-primary/40"
            >
              <option value="">{t("settings.none")}</option>
              {devices.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </Row>
        </Section>

        <Section title={t("settings.idleImage")} icon={ImageIcon}>
          <div className="space-y-3 px-4 pt-4 pb-1">
            <Thumb src={s?.idle_image_url ?? "/idle.jpg"} className="aspect-video w-full rounded-xl" icon={ImageIcon} />
          </div>
          <div className="border-none pt-1">
            <label htmlFor="idle-url" className="block px-4 pb-1.5 text-sm font-medium">
              {t("settings.imageUrl")}
            </label>
            {s ? (
              <TextSetting
                key={s.idle_image_url ?? ""}
                id="idle-url"
                value={s.idle_image_url}
                placeholder={t("settings.imageUrlPlaceholder")}
                describedBy="idle-url-hint"
                onSave={(v) => save({ idle_image_url: v })}
              />
            ) : (
              <div className="mx-4 mb-3 h-11 animate-pulse rounded-xl bg-muted" />
            )}
            <p id="idle-url-hint" className="-mt-1.5 px-4 pb-3 text-xs text-muted-foreground">
              {t("settings.imageUrlHint")}
            </p>
          </div>
          <ToggleRow id="idle-connect" label={t("settings.showOnConnect")} field="show_idle_on_connect" settings={s} onChange={save} />
          <ToggleRow id="idle-stop" label={t("settings.showOnStop")} field="show_idle_on_stop" settings={s} onChange={save} />
          <div className="p-3">
            <Button variant="secondary" className="w-full" onClick={showIdleNow} disabled={!active}>
              {t("settings.showNow")}
            </Button>
          </div>
        </Section>

        <Section title={t("settings.network")} icon={Network}>
          <div className="pt-3">
            <label htmlFor="public-url" className="block px-4 text-sm font-medium">
              {t("settings.publicUrl")}
            </label>
            <p className="px-4 pb-2 text-xs text-muted-foreground">
              {t("settings.publicUrlHint")}
            </p>
            {s ? (
              <TextSetting
                key={s.public_base_url ?? ""}
                id="public-url"
                value={s.public_base_url}
                placeholder="http://192.168.1.10:8000"
                onSave={(v) => save({ public_base_url: v })}
              />
            ) : (
              <div className="mx-4 mb-3 h-11 animate-pulse rounded-xl bg-muted" />
            )}
          </div>
          <ToggleRow
            id="force-proxy"
            label={t("settings.forceProxy")}
            description={t("settings.forceProxyHint")}
            field="force_proxy"
            settings={s}
            onChange={save}
          />
        </Section>

        <Section title={t("settings.browserAds")} icon={ShieldCheck}>
          <AdblockSettings settings={s} onChange={save} />
        </Section>

        <Section title={t("settings.language")} icon={Languages}>
          <div className="p-3">
            <LanguagePicker />
          </div>
        </Section>

        <Section title={t("settings.appearance")} icon={Palette}>
          <div className="p-3">
            <ThemeToggle />
          </div>
        </Section>

        <Section title={t("settings.about")} icon={Info}>
          <Row label={t("settings.server")}>
            <span className="text-sm text-muted-foreground">
              {health.data ? `v${health.data.version} · driver ${health.data.driver}` : health.isError ? t("settings.unreachable") : "…"}
            </span>
          </Row>
          <Row label={t("settings.liveSync")}>
            <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <span className={connection === "open" ? "size-2 rounded-full bg-success" : "size-2 rounded-full bg-amber-500"} />
              {connection === "open" ? t("settings.connected") : t("connection.reconnecting")}
            </span>
          </Row>
          <Row label={t("settings.install")} description={t("settings.installHint")}>
            <MonitorSmartphone className="size-5 text-muted-foreground" />
          </Row>
        </Section>
      </PageBody>
    </>
  );
}
