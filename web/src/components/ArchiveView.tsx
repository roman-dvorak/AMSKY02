import { useCallback, useEffect, useRef, useState } from 'react';
import { defaultDateInput, fetchFile, filterFilesByDate, listSourceFiles } from '../lib/archive';
import type { DayMode } from '../lib/dayMode';
import { addDaysToDateKey, dateKeyToInput, inputToDateKey, periodDescription, periodLabel } from '../lib/dayMode';
import { parseH5 } from '../lib/hdf5';
import { mergeDatasets } from '../lib/merge';
import type { ArchiveSource } from '../lib/sources';
import { loadSources, normalizeSourceUrl, removeSource, setPinned, sourceLabel, touchSource } from '../lib/sources';
import type { Dataset, H5FileEntry } from '../lib/types';
import { readDate, readDayMode, readFiles, readSource, writeParams } from '../lib/urlState';
import { DatasetView } from './DatasetView';

const MODE_LABEL: Record<DayMode, string> = {
  daytime: 'Daytime (půlnoc–půlnoc)',
  night: 'Night (poledne–poledne)',
};

/** Naposledy rozparsované soubory, aby přepínání výběru nestahovalo znovu. */
const parsedCache = new Map<string, Dataset>();
const CACHE_LIMIT = 48;

async function loadEntry(entry: H5FileEntry): Promise<Dataset> {
  const cached = parsedCache.get(entry.url);
  if (cached) return cached;
  const parsed = await parseH5(entry.filename, await fetchFile(entry));
  parsedCache.set(entry.url, parsed);
  if (parsedCache.size > CACHE_LIMIT) parsedCache.delete(parsedCache.keys().next().value!);
  return parsed;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Neočekávaná chyba při načítání dat.';
}

/** Výběr zdroje: zadání adresy a seznam připnutých a naposledy použitých. */
function SourcePicker({
  sources,
  onOpen,
  onPin,
  onRemove,
}: {
  sources: ArchiveSource[];
  onOpen(url: string): void;
  onPin(url: string, pinned: boolean): void;
  onRemove(url: string): void;
}) {
  const [input, setInput] = useState('');
  const [invalid, setInvalid] = useState(false);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    const url = normalizeSourceUrl(input);
    if (!url) {
      setInvalid(true);
      return;
    }
    onOpen(url);
  };

  const pinned = sources.filter((s) => s.pinned);
  const recent = sources.filter((s) => !s.pinned);

  const group = (title: string, items: ArchiveSource[]) =>
    items.length > 0 && (
      <div className="source-group">
        <span className="label">{title}</span>
        <ul className="source-list">
          {items.map((source) => (
            <li key={source.url} className="source-item">
              <button type="button" className="source-open" onClick={() => onOpen(source.url)}>
                <span className="source-name">{sourceLabel(source.url)}</span>
                <span className="source-url">{source.url}</span>
              </button>
              <button
                type="button"
                className={`icon-btn ${source.pinned ? 'active' : ''}`}
                onClick={() => onPin(source.url, !source.pinned)}
                title={source.pinned ? 'Odepnout' : 'Připnout'}
                aria-label={source.pinned ? `Odepnout ${source.url}` : `Připnout ${source.url}`}
                aria-pressed={source.pinned}
              >
                {source.pinned ? '★' : '☆'}
              </button>
              <button
                type="button"
                className="icon-btn"
                onClick={() => onRemove(source.url)}
                title="Odebrat ze seznamu"
                aria-label={`Odebrat ${source.url} ze seznamu`}
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      </div>
    );

  return (
    <section className="source-picker">
      <form className="source-form" onSubmit={submit}>
        <label className="field grow">
          <span className="label">Adresa adresáře s HDF5 logy</span>
          <input
            type="text"
            inputMode="url"
            value={input}
            onChange={(e) => {
              setInput(e.target.value);
              setInvalid(false);
            }}
            placeholder="https://example.org/meteo/stanice/AMSKY02/"
            spellCheck={false}
            autoComplete="url"
            aria-invalid={invalid}
          />
        </label>
        <button type="submit" className="primary" disabled={!input.trim()}>
          Otevřít
        </button>
      </form>
      {invalid && <div className="error-banner">Zadejte platnou adresu začínající http:// nebo https://.</div>}
      <p className="note">
        Zadejte adresu složky, kde webový server vypisuje hodinové soubory <code>…_YYYYMMDD_HH.h5</code>. Server musí
        povolit čtení z této stránky (CORS).
      </p>
      {group('Připnuté', pinned)}
      {group('Naposledy použité', recent)}
      {sources.length === 0 && (
        <div className="status-banner">Zatím žádné zdroje. Po otevření se adresa uloží sem a půjde připnout.</div>
      )}
    </section>
  );
}

/** Procházení archivu: zdroj zadaný adresou, výběr dne a hodinových souborů. */
export function ArchiveView() {
  const [sources, setSources] = useState<ArchiveSource[]>(loadSources);
  const [source, setSource] = useState<string | null>(null);
  const [mode, setMode] = useState<DayMode>(readDayMode);
  const [date, setDate] = useState('');
  const [allFiles, setAllFiles] = useState<H5FileEntry[]>([]);
  const [dayFiles, setDayFiles] = useState<H5FileEntry[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [data, setData] = useState<Dataset | null>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingFile, setLoadingFile] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [linkCopied, setLinkCopied] = useState(false);

  // Každé nové načtení zneplatní výsledky těch rozběhnutých dříve.
  const fileToken = useRef(0);
  const listToken = useRef(0);
  // Výběr dne a souborů z odkazu, kterým byla stránka otevřena.
  const initialLink = useRef({ date: readDate(), files: readFiles() });

  const selectFiles = useCallback(async (names: string[], files: H5FileEntry[]) => {
    const token = ++fileToken.current;
    setSelected(names);
    writeParams({ files: names.length > 0 ? names.join(',') : null });
    if (names.length === 0) {
      setData(null);
      setLoadingFile(false);
      return;
    }
    setLoadingFile(true);
    setError(null);
    try {
      const byName = new Map(files.map((f) => [f.filename, f]));
      const entries = names.map((n) => byName.get(n)).filter((e): e is H5FileEntry => !!e);
      const parsed = await Promise.all(entries.map(loadEntry));
      if (token !== fileToken.current) return;
      setData(mergeDatasets(parsed));
    } catch (e) {
      if (token !== fileToken.current) return;
      setData(null);
      setError(errorText(e));
    } finally {
      if (token === fileToken.current) setLoadingFile(false);
    }
  }, []);

  /** Přefiltruje soubory na zvolené období a vybere, co se má zobrazit. */
  const applyPeriod = useCallback(
    (files: H5FileEntry[], nextDate: string, nextMode: DayMode, wanted: string[]) => {
      const period = filterFilesByDate(files, inputToDateKey(nextDate), nextMode);
      setDayFiles(period);
      const available = new Set(period.map((f) => f.filename));
      const kept = wanted.filter((n) => available.has(n));
      void selectFiles(kept.length > 0 ? kept : period.slice(0, 1).map((f) => f.filename), period);
    },
    [selectFiles],
  );

  const openSource = useCallback(
    async (url: string, fromLink?: { date: string | null; files: string[] }) => {
      const token = ++listToken.current;
      const nextMode = readDayMode();
      setSource(url);
      setMode(nextMode);
      setLoadingList(true);
      setError(null);
      setAllFiles([]);
      setDayFiles([]);
      setSelected([]);
      setData(null);
      writeParams({ src: url, date: null, files: null });
      try {
        const files = await listSourceFiles(url);
        if (token !== listToken.current) return;
        setAllFiles(files);
        if (files.length === 0) {
          setError('V zadaném adresáři nejsou žádné soubory .h5.');
          return;
        }
        // Zdroj se zapamatuje, až když se z něj opravdu podařilo číst.
        setSources((list) => touchSource(list, url));
        const linkDate = fromLink?.date;
        const useLinkDate = !!linkDate && filterFilesByDate(files, inputToDateKey(linkDate), nextMode).length > 0;
        const nextDate = useLinkDate ? linkDate! : defaultDateInput(files, nextMode);
        setDate(nextDate);
        writeParams({ date: nextDate, mode: nextMode === 'night' ? 'night' : null });
        applyPeriod(files, nextDate, nextMode, fromLink?.files ?? []);
      } catch (e) {
        if (token !== listToken.current) return;
        setError(errorText(e));
      } finally {
        if (token === listToken.current) setLoadingList(false);
      }
    },
    [applyPeriod],
  );

  useEffect(() => {
    const fromUrl = normalizeSourceUrl(readSource() ?? '');
    if (fromUrl) void openSource(fromUrl, initialLink.current);
    // Spouští se jen jednou při otevření archivu.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const closeSource = () => {
    listToken.current++;
    fileToken.current++;
    setSource(null);
    setData(null);
    setError(null);
    setLoadingList(false);
    setLoadingFile(false);
    setSources(loadSources());
    writeParams({ src: null, date: null, mode: null, files: null });
  };

  const changeDate = (next: string) => {
    if (!next) return;
    setDate(next);
    writeParams({ date: next });
    applyPeriod(allFiles, next, mode, []);
  };

  const changeMode = (next: DayMode) => {
    setMode(next);
    const hasCurrent = filterFilesByDate(allFiles, inputToDateKey(date), next).length > 0;
    const nextDate = hasCurrent ? date : defaultDateInput(allFiles, next);
    setDate(nextDate);
    writeParams({ mode: next === 'night' ? 'night' : null, date: nextDate });
    applyPeriod(allFiles, nextDate, next, []);
  };

  const shiftDate = (days: number) => changeDate(dateKeyToInput(addDaysToDateKey(inputToDateKey(date), days)));

  const toggleFile = (name: string, checked: boolean) => {
    const next = new Set(selected);
    if (checked) next.add(name);
    else next.delete(name);
    void selectFiles(
      dayFiles.map((f) => f.filename).filter((n) => next.has(n)),
      dayFiles,
    );
  };

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setLinkCopied(true);
      setTimeout(() => setLinkCopied(false), 2000);
    } catch {
      setError('Nepodařilo se zkopírovat odkaz.');
    }
  };

  if (!source) {
    return (
      <SourcePicker
        sources={sources}
        onOpen={(url) => void openSource(url)}
        onPin={(url, pinned) => setSources((list) => setPinned(list, url, pinned))}
        onRemove={(url) => setSources((list) => removeSource(list, url))}
      />
    );
  }

  const busy = loadingList || loadingFile;
  const fileLabel = selected.length === 0 ? '—' : selected.length === 1 ? selected[0] : `${selected.length} souborů`;
  const saved = sources.find((s) => s.url === source);
  const hasFiles = allFiles.length > 0;

  return (
    <>
      <section className="source-bar">
        <div className="source-current">
          <span className="label">Zdroj</span>
          <span className="source-url">{source}</span>
        </div>
        <div className="source-actions">
          {saved && (
            <button
              type="button"
              className={saved.pinned ? 'active' : ''}
              aria-pressed={saved.pinned}
              onClick={() => setSources((list) => setPinned(list, source, !saved.pinned))}
            >
              {saved.pinned ? '★ Připnuto' : '☆ Připnout'}
            </button>
          )}
          {hasFiles && (
            <button type="button" onClick={() => void copyLink()}>
              {linkCopied ? 'Odkaz zkopírován' : 'Kopírovat odkaz'}
            </button>
          )}
          <button type="button" onClick={closeSource}>
            Změnit zdroj
          </button>
        </div>
      </section>

      {hasFiles && (
        <section className="selectors">
          <div className="station-selector">
            <label className="field">
              <span className="label">Režim</span>
              <select value={mode} onChange={(e) => changeMode(e.target.value as DayMode)} disabled={busy}>
                <option value="daytime">{MODE_LABEL.daytime}</option>
                <option value="night">{MODE_LABEL.night}</option>
              </select>
            </label>
            <label className="field">
              <span className="label">{periodLabel(mode)}</span>
              <span className="date-row">
                <button type="button" onClick={() => shiftDate(-1)} disabled={busy || !date} aria-label="Předchozí den">
                  ‹
                </button>
                <input type="date" value={date} onChange={(e) => changeDate(e.target.value)} disabled={busy} />
                <button type="button" onClick={() => shiftDate(1)} disabled={busy || !date} aria-label="Následující den">
                  ›
                </button>
              </span>
            </label>
          </div>

          <div className="file-selector">
            <div className="header">
              <span className="label">HDF5 soubory</span>
              <div className="actions">
                <button
                  type="button"
                  onClick={() =>
                    void selectFiles(
                      dayFiles.map((f) => f.filename),
                      dayFiles,
                    )
                  }
                  disabled={busy || dayFiles.length === 0}
                >
                  Vše
                </button>
                <button type="button" onClick={() => void selectFiles([], dayFiles)} disabled={busy || selected.length === 0}>
                  Žádný
                </button>
              </div>
            </div>
            <div className={`file-list ${busy ? 'disabled' : ''}`}>
              {dayFiles.map((file) => (
                <label className="file-item" key={file.url}>
                  <input
                    type="checkbox"
                    checked={selected.includes(file.filename)}
                    onChange={(e) => toggleFile(file.filename, e.target.checked)}
                    disabled={busy}
                  />
                  <span>
                    {file.source && <span className="source">{file.source}/</span>}
                    {file.filename}
                  </span>
                </label>
              ))}
            </div>
            <span className="selection-count">
              Vybráno: {selected.length} / {dayFiles.length}
            </span>
          </div>
        </section>
      )}

      {busy && <div className="status-banner">Načítám data…</div>}
      {error && <div className="error-banner">{error}</div>}
      {!busy && !error && hasFiles && dayFiles.length === 0 && (
        <div className="status-banner">Pro vybraný den nejsou dostupná žádná HDF5 data.</div>
      )}

      {data && (
        <DatasetView
          group="archive"
          data={data}
          info={[
            { label: 'Režim', value: MODE_LABEL[mode] },
            { label: 'Období', value: periodDescription(mode, date) },
            { label: 'Soubory', value: fileLabel },
          ]}
        />
      )}
    </>
  );
}
