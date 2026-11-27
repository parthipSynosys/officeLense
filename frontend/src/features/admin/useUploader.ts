/**
 * Chunked bulk uploader: files are sent in small batches (max 5 files / 60 MB)
 * with 2 batches in flight. Each batch retries transient failures (network,
 * 5xx, 429) with backoff, so one failure never stops the rest.
 */
import { useCallback, useRef, useState } from "react";
import { ApiError, type AdminApi } from "@/lib/api";

export const MAX_FILE_BYTES = 30 * 1024 * 1024;
export const MAX_VIDEO_BYTES = 500 * 1024 * 1024;
const BATCH_FILES = 5;
const BATCH_BYTES = 60 * 1024 * 1024;
const CONCURRENCY = 2;
const RETRIES = 3;
const IMAGE_EXT = /\.(jpe?g|png|webp|heic|heif)$/i;
const VIDEO_EXT = /\.(mp4|m4v|mov|webm|mkv|avi|3gp)$/i;

export function isVideoFile(f: File): boolean {
  return VIDEO_EXT.test(f.name) || f.type.startsWith("video/");
}

function isImageFile(f: File): boolean {
  return IMAGE_EXT.test(f.name) || f.type.startsWith("image/");
}

export interface UploadProgress {
  running: boolean;
  filesTotal: number;
  filesDone: number;
  bytesTotal: number;
  bytesSent: number;
}

export interface UploadSummary {
  accepted: number;
  duplicates: string[];
  rejected: { filename: string; error: string }[];
  failed: File[]; // batches that failed after retries — can be retried
  cancelled: boolean;
}

const IDLE: UploadProgress = { running: false, filesTotal: 0, filesDone: 0, bytesTotal: 0, bytesSent: 0 };

function chunk(files: File[]): File[][] {
  const batches: File[][] = [];
  let cur: File[] = [];
  let bytes = 0;
  for (const f of files) {
    if (cur.length && (cur.length >= BATCH_FILES || bytes + f.size > BATCH_BYTES)) {
      batches.push(cur);
      cur = [];
      bytes = 0;
    }
    cur.push(f);
    bytes += f.size;
  }
  if (cur.length) batches.push(cur);
  return batches;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function isTransient(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 0 || err.status >= 500 || err.status === 429);
}

export function useUploader(api: AdminApi, eventId: string, onBatchDone?: () => void) {
  const [progress, setProgress] = useState<UploadProgress>(IDLE);
  const [summary, setSummary] = useState<UploadSummary | null>(null);
  const ctrlRef = useRef<AbortController | null>(null);

  const upload = useCallback(
    async (input: File[]) => {
      if (ctrlRef.current) return; // already running
      const ctrl = new AbortController();
      ctrlRef.current = ctrl;

      const result: UploadSummary = { accepted: 0, duplicates: [], rejected: [], failed: [], cancelled: false };
      const valid: File[] = [];
      for (const f of input) {
        const video = isVideoFile(f);
        if (!video && !isImageFile(f)) result.rejected.push({ filename: f.name, error: "Not a photo or video" });
        else if (video && f.size > MAX_VIDEO_BYTES) result.rejected.push({ filename: f.name, error: "Video larger than 500 MB" });
        else if (!video && f.size > MAX_FILE_BYTES) result.rejected.push({ filename: f.name, error: "Larger than 30 MB" });
        else valid.push(f);
      }

      const batches = chunk(valid);
      const bytesTotal = valid.reduce((n, f) => n + f.size, 0);
      let bytesDone = 0;
      let filesDone = 0;
      const inFlight = new Map<number, number>();
      const report = () => {
        const sent = bytesDone + Array.from(inFlight.values()).reduce((a, b) => a + b, 0);
        setProgress({ running: true, filesTotal: valid.length, filesDone, bytesTotal, bytesSent: Math.min(sent, bytesTotal) });
      };
      setSummary(null);
      report();

      let next = 0;
      async function worker() {
        while (next < batches.length && !ctrl.signal.aborted) {
          const idx = next++;
          const batch = batches[idx];
          const size = batch.reduce((n, f) => n + f.size, 0);
          let attempt = 0;
          for (;;) {
            try {
              const res = await api.uploadPhotos(
                eventId,
                batch,
                (loaded, total) => {
                  // `total` includes multipart overhead; scale to file bytes.
                  inFlight.set(idx, total ? (loaded / total) * size : 0);
                  report();
                },
                ctrl.signal,
              );
              result.accepted += res.accepted.length;
              result.duplicates.push(...res.duplicates);
              result.rejected.push(...res.rejected);
              break;
            } catch (err) {
              if (err instanceof DOMException && err.name === "AbortError") {
                inFlight.delete(idx);
                return;
              }
              if (isTransient(err) && attempt < RETRIES - 1) {
                attempt += 1;
                inFlight.set(idx, 0);
                report();
                await sleep(1000 * 2 ** attempt);
                continue;
              }
              if (err instanceof ApiError && !isTransient(err)) {
                batch.forEach((f) => result.rejected.push({ filename: f.name, error: err.message }));
              } else {
                result.failed.push(...batch);
              }
              break;
            }
          }
          inFlight.delete(idx);
          bytesDone += size;
          filesDone += batch.length;
          report();
          onBatchDone?.();
        }
      }

      await Promise.all(Array.from({ length: Math.min(CONCURRENCY, batches.length) }, worker));
      if (ctrl.signal.aborted) {
        result.cancelled = true;
        // Batches never started are offered for retry.
        result.failed.push(...batches.slice(next).flat());
      }
      ctrlRef.current = null;
      setProgress(IDLE);
      setSummary(result);
    },
    [api, eventId, onBatchDone],
  );

  const cancel = useCallback(() => ctrlRef.current?.abort(), []);
  const dismiss = useCallback(() => setSummary(null), []);

  return { progress, summary, upload, cancel, dismiss };
}

/** Collect files from a drop, including files inside dropped folders (recursive). */
export async function filesFromDataTransfer(dt: DataTransfer): Promise<File[]> {
  const entries = Array.from(dt.items ?? [])
    .map((item) => (item.kind === "file" ? item.webkitGetAsEntry?.() : null))
    .filter((e): e is FileSystemEntry => !!e);
  if (entries.length === 0) return Array.from(dt.files);

  const out: File[] = [];
  async function walk(entry: FileSystemEntry): Promise<void> {
    if (entry.isFile) {
      const file = await new Promise<File>((res, rej) => (entry as FileSystemFileEntry).file(res, rej));
      if (!file.name.startsWith(".")) out.push(file);
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      // readEntries returns results in chunks; call until empty.
      for (;;) {
        const batch = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej));
        if (batch.length === 0) break;
        for (const child of batch) await walk(child);
      }
    }
  }
  for (const e of entries) await walk(e);
  return out;
}
