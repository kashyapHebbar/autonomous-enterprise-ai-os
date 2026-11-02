import { useSyncExternalStore } from 'react';

export type UiPrefs = { theme:'dark'|'light'; density:'comfortable'|'compact'; motion:boolean; advanced:boolean };
const KEY = 'aeai-ui95-prefs';
const defaults: UiPrefs = {theme:'dark',density:'comfortable',motion:true,advanced:false};
let cached: UiPrefs | null = null;
const listeners = new Set<() => void>();
function read(): UiPrefs {
  if (cached) return cached;
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || '{}') as Partial<UiPrefs>;
    const legacyTheme = localStorage.getItem('aeai-theme');
    cached = {...defaults, ...saved, theme:saved.theme==='light'||(!saved.theme&&legacyTheme==='light')?'light':'dark', density:saved.density==='compact'?'compact':'comfortable', motion:saved.motion!==false, advanced:saved.advanced===true};
  } catch { cached = {...defaults}; }
  return cached;
}
export function getUiPrefs(): UiPrefs { return read(); }
export function updateUiPrefs(patch: Partial<UiPrefs>) {
  cached = {...read(),...patch};
  try {localStorage.setItem(KEY,JSON.stringify(cached));localStorage.setItem('aeai-theme',cached.theme);} catch { /* storage may be disabled */ }
  listeners.forEach(listener=>listener());
}
export function useUiPrefs(): UiPrefs { return useSyncExternalStore((fn)=>{listeners.add(fn);return ()=>{listeners.delete(fn);};},getUiPrefs,getUiPrefs); }
