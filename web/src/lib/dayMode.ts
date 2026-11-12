export type DayMode = 'daytime' | 'night';

export interface FileTimestamp {
  dateKey: string;
  hour: number;
}

/** Hodinové logy se jmenují `<zařízení>_YYYYMMDD_HH.h5` (čas v UTC). */
export function parseFileTimestamp(filename: string): FileTimestamp | null {
  const match = filename.match(/_(\d{8})_(\d{2})\.h5$/i);
  return match ? { dateKey: match[1], hour: Number(match[2]) } : null;
}

export function addDaysToDateKey(dateKey: string, days: number): string {
  const date = new Date(
    Date.UTC(Number(dateKey.slice(0, 4)), Number(dateKey.slice(4, 6)) - 1, Number(dateKey.slice(6, 8)) + days),
  );
  return date.toISOString().slice(0, 10).replace(/-/g, '');
}

/** Noc se počítá od poledne do poledne a nese datum svého rána. */
export function nightDateKeyForFile(dateKey: string, hour: number): string {
  return hour < 12 ? dateKey : addDaysToDateKey(dateKey, 1);
}

export function fileBelongsToPeriod(filename: string, selectedDateKey: string, mode: DayMode): boolean {
  const parsed = parseFileTimestamp(filename);
  if (!parsed) return false;
  if (mode === 'daytime') return parsed.dateKey === selectedDateKey;
  if (parsed.dateKey === addDaysToDateKey(selectedDateKey, -1) && parsed.hour >= 12) return true;
  return parsed.dateKey === selectedDateKey && parsed.hour < 12;
}

export function periodLabel(mode: DayMode): string {
  return mode === 'night' ? 'Night ending on' : 'Date';
}

export function periodDescription(mode: DayMode, dateInput: string): string {
  if (!dateInput) return '';
  if (mode === 'daytime') return `${dateInput} 00:00 – 24:00 UTC`;
  const previous = dateKeyToInput(addDaysToDateKey(inputToDateKey(dateInput), -1));
  return `${previous} 12:00 – ${dateInput} 12:00 UTC`;
}

export function dateKeyToInput(dateKey: string): string {
  return `${dateKey.slice(0, 4)}-${dateKey.slice(4, 6)}-${dateKey.slice(6, 8)}`;
}

export function inputToDateKey(value: string): string {
  return value.replace(/-/g, '');
}
