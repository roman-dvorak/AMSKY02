import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// Relativní base: stejný build funguje v kořeni vlastní domény
// (viewer.amsky.astrometers.eu) i v podadresáři.
export default defineConfig({
  base: './',
  plugins: [react()],
  build: { target: 'es2022', chunkSizeWarningLimit: 6000 },
  server: {
    // Jen pro vývoj: archiv space.astro.cz povoluje CORS pouze produkční doméně,
    // lokálně ho lze otevřít jako zdroj http://localhost:5173/meteo/<stanice>/<zařízení>/
    proxy: { '/meteo': { target: 'https://space.astro.cz', changeOrigin: true, secure: true } },
  },
  test: { environment: 'node', include: ['tests/**/*.test.ts'] },
});
