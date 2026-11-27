import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Button } from "@/components/Button";
import { CalendarIcon, EditIcon, ImageIcon, PlusIcon, TrashIcon } from "@/components/Icons";
import { ConfirmDialog } from "@/components/Modal";
import { Alert, Badge, EmptyState, ErrorState, Skeleton, errorMessage } from "@/components/States";
import type { AdminEvent } from "@/lib/api";
import { formatDate, formatNumber, plural } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { useAdminApi } from "./AuthContext";
import { EventFormModal } from "./EventFormModal";
import { PublishToggle } from "./PublishToggle";

export function EventsPage() {
  const api = useAdminApi();
  const events = useAsync((signal) => api.listEvents(signal), [api]);
  const [params, setParams] = useSearchParams();
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<AdminEvent | null>(null);
  const [deleting, setDeleting] = useState<AdminEvent | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Support /admin/events?new=1 from the dashboard.
  useEffect(() => {
    if (params.get("new")) {
      setEditing(null);
      setFormOpen(true);
      setParams({}, { replace: true });
    }
  }, [params, setParams]);

  function replaceEvent(updated: AdminEvent) {
    events.setData((list) => (list ?? []).map((e) => (e.id === updated.id ? updated : e)));
  }

  async function togglePublish(e: AdminEvent, next: boolean) {
    setActionError(null);
    replaceEvent({ ...e, is_published: next }); // optimistic
    try {
      replaceEvent(await api.updateEvent(e.id, { is_published: next }));
    } catch (err) {
      replaceEvent(e);
      setActionError(errorMessage(err));
    }
  }

  async function confirmDelete() {
    if (!deleting) return;
    setBusy(true);
    try {
      await api.deleteEvent(deleting.id);
      events.setData((list) => (list ?? []).filter((x) => x.id !== deleting.id));
      setDeleting(null);
    } catch (err) {
      setActionError(errorMessage(err));
      setDeleting(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Events</h1>
          <p className="text-sm text-ink-muted">Create events, upload photos and publish them for guests.</p>
        </div>
        <Button
          icon={<PlusIcon />}
          onClick={() => {
            setEditing(null);
            setFormOpen(true);
          }}
        >
          New event
        </Button>
      </div>

      {actionError ? <Alert tone="danger">{actionError}</Alert> : null}

      {events.loading && !events.data ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="card flex items-center gap-4 p-4">
              <Skeleton className="h-16 w-16 shrink-0" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-4 w-1/3" />
                <Skeleton className="h-3 w-1/4" />
              </div>
            </div>
          ))}
        </div>
      ) : events.error && !events.data ? (
        <div className="card">
          <ErrorState error={events.error} onRetry={events.reload} title="Couldn't load events" />
        </div>
      ) : (events.data ?? []).length === 0 ? (
        <div className="card">
          <EmptyState
            icon={<CalendarIcon />}
            title="No events yet"
            description="Create your first event, then upload its photos."
            action={
              <Button icon={<PlusIcon />} onClick={() => setFormOpen(true)}>
                Create event
              </Button>
            }
          />
        </div>
      ) : (
        <ul className="space-y-3">
          {(events.data ?? []).map((e) => (
            <li key={e.id} className="card flex flex-col gap-4 p-4 sm:flex-row sm:items-center">
              <Link to={`/admin/events/${e.id}`} className="flex min-w-0 flex-1 items-center gap-4 rounded-xl">
                <div className="h-16 w-16 shrink-0 overflow-hidden rounded-xl bg-primary-50">
                  {e.cover_thumb_url ? (
                    <img src={e.cover_thumb_url} alt="" className="h-full w-full object-cover" loading="lazy" />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-2xl text-primary-300">
                      <ImageIcon />
                    </div>
                  )}
                </div>
                <div className="min-w-0">
                  <p className="truncate font-semibold text-ink">{e.name}</p>
                  <p className="mt-0.5 text-sm text-ink-muted">
                    {formatDate(e.event_date)} · {e.type}
                  </p>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    <Badge>{plural(e.photo_count, "photo")}</Badge>
                    <Badge tone="primary">{formatNumber(e.face_count)} faces</Badge>
                    {e.failed_count > 0 ? <Badge tone="danger">{e.failed_count} failed</Badge> : null}
                    {e.photo_count - e.done_count - e.failed_count > 0 ? (
                      <Badge tone="warning">{e.photo_count - e.done_count - e.failed_count} indexing</Badge>
                    ) : null}
                  </div>
                </div>
              </Link>
              <div className="flex items-center justify-between gap-2 sm:justify-end">
                <PublishToggle published={e.is_published} onChange={(next) => togglePublish(e, next)} label={`Publish ${e.name}`} />
                <div className="flex gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<EditIcon />}
                    aria-label={`Edit ${e.name}`}
                    onClick={() => {
                      setEditing(e);
                      setFormOpen(true);
                    }}
                  />
                  <Button variant="ghost" size="sm" icon={<TrashIcon />} aria-label={`Delete ${e.name}`} onClick={() => setDeleting(e)} />
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      <EventFormModal
        open={formOpen}
        event={editing}
        onClose={() => setFormOpen(false)}
        onSubmit={async (input) => {
          if (editing) replaceEvent(await api.updateEvent(editing.id, input));
          else {
            const created = await api.createEvent(input);
            events.setData((list) => [created, ...(list ?? [])]);
          }
        }}
      />

      <ConfirmDialog
        open={!!deleting}
        danger
        loading={busy}
        title={`Delete “${deleting?.name ?? ""}”?`}
        description={`This permanently deletes the event, all ${plural(deleting?.photo_count ?? 0, "photo")} and their face data. This cannot be undone.`}
        confirmLabel="Delete permanently"
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
