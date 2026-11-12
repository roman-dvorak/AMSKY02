import { useEffect, useState } from 'react';
import { ArchiveView } from './components/ArchiveView';
import { FilesView } from './components/FilesView';
import { LiveView } from './components/LiveView';
import type { Dataset } from './lib/types';
import type { View } from './lib/urlState';
import { readView, writeParams } from './lib/urlState';

const TABS: { id: View; label: string; subtitle: string }[] = [
  { id: 'live', label: 'Live', subtitle: 'Live data from a sensor' },
  { id: 'archive', label: 'Archive', subtitle: 'HDF5 logs from a web directory' },
  { id: 'files', label: 'Files', subtitle: 'HDF5 logs from your disk' },
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
        <div className="brand">
          <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
            <circle cx="16" cy="16" r="15" fill="#0f1626" stroke="currentColor" strokeWidth="1.5" />
            <path d="M5 21a11 11 0 0 1 22 0" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <circle cx="11" cy="12" r="1.3" fill="#f0b849" />
            <circle cx="20" cy="8.5" r="1" fill="#f0b849" />
            <circle cx="23" cy="15" r="0.9" fill="#f0b849" />
          </svg>
          <div className="title-block">
            <h1>AMSKY Viewer</h1>
            <p className="subtitle">{current.subtitle}</p>
          </div>
        </div>
        <nav className="tabs" aria-label="Data source">
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
        <a href="https://astrometers.eu/docs/AMSKY/">Documentation</a>
        <a href="https://github.com/roman-dvorak/AMSKY02">Source code</a>
      </footer>
    </div>
  );
}
