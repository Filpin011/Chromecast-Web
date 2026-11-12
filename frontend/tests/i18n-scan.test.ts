/**
 * Guard against UI text that bypasses the dictionaries: scans src/app and src/components for
 * string literals and JSX text that look Italian. Deliberately conservative (whole words that are
 * unambiguously Italian, accented letters), so it doesn't flag English copy or code.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = join(__dirname, "..", "src");
const DIRS = ["app", "components"];
/** shadcn primitives: generated, no product copy. */
const SKIP = [join("components", "ui")];

const ITALIAN_WORDS = [
  "il", "gli", "della", "delle", "dello", "degli", "nel", "nella", "sul", "sulla", "dal", "dalla", "alla", "allo",
  "per", "con", "non", "che", "una", "uno", "questo", "questa", "nessun", "nessuna", "nessuno", "tutti", "ora",
  "aggiungi", "apri", "chiudi", "cerca", "elimina", "annulla", "salva", "riprova", "rimuovi", "trasmetti",
  "caricamento", "impostazioni", "dispositivo", "dispositivi", "anteprima", "coda", "preferiti", "preferito",
  "cronologia", "pagina", "sessione", "sessioni", "riproduzione", "indietro", "avanti", "canali", "canale",
  "aggiorna", "importa", "connessione", "nuova", "nuovo", "vuota", "vuoto", "attesa", "immagine", "rete", "aspetto",
  "lingua", "tastiera", "blocca", "consenti", "chiedi", "sottotitoli", "traccia", "precedente", "successivo",
  "impossibile", "riuscito", "riuscita", "aggiunto", "rimosso", "trovato", "trovata", "disattivato", "attivo",
  "di", "da", "lo", "su", "del", "dei", "tutto", "recenti", "libreria", "chiaro", "scuro", "sistema", "tema",
  "percorso", "informazioni", "installa", "connesso", "riconnessione", "salvataggio", "manuale", "aggiornata",
  "aggiornate", "cancella", "incolla", "invio", "invia", "vista", "elenco", "griglia", "gruppi", "indirizzo",
  "ricarica", "ricerca", "rilevato", "rilevati", "versione", "lista", "liste", "regole", "errore", "scegli",
  "nome", "pausa", "muto", "posizione", "altro", "analizza", "analisi", "appunti", "trascina", "disattivati",
  "riattiva", "ferma", "navigazione", "catturati",
];
// a hyphen counts as part of the word, so English like "non-ad" doesn't match "non"
const WORD_RE = new RegExp(`(^|[^\\p{L}-])(${ITALIAN_WORDS.join("|")})(?=$|[^\\p{L}-])`, "iu");
const ACCENT_RE = /[àèéìòùÀÈÉÌÒÙ]/;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (SKIP.some((s) => relative(ROOT, p).startsWith(s))) return [];
    if (statSync(p).isDirectory()) return files(p);
    return /\.(ts|tsx)$/.test(name) ? [p] : [];
  });
}

/** Drop comments (keeping line numbers) so prose in doc comments is not scanned. */
function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
    .replace(/(^|[^:"'`\\])\/\/.*$/gm, (_m, pre: string) => pre)
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, (m) => m.replace(/[^\n]/g, " "));
}

/** Pieces of user-visible text: string/template literals and JSX text nodes. */
function candidates(src: string): { text: string; line: number }[] {
  const out: { text: string; line: number }[] = [];
  const lineAt = (i: number) => src.slice(0, i).split("\n").length;
  const literal = /"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)'|`((?:[^`\\]|\\.)*)`/g;
  for (const m of src.matchAll(literal)) {
    const text = (m[1] ?? m[2] ?? m[3] ?? "").replace(/\$\{[^}]*\}/g, " ");
    out.push({ text, line: lineAt(m.index ?? 0) });
  }
  // JSX text: between a tag end and the next tag / expression
  for (const m of src.matchAll(/>([^<>{}]+)</g)) {
    if (/[\p{L}]/u.test(m[1])) out.push({ text: m[1], line: lineAt(m.index ?? 0) });
  }
  return out;
}

function isImport(src: string, line: number): boolean {
  return /^\s*(import|export .* from)\b/.test(src.split("\n")[line - 1] ?? "");
}

function findItalian(src: string): { text: string; line: number }[] {
  const code = stripComments(src);
  return candidates(code).filter(
    ({ text, line }) => (WORD_RE.test(text) || ACCENT_RE.test(text)) && !isImport(code, line),
  );
}

describe("hard-coded Italian scan", () => {
  it("detects obvious Italian UI text (self-test)", () => {
    expect(findItalian(`<p>Nessun dispositivo trovato</p>`)).toHaveLength(1);
    expect(findItalian(`<Button aria-label="Chiudi sessione" />`)).toHaveLength(1);
    expect(findItalian("toast.error(`Impossibile connettersi a ${x}`)")).toHaveLength(1);
    expect(findItalian("toast.success(`${d.name} è stato aggiunto`)")).toHaveLength(1);
    expect(findItalian(`<p>No device found</p>`)).toHaveLength(0);
    expect(findItalian(`// Apri la pagina\nconst x = 1;`)).toHaveLength(0);
    expect(findItalian(`<span>{t("devices.none")}</span>`)).toHaveLength(0);
  });

  it("finds no hard-coded Italian strings in src/app and src/components", () => {
    const hits = DIRS.flatMap((d) => files(join(ROOT, d))).flatMap((f) =>
      findItalian(readFileSync(f, "utf8")).map((h) => `${relative(ROOT, f)}:${h.line}: ${h.text.trim().slice(0, 80)}`),
    );
    expect(hits).toEqual([]);
  });
});
