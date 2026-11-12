/**
 * Simulátor senzoru: generuje řádky protokolu AMSKY02 bez hardwaru.
 * Slouží k vyzkoušení aplikace a k vývoji v prohlížečích bez Web Serial.
 */

const ROWS = 24;
const COLS = 32;

function thermalMap(sensor: number, phase: number, sky: number, ambient: number): string {
  const values: string[] = [];
  // Mrak = teplejší skvrna putující přes zorné pole.
  const cx = COLS / 2 + Math.cos(phase / 9 + sensor) * COLS * 0.45;
  const cy = ROWS / 2 + Math.sin(phase / 13 + sensor * 2) * ROWS * 0.4;
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      const d2 = ((c - cx) / 7) ** 2 + ((r - cy) / 5) ** 2;
      const cloud = (ambient - 4 - sky) * Math.exp(-d2);
      // Okraj zorného pole vidí níž nad obzor, kde je obloha teplejší.
      const edge = (((c - COLS / 2) / COLS) ** 2 + ((r - ROWS / 2) / ROWS) ** 2) * 14;
      values.push((sky + cloud + edge + (Math.random() - 0.5) * 0.4).toFixed(2));
    }
  }
  return `$thrmap,${sensor},${values.join(',')}`;
}

export function demoHello(): string[] {
  return [
    '# AMSKY02B',
    '# Serial Number: DEMO000000000000',
    '# FW Version: demo',
    '$HELLO,AMSKY02B,DEMO000000000000,demo,0000000,demo',
  ];
}

/** Jedna perioda měření (firmware ji posílá každé 2 s). */
export function demoTick(step: number, thrmap: boolean): string[] {
  const ambient = 6 + Math.sin(step / 60) * 2;
  const humidity = 72 - Math.sin(step / 60) * 8;
  const dew = ambient - (100 - humidity) / 5;
  const sky = -28 + Math.sin(step / 25) * 6;
  const lines = [`$hygro,${ambient.toFixed(2)},${humidity.toFixed(2)},${dew.toFixed(2)}`];

  for (const ch of [0, 1]) {
    const sqm = 20.9 + Math.sin(step / 40 + ch) * 0.35 + (Math.random() - 0.5) * 0.04;
    const full = Math.round(3600 + Math.sin(step / 40 + ch) * 400 + Math.random() * 30);
    const ir = Math.round(full * 0.03);
    const lux = Math.pow(10, (14.2 - sqm) / 2.5);
    lines.push(`$light,${ch},${Math.round(lux * 1e6)},${full},${ir},9876,600,${sqm.toFixed(2)}`);
  }

  for (const sensor of [1, 2]) {
    const center = sky + Math.sin(step / 9 + sensor) * 1.5;
    const corner = (k: number) => (center + 6 + Math.sin(step / 11 + k + sensor) * 2).toFixed(2);
    lines.push(`$cloud_meta,${sensor},3.300,${(ambient + 1.4).toFixed(3)}`);
    lines.push(`$cloud,${sensor},${corner(0)},${corner(1)},${corner(2)},${corner(3)},${center.toFixed(2)}`);
    if (thrmap) lines.push(thermalMap(sensor, step, sky, ambient));
  }
  return lines;
}
