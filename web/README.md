# AMSKY Viewer (web)

Statická webová aplikace (React + Vite + TypeScript) pro senzory AMSKY.
Běží celá v prohlížeči, nemá žádný backend. Produkční adresa:
**https://viewer.amsky.astrometers.eu**

| Záložka | Co dělá |
| --- | --- |
| **Živě** | Připojí se k senzoru přes USB (Web Serial), ukazuje aktuální hodnoty, teplotní mapu oblohy z obou senzorů a grafy od připojení. Záznam lze stáhnout jako HDF5. Součástí je konzole pro příkazy (`config_show`, `set …`). |
| **Archiv** | Prohlíží hodinové HDF5 logy z adresáře na webu. Adresu adresáře zadává uživatel; naposledy použité zdroje se pamatují a dají se připnout. |
| **Soubory** | Otevře HDF5 logy z disku (přetažením nebo výběrem). Soubory se nikam neodesílají. |

## Požadavky na prohlížeč

Živé připojení potřebuje **Web Serial API** — Chrome, Edge nebo Opera na
počítači, a stránku načtenou přes HTTPS (nebo z `localhost`). Firefox a Safari
sériový port neumí; archiv a soubory v nich fungují. Na Linuxu musí mít
uživatel přístup k portu (`sudo usermod -aG dialout $USER`).

Port může mít otevřený vždy jen jeden program — před připojením z webu zavřete
`amsky-viewer` / `amsky-cli` (a naopak).

## Archiv

Zdroj je adresa složky, kterou webový server vypisuje jako seznam souborů
(Apache/nginx autoindex), např. `https://example.org/meteo/stanice/AMSKY02/`.
Soubory se musí jmenovat `<cokoli>_YYYYMMDD_HH.h5` (čas v UTC), jak je vytváří
`amsky-viewer --log`. Když složka sama žádné `.h5` neobsahuje, projdou se její
podsložky.

Server musí stránce povolit čtení hlavičkou CORS, pro Apache např.:

```apache
Header set Access-Control-Allow-Origin "https://viewer.amsky.astrometers.eu"
```

Konkrétní pohled lze sdílet odkazem — parametry `view`, `src`, `date`, `mode`
(`night` = poledne–poledne) a `files`. Seznam zdrojů a nastavení zobrazení se
ukládají jen do `localStorage` prohlížeče.

## Formát HDF5

Čtení i zápis odpovídají `HDF5Logger` v `sw/amsky_viewer.py`:

```
/sky<N>/     data (n × řádky × sloupce, float32), time (int64 ns), temp
/cloud<N>/   tl, tr, bl, br, center, vdd, time
/light<C>/   all, ir, gain, expo, time   (+ lux, sqm u záznamů z webu)
/hygro/      temp, hum, time
```

Čtou se i starší logy (`/sky`, `/light` bez indexu, mapa 16×12). Záznam stažený
z webu navíc nese `lux` a `sqm` tak, jak je spočítal firmware; u logů bez nich
se lux a SQM přepočítávají z raw hodnot (`src/lib/light.ts`).

## Vývoj

```bash
cd web
npm install
npm run dev        # http://localhost:5173
npm test           # jednotkové testy (vitest)
npm run build      # typová kontrola + produkční build do dist/
```

Bez hardwaru lze živý pohled vyzkoušet tlačítkem **Simulátor**.

Archiv `space.astro.cz` povoluje CORS jen produkční doméně. Vývojový server
proto přeposílá cestu `/meteo`, takže lokálně lze jako zdroj zadat
`http://localhost:5173/meteo/svakov/AMSKY02/`.

## Nasazení

Workflow `.github/workflows/deploy-viewer.yml` při pushi do výchozí větve `AMSKY02C` (změny ve
`web/`) spustí testy, build a nasadí `web/dist` na GitHub Pages. Jednorázově je
potřeba:

1. v nastavení repozitáře **Settings → Pages → Source** zvolit *GitHub Actions*,
2. v DNS vytvořit záznam `viewer.amsky.astrometers.eu CNAME roman-dvorak.github.io`,
3. v **Settings → Pages** vyplnit vlastní doménu a zapnout *Enforce HTTPS*
   (HTTPS je pro Web Serial nutné).

Doménu drží soubor `public/CNAME`. Build používá relativní cesty, takže funguje
v kořeni domény i v podadresáři.

## Struktura

```
src/lib/protocol.ts        parser sériového protokolu ($light, $cloud, $thrmap…)
src/lib/serial.ts          Web Serial: připojení, čtení po řádcích, příkazy
src/lib/session.ts         živá relace — poslední hodnoty a historie
src/lib/liveController.ts  zdroj živých dat (port / simulátor)
src/lib/hdf5.ts            čtení a zápis HDF5 (h5wasm, načítá se až při potřebě)
src/lib/archive.ts         výpis adresáře, výběr dne/noci
src/lib/sources.ts         zadané zdroje archivu (poslední, připnuté)
src/lib/sky.ts             skládání map senzorů, palety, rozsah škály
src/components/            pohledy Živě / Archiv / Soubory, grafy, mapa oblohy
```
