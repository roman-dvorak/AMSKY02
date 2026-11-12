import { useEffect, useState } from 'react';
import { ArchiveView } from './components/ArchiveView';
import { FilesView } from './components/FilesView';
import { LiveView } from './components/LiveView';
import type { Dataset } from './lib/types';
import type { View } from './lib/urlState';
import { readView, writeParams } from './lib/urlState';

const TABS: { id: View; label: string; subtitle: string }[] = [
  { id: 'live', label: 'Živě', subtitle: 'Živá data ze senzoru připojeného přes USB' },
  { id: 'archive', label: 'Archiv', subtitle: 'HDF5 logy z adresáře na webu' },
  { id: 'files', label: 'Soubory', subtitle: 'HDF5 logy z vašeho disku' },
];

const ARCHIVE_PARAMS = { src: null, station: null, date: null, mode: null, files: null };

export function App() {
  const [view, setView] = useState<View>(readView);
  const [localData, setLocalData] = useState<Dataset | null>(null);
  // Archiv se připojuje k serveru až při prvním otevření a pak zůstává
  // načtený, aby přepnutí záložky neztratilo výběr.
  const [archiveOpened, setArchiveOpened] = useState(view === 'archive');

  useEffect(() => {
    if (view === 'archive') setArchiveOpened(true);
    // Parametry archivu patří jen k archivu; jinde by v odkazu mátly.
    writeParams(view === 'archive' ? { view: 'archive' } : { view, ...ARCHIVE_PARAMS });
  }, [view]);

  const current = TABS.find((tab) => tab.id === view)!;

  return (
    <div className="app-shell">
      <header className="top-bar">
        <div className="title-block">
          <h1>AMSKY Viewer</h1>
          <p className="subtitle">{current.subtitle}</p>
        </div>
        <nav className="tabs" aria-label="Zdroj dat">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={tab.id === view ? 'active' : ''}
              aria-current={tab.id === view ? 'page' : undefined}
              onClick={() => setView(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>

      <main className="view" hidden={view !== 'live'}>
        <LiveView
          onOpenRecording={(data) => {
            setLocalData(data);
            setView('files');
          }}
        />
      </main>
      {archiveOpened && (
        <main className="view" hidden={view !== 'archive'}>
          <ArchiveView />
        </main>
      )}
      {view === 'files' && (
        <main className="view">
          <FilesView data={localData} onData={setLocalData} />
        </main>
      )}

      <footer className="footer">
        <a href="https://astrometers.eu/products/AMSKY02/">AMSKY02</a>
        <a href="https://astrometers.eu/docs/AMSKY/">Dokumentace</a>
        <a href="https://github.com/roman-dvorak/AMSKY02">Zdrojový kód</a>
      </footer>
    </div>
  );
}
