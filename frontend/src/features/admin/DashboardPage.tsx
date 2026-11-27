import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Button } from "@/components/Button";
import { AlertIcon, CalendarIcon, ChevronRightIcon, ClockIcon, ImageIcon, PlusIcon, UsersIcon } from "@/components/Icons";
import { Badge, EmptyState, ErrorState, Skeleton } from "@/components/States";
import type { AdminEvent } from "@/lib/api";
import { formatDate, formatNumber, plural } from "@/lib/format";
import { useAsync, useInterval } from "@/lib/useAsync";
import { useAdminApi } from "./AuthContext";

export function DashboardPage() {
  const api = useAdminApi();
  const navigate = useNavigate();
  const stats = useAsync((signal) => api.stats(signal), [api]);
  const events = useAsync((signal) => api.listEvents(signal), [api]);
  useInterval(stats.reload, 10_000);
  useInterval(events.reload, 30_000);

  const s = stats.data;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-sm text-ink-muted">Live overview of your photo library.</p>
        </div>
        <Button icon={<PlusIcon />} onClick={() => navigate("/admin/events?new=1")}>
          New event
        </Button>
      </div>

      {stats.error && !s ? (
        <div className="card">
          <ErrorState error={stats.error} onRetry={stats.reload} title="Couldn't load stats" />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-5">
          <StatCard icon={<CalendarIcon />} label="Events" value={s?.events} hint={s ? `${s.published_events} published` : undefined} />
          <StatCard icon={<ImageIcon />} label="Photos" value={s?.photos} hint={s ? plural(s.videos ?? 0, "video") : undefined} />
          <StatCard icon={<UsersIcon />} label="Faces indexed" value={s?.faces} />
          <StatCard icon={<AlertIcon />} label="Failed" value={s?.failed} tone={s && s.failed > 0 ? "danger" : "neutral"} />
          <StatCard
            icon={<ClockIcon />}
            label="Queue"
            value={s ? s.queue ?? undefined : undefined}
            hint={s ? (s.queue === null ? "Redis unreachable" : `${s.processing} processing`) : undefined}
            tone={s && s.queue === null ? "danger" : "neutral"}
            fallback={s && s.queue === null ? "—" : undefined}
          />
        </div>
      )}

      <section aria-labelledby="dash-events" className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 id="dash-events" className="text-lg font-semibold">
            Your events {events.data ? <span className="text-ink-subtle">· {formatNumber(events.data.length)}</span> : null}
          </h2>
          {events.data && events.data.length > 0 ? (
            <Link to="/admin/events" className="inline-flex items-center gap-1 rounded-lg text-sm font-semibold text-primary hover:underline">
              Manage all <ChevronRightIcon />
            </Link>
          ) : null}
        </div>

        {events.loading && !events.data ? (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <div key={i} className="card overflow-hidden">
                <Skeleton className="aspect-video w-full rounded-none" />
                <div className="space-y-2 p-4">
                  <Skeleton className="h-4 w-2/3" />
                  <Skeleton className="h-3 w-1/2" />
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
              description="Create your first event, then upload its photos and videos."
              action={
                <Button icon={<PlusIcon />} onClick={() => navigate("/admin/events?new=1")}>
                  Create event
                </Button>
              }
            />
          </div>
        ) : (
          <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {events.data!.map((e) => (
              <li key={e.id}>
                <EventTile event={e} />
              </li>
            ))}
          </ul>
        )}
      </section>

      {events.data && events.data.length === 0 ? (
      <div className="card p-6">
        <h2 className="font-semibold">Getting started</h2>
        <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-sm text-ink-muted">
          <li>Create an event (name, type, date) under <Link className="font-semibold text-primary hover:underline" to="/admin/events">Events</Link>.</li>
          <li>Open it and drag &amp; drop your photos — indexing starts automatically.</li>
          <li>Pick a cover photo, then publish the event so guests can search it.</li>
        </ol>
      </div>
      ) : null}
    </div>
  );
}

function EventTile({ event: e }: { event: AdminEvent }) {
  const indexing = e.photo_count - e.done_count - e.failed_count;
  return (
    <Link
      to={`/admin/events/${e.id}`}
      className="card group block overflow-hidden transition-shadow hover:shadow-lg focus-visible:ring-2 focus-visible:ring-primary"
    >
      <div className="relative aspect-video bg-primary-50">
        {e.cover_thumb_url ? (
          <img
            src={e.cover_thumb_url}
            alt={`Thumbnail of ${e.name}`}
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-primary-300">
            <ImageIcon className="text-3xl" />
            <span className="text-xs font-medium">No photos yet</span>
          </div>
        )}
        <span className="absolute left-2 top-2">
          <Badge tone={e.is_published ? "success" : "neutral"}>{e.is_published ? "Published" : "Draft"}</Badge>
        </span>
      </div>
      <div className="p-4">
        <p className="truncate font-semibold text-ink">{e.name}</p>
        <p className="mt-0.5 text-sm text-ink-muted">
          {formatDate(e.event_date)} · {e.type}
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Badge>{plural(e.photo_count, "file")}</Badge>
          <Badge tone="primary">{formatNumber(e.face_count)} faces</Badge>
          {indexing > 0 ? <Badge tone="warning">{indexing} indexing</Badge> : null}
          {e.failed_count > 0 ? <Badge tone="danger">{e.failed_count} failed</Badge> : null}
        </div>
      </div>
    </Link>
  );
}

function StatCard({
  icon,
  label,
  value,
  hint,
  tone = "neutral",
  fallback,
}: {
  icon: ReactNode;
  label: string;
  value: number | undefined;
  hint?: string;
  tone?: "neutral" | "danger";
  fallback?: string;
}) {
  const loading = value === undefined && fallback === undefined;
  return (
    <div className="card p-4 sm:p-5">
      <div className="flex items-center gap-2 text-sm font-medium text-ink-muted">
        <span className={`flex h-8 w-8 items-center justify-center rounded-lg text-base ${tone === "danger" ? "bg-danger-soft text-danger" : "bg-primary-50 text-primary"}`}>
          {icon}
        </span>
        {label}
      </div>
      {loading ? (
        <Skeleton className="mt-3 h-8 w-20" />
      ) : (
        <p className={`mt-3 text-3xl font-bold tabular-nums ${tone === "danger" ? "text-danger" : "text-ink"}`}>
          {value !== undefined ? formatNumber(value) : fallback}
        </p>
      )}
      {hint ? <p className="mt-1 text-xs text-ink-subtle">{hint}</p> : null}
    </div>
  );
}
