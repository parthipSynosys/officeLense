/**
 * Client-side ZIP downloads with JSZip. Photos are fetched from /photos/ (same
 * origin), stored without re-compression (JPEGs don't shrink), and saved.
 */
import JSZip from "jszip";

export interface ZipItem {
  url: string;
  filename: string;
}

export type ZipPhase = "fetching" | "zipping";

export interface ZipProgress {
  phase: ZipPhase;
  done: number;
  total: number;
  /** 0..1 across both phases (fetching = first 85%). */
  fraction: number;
}

const CONCURRENCY = 4;

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Give the browser time to start the download before revoking.
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

/** Fetch all items, build a ZIP and trigger the download. Returns the number of failed files. */
export async function downloadZip(
  items: ZipItem[],
  zipName: string,
  onProgress: (p: ZipProgress) => void,
  signal?: AbortSignal,
): Promise<{ failed: number }> {
  const zip = new JSZip();
  const total = items.length;
  let done = 0;
  let failed = 0;
  let next = 0;

  const report = () =>
    onProgress({ phase: "fetching", done, total, fraction: total ? (done / total) * 0.85 : 0.85 });
  report();

  async function worker() {
    while (next < items.length) {
      if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");
      const item = items[next++];
      try {
        const res = await fetch(item.url, { signal });
        if (!res.ok) throw new Error(String(res.status));
        zip.file(item.filename, await res.blob(), { binary: true });
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") throw err;
        failed += 1;
      }
      done += 1;
      report();
    }
  }

  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, items.length) }, worker));
  if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");

  const blob = await zip.generateAsync({ type: "blob", compression: "STORE", streamFiles: true }, (meta) => {
    onProgress({ phase: "zipping", done, total, fraction: 0.85 + (meta.percent / 100) * 0.15 });
  });
  if (signal?.aborted) throw new DOMException("Cancelled", "AbortError");
  saveBlob(blob, zipName.endsWith(".zip") ? zipName : `${zipName}.zip`);
  return { failed };
}
