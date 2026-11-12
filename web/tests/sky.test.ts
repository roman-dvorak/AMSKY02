import { describe, expect, it } from 'vitest';
import { movingAverage } from '../src/lib/smooth';
import { composeSky, indexAtTime } from '../src/lib/sky';

// 2 řádky × 3 sloupce: [[0,1,2],[3,4,5]] a totéž +10 pro druhý senzor.
const a = { rows: 2, cols: 3, pixels: Float32Array.from([0, 1, 2, 3, 4, 5]) };
const b = { rows: 2, cols: 3, pixels: Float32Array.from([10, 11, 12, 13, 14, 15]) };

describe('composeSky', () => {
  it('stacks the first sensor above the second', () => {
    const c = composeSky([a, b], 'stacked')!;
    expect([c.width, c.height]).toEqual([3, 4]);
    expect(Array.from(c.data)).toEqual([0, 1, 2, 3, 4, 5, 10, 11, 12, 13, 14, 15]);
    expect(c.locate(2, 3)).toEqual({ tile: 1, row: 1, col: 2 });
  });

  it('rotates each sensor 90° left and joins them side by side (np.rot90 + hstack)', () => {
    const c = composeSky([a, b], 'rotated')!;
    expect([c.width, c.height]).toEqual([4, 3]);
    // np.rot90([[0,1,2],[3,4,5]]) = [[2,5],[1,4],[0,3]]
    expect(Array.from(c.data)).toEqual([2, 5, 12, 15, 1, 4, 11, 14, 0, 3, 10, 13]);
    expect(c.locate(3, 0)).toEqual({ tile: 1, row: 1, col: 2 });
  });

  it('leaves a missing sensor empty', () => {
    const c = composeSky([a, { rows: 2, cols: 3, pixels: null }], 'stacked')!;
    expect(Array.from(c.data.slice(6)).every(Number.isNaN)).toBe(true);
  });
});

describe('helpers', () => {
  it('finds the frame at or before a time', () => {
    expect(indexAtTime([10, 20, 30], 25)).toBe(1);
    expect(indexAtTime([10, 20, 30], 5)).toBe(0);
    expect(indexAtTime([10, 20, 30], 99)).toBe(2);
    expect(indexAtTime([], 1)).toBe(-1);
  });

  it('smooths with a centred window and keeps gaps', () => {
    expect(movingAverage([1, 2, 3, 4, 5], 3)).toEqual([1.5, 2, 3, 4, 4.5]);
    const out = movingAverage([1, NaN, 3], 3);
    expect(out[0]).toBe(1);
    expect(out[1]).toBeNaN();
    expect(out[2]).toBe(3);
    expect(movingAverage([1, 2], 0)).toEqual([1, 2]);
  });
});
