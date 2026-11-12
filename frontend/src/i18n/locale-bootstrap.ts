import { DEFAULT_LOCALE, LOCALE_STORAGE_KEY, LOCALES } from "./index";

/** Class on `<html>` that keeps the (English) static HTML hidden until `LocaleSync` has applied another locale. */
export const LOCALE_PENDING_CLASS = "cw-locale-pending";

/**
 * Reveal the page anyway this long after `load` (all scripts fetched, so the app should have
 * hydrated by then) — a failed JS load never leaves it blank, while a slow network still doesn't
 * flash English.
 */
export const LOCALE_PENDING_AFTER_LOAD_MS = 1500;
/** Hard cap, in case `load` never fires (a hung request). */
export const LOCALE_PENDING_MAX_MS = 10000;

/**
 * Inline `<head>` script, run before the first paint of the static (English) HTML.
 * Same detection as `detectLocale` (saved choice → browser language starting with "it" → English):
 * it sets `<html lang>` right away and, when the locale is not the one the HTML is rendered in,
 * hides the page until `LocaleSync` has hydrated and translated it.
 */
export const LOCALE_BOOTSTRAP_SCRIPT = `(function(){try{
var d=document.documentElement,l=null,ok=${JSON.stringify(LOCALES)};
try{l=localStorage.getItem(${JSON.stringify(LOCALE_STORAGE_KEY)})}catch(e){}
if(ok.indexOf(l)<0){var n=navigator.languages&&navigator.languages.length?navigator.languages:[navigator.language];
var f="";for(var i=0;i<n.length;i++){if(n[i]){f=n[i];break}}
l=String(f).toLowerCase().indexOf("it")===0?"it":${JSON.stringify(DEFAULT_LOCALE)}}
d.lang=l;
if(l!==${JSON.stringify(DEFAULT_LOCALE)}){var c=${JSON.stringify(LOCALE_PENDING_CLASS)},r=function(){d.classList.remove(c)};
d.classList.add(c);setTimeout(r,${LOCALE_PENDING_MAX_MS});
addEventListener("load",function(){setTimeout(r,${LOCALE_PENDING_AFTER_LOAD_MS})})}
}catch(e){}})();`;
