import { useRef, useState, type DragEvent } from "react";
import { Button } from "@/components/Button";
import { AlertIcon, CheckIcon, RefreshIcon, UploadIcon, XIcon } from "@/components/Icons";
import { Alert, ProgressBar } from "@/components/States";
import { formatBytes, formatNumber, plural } from "@/lib/format";
import { useAdminApi } from "./AuthContext";
import { filesFromDataTransfer, useUploader } from "./useUploader";

export function UploadPanel({ eventId, onUploaded }: { eventId: string; onUploaded: () => void }) {
  const api = useAdminApi();
  const { progress, summary, upload, cancel, dismiss } = useUploader(api, eventId, onUploaded);
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [showDetails, setShowDetails] = useState(false);

  async function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    if (progress.running) return;
    const files = await filesFromDataTransfer(e.dataTransfer);
    if (files.length) void upload(files);
  }

  return (
    <section className="card p-5" aria-labelledby="upload-heading">
      <h2 id="upload-heading" className="font-semibold">
        Upload photos &amp; videos
      </h2>

      {progress.running ? (
        <div className="mt-4 space-y-3" aria-live="polite">
          <ProgressBar value={progress.bytesTotal ? progress.bytesSent / progress.bytesTotal : 0} label="Upload progress" />
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <span className="text-ink-muted">
              Uploaded {formatNumber(progress.filesDone)} of {formatNumber(progress.filesTotal)} files ·{" "}
              {formatBytes(progress.bytesSent)} / {formatBytes(progress.bytesTotal)}
            </span>
            <Button variant="secondary" size="sm" icon={<XIcon />} onClick={cancel}>
              Cancel
            </Button>
          </div>
          <p className="text-xs text-ink-subtle">Keep this tab open. Indexing starts as soon as each batch arrives.</p>
        </div>
      ) : (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`mt-4 flex flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition-colors ${
            dragging ? "border-primary bg-primary-50" : "border-line-strong bg-background"
          }`}
        >
          <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary-50 text-2xl text-primary">
            <UploadIcon />
          </span>
          <p className="mt-3 font-semibold text-ink">Drag &amp; drop photos, videos or folders here</p>
          <p className="mt-1 text-sm text-ink-muted">Photos: JPEG, PNG, WebP, HEIC up to 30 MB · Videos: MP4, MOV, WebM up to 500 MB</p>
          <Button className="mt-4" icon={<UploadIcon />} onClick={() => input.current?.click()}>
            Choose files
          </Button>
          <input
            ref={input}
            type="file"
            multiple
            accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif,video/mp4,video/quicktime,video/webm,video/x-matroska,video/x-msvideo,.mp4,.m4v,.mov,.webm,.mkv,.avi,.3gp"
            className="sr-only"
            tabIndex={-1}
            aria-hidden="true"
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = "";
              if (files.length) void upload(files);
            }}
          />
        </div>
      )}

      {summary ? (
        <div className="mt-4 space-y-3">
          <Alert tone={summary.failed.length || summary.rejected.length ? "warning" : "success"} icon={summary.failed.length ? <AlertIcon /> : <CheckIcon />}>
            <div className="flex items-start justify-between gap-3">
              <p>
                {summary.cancelled ? "Upload cancelled. " : ""}
                <strong>{plural(summary.accepted, "file")}</strong> uploaded
                {summary.duplicates.length ? ` · ${summary.duplicates.length} duplicates skipped` : ""}
                {summary.rejected.length ? ` · ${summary.rejected.length} rejected` : ""}
                {summary.failed.length ? ` · ${summary.failed.length} failed` : ""}
              </p>
              <button type="button" onClick={dismiss} className="shrink-0 rounded-lg p-1 text-base opacity-70 hover:opacity-100" aria-label="Dismiss upload summary">
                <XIcon />
              </button>
            </div>
            {summary.rejected.length || summary.duplicates.length ? (
              <button type="button" className="mt-1 text-sm font-semibold underline" onClick={() => setShowDetails((v) => !v)} aria-expanded={showDetails}>
                {showDetails ? "Hide details" : "Show details"}
              </button>
            ) : null}
            {showDetails ? (
              <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto text-xs">
                {summary.rejected.map((r, i) => (
                  <li key={`r${i}`}>
                    <strong>{r.filename}</strong>: {r.error}
                  </li>
                ))}
                {summary.duplicates.map((d, i) => (
                  <li key={`d${i}`}>
                    <strong>{d}</strong>: already in this event
                  </li>
                ))}
              </ul>
            ) : null}
          </Alert>
          {summary.failed.length ? (
            <Button variant="secondary" icon={<RefreshIcon />} onClick={() => void upload(summary.failed)}>
              Retry {plural(summary.failed.length, "failed upload")}
            </Button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
