/** Středovaný klouzavý průměr; mezery (NaN) se nepřenášejí do okolí. */
export function movingAverage(values: number[], window: number): number[] {
  if (window <= 1) return values;
  const half = Math.floor(window / 2);
  const out = new Array<number>(values.length);
  let sum = 0;
  let count = 0;
  let lo = 0;
  let hi = 0; // okno je [lo, hi)
  for (let i = 0; i < values.length; i++) {
    const end = Math.min(values.length, i + half + 1);
    const start = Math.max(0, i - half);
    for (; hi < end; hi++) if (Number.isFinite(values[hi])) (sum += values[hi]), count++;
    for (; lo < start; lo++) if (Number.isFinite(values[lo])) (sum -= values[lo]), count--;
    out[i] = Number.isFinite(values[i]) && count > 0 ? sum / count : NaN;
  }
  return out;
}
