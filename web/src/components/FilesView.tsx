import { useRef, useState } from 'react';
import { parseH5 } from '../lib/hdf5';
import { mergeDatasets } from '../lib/merge';
import type { Dataset } from '../lib/types';
import { DatasetView } from './DatasetView';

interface Props {
  data: Dataset | null;
  onData(data: Dataset | null): void;
}

/** Prohlížení HDF5 logů z disku — soubory se zpracují v prohlížeči, nikam se neodesílají. */
export function FilesView({ data, onData }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const token = useRef(0);

  const open = async (list: FileList | null) => {
    const files = Array.from(list ?? []).filter((f) => /\.(h5|hdf5)$/i.test(f.name));
    if (files.length === 0) {
      if (list && list.length > 0) setError('Vyberte soubory s příponou .h5 nebo .hdf5.');
      return;
    }
    const current = ++token.current;
    setLoading(true);
    setError(null);
    try {
      const parsed = await Promise.all(files.map(async (f) => parseH5(f.name, await f.arrayBuffer())));
      if (current !== token.current) return;
      onData(mergeDatasets(parsed));
    } catch (e) {
      if (current !== token.current) return;
      setError(e instanceof Error ? e.message : 'Soubor se nepodařilo načíst.');
    } finally {
      if (current === token.current) setLoading(false);
    }
  };

  return (
    <>
      <section
        className={`drop-zone ${dragging ? 'dragging' : ''}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void open(e.dataTransfer.files);
        }}
      >
        <div>
          <strong>Přetáhněte sem HDF5 logy</strong> nebo je vyberte z disku. Více souborů se spojí do jedné časové řady.
          <div className="hint">
            Fungují logy z <code>amsky-viewer --log</code>, z této aplikace i starší logy AMSKY01.
          </div>
        </div>
        <div className="drop-actions">
          <button type="button" className="primary" onClick={() => inputRef.current?.click()} disabled={loading}>
            Vybrat soubory…
          </button>
          {data && (
            <button type="button" onClick={() => onData(null)} disabled={loading}>
              Zavřít
            </button>
          )}
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".h5,.hdf5"
          multiple
          hidden
          onChange={(e) => {
            void open(e.target.files);
            e.target.value = '';
          }}
        />
      </section>

      {loading && <div className="status-banner">Načítám data…</div>}
      {error && <div className="error-banner">{error}</div>}
      {data && <DatasetView group="files" data={data} info={[{ label: 'Zdroj', value: data.label }]} />}
    </>
  );
}
