import { useCallback, useState } from 'react';

/** Stav uložený v localStorage (nastavení zobrazení přežije zavření stránky). */
export function useStoredState<T>(key: string, initial: T, validate?: (value: unknown) => value is T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      if (raw === null) return initial;
      const parsed: unknown = JSON.parse(raw);
      return !validate || validate(parsed) ? (parsed as T) : initial;
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (next: T) => {
      setValue(next);
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        /* úložiště není dostupné — nastavení platí jen do zavření stránky */
      }
    },
    [key],
  );
  return [value, set];
}
