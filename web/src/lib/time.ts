export function formatUtc(ms: number): string {
  return new Date(ms).toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, ' UTC');
}

export function formatClock(ms: number): string {
  return new Date(ms).toISOString().slice(11, 19);
}

export function formatDuration(fromMs: number, toMs: number): string {
  const total = Math.max(0, Math.round((toMs - fromMs) / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) return `${hours} h ${minutes} min`;
  if (minutes > 0) return `${minutes} min ${seconds} s`;
  return `${seconds} s`;
}

/** YYYYMMDD_HH v UTC — stejné značení hodinových souborů jako Python logger. */
export function hourStamp(ms: number): string {
  const iso = new Date(ms).toISOString();
  return `${iso.slice(0, 4)}${iso.slice(5, 7)}${iso.slice(8, 10)}_${iso.slice(11, 13)}`;
}
