import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Button } from "@/components/Button";
import { AlertIcon, ArrowLeftIcon, ClockIcon, EditIcon, ImageIcon, PlayIcon, RefreshIcon, StarIcon, TrashIcon, VideoIcon } from "@/components/Icons";
import { Lightbox, type LightboxPhoto } from "@/components/Lightbox";
import { ConfirmDialog } from "@/components/Modal";
import { Spinner } from "@/components/Spinner";
import { Alert, Badge, EmptyState, ErrorState, ProgressBar, Skeleton, errorMessage } from "@/components/States";
import type { AdminEvent, AdminPhoto, PhotoStatus } from "@/lib/api";
import { formatDate, formatDuration, formatNumber, plural } from "@/lib/format";
import { useAsync, useInterval } from "@/lib/useAsync";
import { useAdminApi } from "./AuthContext";
import { EventFormModal } from "./EventFormModal";
import { PublishToggle } from "./PublishToggle";
import { UploadPanel } from "./UploadPanel";

const PAGE_SIZE = 60;
const STATUS_TABS: { key: PhotoStatus | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "done", label: "Done" },
  { key: "queued", label: "Queued" },
  { key: "processing", label: "Processing" },
  { key: "failed", label: "Failed" },
];

const STATUS_BADGE: Record<PhotoStatus, { tone: "success" | "warning" | "primary" | "danger"; label: string }> = {
  done: { tone: "success", label: "Done" },
  queued: { tone: "warning", label: "Queued" },
  processing: { tone: "primary", label: "Processing" },
  failed: { tone: "danger", label: "Failed" },
};

export function EventDetailPage() {
  const { id = "" } = useParams();
  const api = useAdminApi();
  const navigate = useNavigate();

  const event = useAsync((signal) => api.getEvent(id, signal), [api, id]);
  const status = useAsync((signal) => api.status(id, signal), [api, id]);
  const [statusFilter, setStatusFilter] = useState<PhotoStatus | "all">("all");
  const [page, setPage] = useState(1);
  const photos = useAsync(
    (signal) => api.listPhotos(id, page, PAGE_SIZE, statusFilter === "all" ? undefined : statusFilter, signal),
    [api, id, page, statusFilter],
  );

  const [editOpen, setEditOpen] = useState(false);
  const [confirm, setConfirm] = useState<null | "delete-event" | "reindex" | { photo: AdminPhoto }>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ tone: "success" | "danger"; text: string } | null>(null);
  const [viewing, setViewing] = useState<number | null>(null);

  // Live indexing progress: poll every 3 s.
  useInterval(status.reload, 3000);

  // Refresh the grid whenever processed counts change.
  const signature = status.data ? `${status.data.total}-${status.data.done}-${status.data.failed}` : "";
  useEffect(() => {
    if (signature) photos.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  const ev = event.data;
  const st = status.data;
  const pending = st ? st.queued + st.processing : 0;
  const totalPages = photos.data ? Math.max(1, Math.ceil(photos.data.total / PAGE_SIZE)) : 1;

  const viewerItems: LightboxPhoto[] = useMemo(
    () =>
      (photos.data?.items ?? [])
        .filter((p) => p.status === "done")
        .map((p) => ({
          id: p.id,
          fullUrl: p.full_url,
          thumbUrl: p.thumb_url,
          alt: p.original_filename,
          downloadUrl: (p.media_type === "video" ? p.video_url : p.full_url) ?? "",
          videoUrl: p.media_type === "video" ? p.video_url : null,
        })),
    [photos.data],
  );

  const progressValue = useMemo(() => (st && st.total ? (st.done + st.failed) / st.total : 0), [st]);

  async function update(patch: Parameters<typeof api.updateEvent>[1], okText?: string) {
    setNotice(null);
    try {
      event.setData(await api.updateEvent(id, patch));
      if (okText) setNotice({ tone: "success", text: okText });
    } catch (err) {
      setNotice({ tone: "danger", text: errorMessage(err) });
    }
  }

  async function runConfirmed() {
    if (!confirm) return;
    setBusy(true);
    setNotice(null);
    try {
      if (confirm === "delete-event") {
        await api.deleteEvent(id);
        navigate("/admin/events", { replace: true });
        return;
      }
      if (confirm === "reindex") {
        const r = await api.reindex(id);
        setNotice({ tone: "success", text: `Re-indexing ${plural(r.queued, "photo")}.` });
      } else {
        await api.deletePhoto(confirm.photo.id);
        if (ev?.cover_photo_id === confirm.photo.id) event.reload();
        setNotice({ tone: "success", text: "Photo deleted." });
      }
      status.reload();
      photos.reload();
    } catch (err) {
      setNotice({ tone: "danger", text: errorMessage(err) });
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  }

  async function retryFailed() {
    setNotice(null);
    try {
      const r = await api.retryFailed(id);
      setNotice({ tone: "success", text: `Retrying ${plural(r.queued, "photo")}.` });
      status.reload();
      photos.reload();
    } catch (err) {
      setNotice({ tone: "danger", text: errorMessage(err) });
    }
  }

  if (event.error && !ev) {
    return (
      <div className="card">
        <ErrorState error={event.error} onRetry={event.reload} title="Couldn't load this event" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Link to="/admin/events" className="inline-flex items-center gap-1.5 rounded-lg text-sm font-medium text-ink-muted hover:text-ink">
        <ArrowLeftIcon /> All events
      </Link>

      {/* Header */}
      {!ev ? (
        <div className="card flex items-center gap-4 p-5">
          <Skeleton className="h-20 w-20" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-4 w-1/4" />
          </div>
        </div>
      ) : (
        <div className="card flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
          <div className="h-20 w-20 shrink-0 overflow-hidden rounded-2xl bg-primary-50">
            {ev.cover_thumb_url ? (
              <img src={ev.cover_thumb_url} alt={`Cover of ${ev.name}`} className="h-full w-full object-cover" />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-3xl text-primary-300" title="No cover photo yet">
                <ImageIcon />
              </div>
            )}
          </div>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-2xl font-bold tracking-tight">{ev.name}</h1>
            <p className="text-sm text-ink-muted">
              {formatDate(ev.event_date)} · {ev.type}
            </p>
            {ev.description ? <p className="mt-1 line-clamp-2 text-sm text-ink-subtle">{ev.description}</p> : null}
            {!ev.cover_photo_id ? (
              <p className="mt-1 inline-flex items-center gap-1 text-xs text-ink-subtle">
                <StarIcon /> {ev.cover_thumb_url ? "Thumbnail is picked automatically." : "No thumbnail yet."} Hover any photo or video below and click the star to choose one.
              </p>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <PublishToggle
              published={ev.is_published}
              label={`Publish ${ev.name}`}
              onChange={(next) => update({ is_published: next }, next ? "Event published — guests can now search it." : "Event unpublished.")}
            />
            <Button variant="secondary" size="sm" icon={<EditIcon />} onClick={() => setEditOpen(true)}>
              Edit
            </Button>
            <Button variant="ghost" size="sm" icon={<TrashIcon />} onClick={() => setConfirm("delete-event")}>
              Delete
            </Button>
          </div>
        </div>
      )}

      {notice ? <Alert tone={notice.tone}>{notice.text}</Alert> : null}

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <UploadPanel eventId={id} onUploaded={() => status.reload()} />
        </div>

        {/* Indexing progress */}
        <section className="card p-5 lg:col-span-2" aria-labelledby="progress-heading">
          <div className="flex items-center justify-between">
            <h2 id="progress-heading" className="font-semibold">
              Indexing
            </h2>
            {pending > 0 ? (
              <span className="inline-flex items-center gap-1.5 text-sm text-primary">
                <Spinner className="h-4 w-4" /> Working
              </span>
            ) : null}
          </div>
          {!st ? (
            <div className="mt-4 space-y-3">
              <Skeleton className="h-2 w-full" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : (
            <div className="mt-4 space-y-4" aria-live="polite">
              <ProgressBar value={progressValue} label="Indexing progress" tone={pending === 0 && st.total > 0 ? "success" : "primary"} />
              <dl className="grid grid-cols-2 gap-2 text-sm">
                {(
                  [
                    ["Queued", st.queued, "text-warning"],
                    ["Processing", st.processing, "text-primary"],
                    ["Done", st.done, "text-success"],
                    ["Failed", st.failed, "text-danger"],
                  ] as const
                ).map(([label, n, color]) => (
                  <div key={label} className="rounded-xl bg-background px-3 py-2">
                    <dt className="text-xs text-ink-subtle">{label}</dt>
                    <dd className={`text-lg font-bold tabular-nums ${n > 0 ? color : "text-ink"}`}>{formatNumber(n)}</dd>
                  </div>
                ))}
              </dl>
              <p className="text-sm text-ink-muted">
                <strong className="text-ink">{formatNumber(st.faces)}</strong> faces found in {plural(st.total, "file")}
              </p>
              <div className="flex flex-wrap gap-2">
                {st.failed > 0 ? (
                  <Button variant="soft" size="sm" icon={<RefreshIcon />} onClick={retryFailed}>
                    Retry failed ({st.failed})
                  </Button>
                ) : null}
                <Button variant="secondary" size="sm" icon={<RefreshIcon />} onClick={() => setConfirm("reindex")} disabled={st.total === 0}>
                  Re-index event
                </Button>
              </div>
            </div>
          )}
        </section>
      </div>

      {/* Photos */}
      <section aria-labelledby="photos-heading" className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="photos-heading" className="text-lg font-semibold">
            Photos &amp; videos {photos.data ? <span className="text-ink-subtle">· {formatNumber(photos.data.total)}</span> : null}
          </h2>
          <div className="flex gap-1 overflow-x-auto scrollbar-none" role="group" aria-label="Filter photos by status">
            {STATUS_TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                aria-pressed={statusFilter === t.key}
                onClick={() => {
                  setStatusFilter(t.key);
                  setPage(1);
                }}
                className={`shrink-0 rounded-full px-3 py-1.5 text-sm font-semibold ${
                  statusFilter === t.key ? "bg-primary text-white" : "bg-surface text-ink-muted ring-1 ring-inset ring-line hover:text-ink"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {photos.loading && !photos.data ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
            {Array.from({ length: 12 }, (_, i) => (
              <Skeleton key={i} className="aspect-square" />
            ))}
          </div>
        ) : photos.error && !photos.data ? (
          <div className="card">
            <ErrorState error={photos.error} onRetry={photos.reload} title="Couldn't load photos" />
          </div>
        ) : (photos.data?.items.length ?? 0) === 0 ? (
          <div className="card">
            <EmptyState
              icon={<ImageIcon />}
              title={statusFilter === "all" ? "No photos yet" : `No ${statusFilter} photos`}
              description={statusFilter === "all" ? "Upload photos above — faces are indexed automatically." : undefined}
            />
          </div>
        ) : (
          <>
            <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
              {photos.data!.items.map((p) => (
                <PhotoCard
                  key={p.id}
                  photo={p}
                  isCover={ev?.cover_photo_id === p.id}
                  onSetCover={() => update({ cover_photo_id: p.id }, "Event thumbnail updated.")}
                  onOpen={() => {
                    const i = viewerItems.findIndex((v) => v.id === p.id);
                    if (i >= 0) setViewing(i);
                  }}
                  onDelete={() => setConfirm({ photo: p })}
                />
              ))}
            </ul>
            {totalPages > 1 ? (
              <nav className="flex items-center justify-center gap-3" aria-label="Photo pages">
                <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                  Previous
                </Button>
                <span className="text-sm text-ink-muted tabular-nums">
                  Page {page} of {totalPages}
                </span>
                <Button variant="secondary" size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
                  Next
                </Button>
              </nav>
            ) : null}
          </>
        )}
      </section>

      {viewing !== null && viewerItems[viewing] ? (
        <Lightbox photos={viewerItems} index={viewing} onIndexChange={setViewing} onClose={() => setViewing(null)} />
      ) : null}

      <EventFormModal
        open={editOpen}
        event={ev as AdminEvent | undefined}
        onClose={() => setEditOpen(false)}
        onSubmit={async (input) => {
          event.setData(await api.updateEvent(id, input));
        }}
      />

      <ConfirmDialog
        open={confirm !== null}
        danger={confirm !== "reindex"}
        loading={busy}
        title={
          confirm === "delete-event"
            ? `Delete “${ev?.name ?? ""}”?`
            : confirm === "reindex"
              ? "Re-index all photos?"
              : "Delete this photo?"
        }
        description={
          confirm === "delete-event"
            ? `This permanently deletes the event, ${plural(st?.total ?? 0, "photo")} and all face data. This cannot be undone.`
            : confirm === "reindex"
              ? "Face detection runs again for every photo in this event. Matches stay available while it runs."
              : "The photo and its face data are permanently removed."
        }
        confirmLabel={confirm === "reindex" ? "Re-index" : "Delete"}
        onConfirm={runConfirmed}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}

function PhotoCard({
  photo,
  isCover,
  onSetCover,
  onDelete,
  onOpen,
}: {
  photo: AdminPhoto;
  isCover: boolean;
  onSetCover: () => void;
  onDelete: () => void;
  onOpen: () => void;
}) {
  const badge = STATUS_BADGE[photo.status];
  const isVideo = photo.media_type === "video";
  return (
    <li className="group overflow-hidden rounded-2xl bg-surface shadow-soft">
      <div className="relative aspect-square bg-background">
        {photo.thumb_url ? (
          <button type="button" onClick={onOpen} className="block h-full w-full" aria-label={`View ${photo.original_filename}`}>
            <img src={photo.thumb_url} alt={photo.original_filename} loading="lazy" className="h-full w-full object-cover" />
            {isVideo ? (
              <span className="pointer-events-none absolute inset-0 flex items-center justify-center">
                <span className="flex h-11 w-11 items-center justify-center rounded-full bg-black/55 text-lg text-white">
                  <PlayIcon />
                </span>
              </span>
            ) : null}
          </button>
        ) : (
          <div className="flex h-full w-full items-center justify-center text-3xl text-ink-subtle">
            {photo.status === "failed" ? <AlertIcon className="text-danger" /> : photo.status === "processing" ? <Spinner className="h-7 w-7 text-primary" /> : <ClockIcon />}
          </div>
        )}
        <div className="absolute left-2 top-2 flex gap-1">
          <Badge tone={badge.tone}>{badge.label}</Badge>
          {isVideo ? (
            <Badge>
              <VideoIcon /> {photo.duration ? formatDuration(photo.duration) : "Video"}
            </Badge>
          ) : null}
          {isCover ? (
            <Badge tone="primary">
              <StarIcon /> Cover
            </Badge>
          ) : null}
        </div>
        <div className="absolute right-2 top-2 flex gap-1 opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
          {photo.status === "done" && !isCover ? (
            <button
              type="button"
              onClick={onSetCover}
              className="flex h-8 w-8 items-center justify-center rounded-full bg-surface/95 text-ink shadow-soft hover:text-primary"
              aria-label={`Use ${photo.original_filename} as event thumbnail`}
              title="Use as event thumbnail"
            >
              <StarIcon />
            </button>
          ) : null}
          <button
            type="button"
            onClick={onDelete}
            className="flex h-8 w-8 items-center justify-center rounded-full bg-surface/95 text-ink shadow-soft hover:text-danger"
            aria-label={`Delete ${photo.original_filename}`}
            title="Delete photo"
          >
            <TrashIcon />
          </button>
        </div>
      </div>
      <div className="px-3 py-2">
        <p className="truncate text-xs font-medium text-ink" title={photo.original_filename}>
          {photo.original_filename}
        </p>
        {photo.status === "failed" ? (
          <p className="mt-0.5 line-clamp-2 text-xs text-danger" title={photo.error ?? undefined}>
            {photo.error ?? "Indexing failed"}
          </p>
        ) : (
          <p className="mt-0.5 text-xs text-ink-subtle">
            {photo.status === "done" ? plural(photo.face_count, isVideo ? "person" : "face", isVideo ? "people" : "faces") : isVideo ? "Scanning video for faces" : "Waiting for indexing"}
          </p>
        )}
      </div>
    </li>
  );
}
