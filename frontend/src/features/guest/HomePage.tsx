/** Guest home: hero, event filters (type chips + event list), privacy notice + consent. */
import { useId, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/Button";
import { CalendarIcon, CameraIcon, CheckIcon, ImageIcon, LockIcon, SparklesIcon } from "@/components/Icons";
import { EmptyState, ErrorState, Skeleton } from "@/components/States";
import { publicApi, type PublicEvent } from "@/lib/api";
import { formatDate, plural } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { useGuestFlow } from "./GuestFlowContext";

export function HomePage() {
  const navigate = useNavigate();
  const flow = useGuestFlow();
  const consentId = useId();

  const events = useAsync((signal) => publicApi.listEvents(signal), []);
  const types = useAsync((signal) => publicApi.eventTypes(signal), []);

  const visibleEvents = useMemo(() => {
    const all = events.data ?? [];
    return flow.eventTypes.length ? all.filter((e) => flow.eventTypes.includes(e.type)) : all;
  }, [events.data, flow.eventTypes]);

  function toggleType(type: string) {
    const next = flow.eventTypes.includes(type) ? flow.eventTypes.filter((t) => t !== type) : [...flow.eventTypes, type];
    // Drop selected events that are hidden by the new type filter.
    const stillVisible = new Set((events.data ?? []).filter((e) => !next.length || next.includes(e.type)).map((e) => e.id));
    flow.setFilters({ eventTypes: next, eventIds: flow.eventIds.filter((id) => stillVisible.has(id)) });
  }

  function toggleEvent(id: string) {
    const next = flow.eventIds.includes(id) ? flow.eventIds.filter((x) => x !== id) : [...flow.eventIds, id];
    flow.setFilters({ eventIds: next });
  }

  const noEvents = !events.loading && !events.error && (events.data?.length ?? 0) === 0;

  return (
    <div className="space-y-8">
      {/* Hero */}
      <section className="relative overflow-hidden rounded-4xl bg-primary px-6 py-10 text-white shadow-lifted sm:px-10 sm:py-14">
        <div className="pointer-events-none absolute -right-16 -top-16 h-64 w-64 rounded-full bg-primary-400/40 blur-3xl" aria-hidden="true" />
        <div className="pointer-events-none absolute -bottom-24 left-10 h-64 w-64 rounded-full bg-primary-800/50 blur-3xl" aria-hidden="true" />
        <div className="relative">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-3 py-1 text-xs font-semibold">
            <SparklesIcon /> Face search for event photos
          </span>
          {/* One line on desktop; wraps naturally on small screens. */}
          <h1 className="mt-4 text-2xl font-extrabold leading-tight tracking-tight sm:text-3xl lg:whitespace-nowrap">
            Find your photos in seconds, just take a selfie.
          </h1>
          <h2 className="mt-3 text-xl lg:whitespace-nowrap font-bold leading-snug tracking-tight text-white/90 sm:text-2xl">
            Every photo and video you're in, all in one place.
          </h2>
          <p className="mt-3 max-w-2xl text-base text-primary-100 sm:text-lg">
            We'll show you every event photo and video you appear in, ready to view and download.
          </p>
          <ol className="mt-6 grid max-w-2xl gap-3 text-sm sm:grid-cols-3">
            {[
              { icon: <CalendarIcon />, text: "Pick your events" },
              { icon: <CameraIcon />, text: "Take a quick selfie" },
              { icon: <ImageIcon />, text: "Get your photos" },
            ].map((s, i) => (
              <li key={s.text} className="flex items-center gap-2.5 rounded-2xl bg-white/10 px-3 py-2.5">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white text-sm font-bold text-primary">
                  {i + 1}
                </span>
                <span className="font-medium">{s.text}</span>
              </li>
            ))}
          </ol>
        </div>
      </section>

      {/* Filters */}
      <section aria-labelledby="filters-heading" className="card p-5 sm:p-6">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 id="filters-heading" className="text-lg font-semibold">
              Which events were you at?
            </h2>
            <p className="text-sm text-ink-muted">Leave everything on “All” to search every event.</p>
          </div>
          {(flow.eventTypes.length > 0 || flow.eventIds.length > 0) && (
            <Button variant="ghost" size="sm" onClick={() => flow.setFilters({ eventTypes: [], eventIds: [] })}>
              Clear filters
            </Button>
          )}
        </div>

        {/* Type chips */}
        <div className="mt-4" role="group" aria-label="Filter by event type">
          {types.loading ? (
            <div className="flex gap-2">
              {[80, 110, 90, 100].map((w) => (
                <Skeleton key={w} className="h-9 rounded-full" />
              ))}
            </div>
          ) : (
            <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 scrollbar-none">
              <Chip active={flow.eventTypes.length === 0} onClick={() => flow.setFilters({ eventTypes: [] })}>
                All types
              </Chip>
              {(types.data?.types ?? []).map((t) => (
                <Chip key={t} active={flow.eventTypes.includes(t)} onClick={() => toggleType(t)}>
                  {t}
                </Chip>
              ))}
            </div>
          )}
        </div>

        {/* Event list */}
        <div className="mt-5">
          {events.loading ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {Array.from({ length: 4 }, (_, i) => (
                <div key={i} className="flex items-center gap-3 rounded-2xl border border-line p-3">
                  <Skeleton className="h-16 w-16 shrink-0" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-3/4" />
                    <Skeleton className="h-3 w-1/2" />
                  </div>
                </div>
              ))}
            </div>
          ) : events.error ? (
            <ErrorState error={events.error} onRetry={events.reload} title="Couldn't load events" />
          ) : noEvents ? (
            <EmptyState icon={<CalendarIcon />} title="No events yet" description="Photos haven't been published yet. Please check back soon!" />
          ) : (
            <ul className="grid gap-3 sm:grid-cols-2" aria-label="Events">
              <li>
                <EventOption
                  selected={flow.eventIds.length === 0}
                  onToggle={() => flow.setFilters({ eventIds: [] })}
                  title={flow.eventTypes.length ? "All matching events" : "All events"}
                  subtitle={plural(visibleEvents.reduce((n, e) => n + e.photo_count, 0), "photo")}
                />
              </li>
              {visibleEvents.map((e) => (
                <li key={e.id}>
                  <EventOption event={e} selected={flow.eventIds.includes(e.id)} onToggle={() => toggleEvent(e.id)} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* Privacy + consent */}
      <section aria-labelledby="privacy-heading" className="card p-5 sm:p-6">
        <div className="flex gap-4">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-primary-50 text-xl text-primary">
            <LockIcon />
          </div>
          <div>
            <h2 id="privacy-heading" className="font-semibold">
              Your privacy
            </h2>
            <p className="mt-1 text-sm text-ink-muted">
              Your selfie is only used to find your photos. It is never saved — it's processed in memory and discarded
              immediately after the search.
            </p>
          </div>
        </div>
        <label htmlFor={consentId} className="mt-5 flex cursor-pointer items-start gap-3 rounded-2xl border border-line p-4 hover:border-primary-300">
          <input
            id={consentId}
            type="checkbox"
            checked={flow.consent}
            onChange={(e) => flow.setConsent(e.target.checked)}
            className="mt-0.5 h-5 w-5 shrink-0 rounded border-line-strong text-primary accent-primary"
          />
          <span className="text-sm text-ink">
            I agree to my selfie being used to search for my photos in these events.
          </span>
        </label>
        <Button
          size="lg"
          fullWidth
          className="mt-5"
          icon={<CameraIcon />}
          disabled={!flow.consent || noEvents}
          onClick={() => navigate("/selfie")}
        >
          Continue to selfie
        </Button>
        {!flow.consent && !noEvents ? (
          <p className="mt-2 text-center text-xs text-ink-subtle">Please tick the box above to continue.</p>
        ) : null}
      </section>
    </div>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full px-4 text-sm font-semibold transition-colors ${
        active ? "bg-primary text-white" : "bg-background text-ink-muted ring-1 ring-inset ring-line-strong hover:text-ink"
      }`}
    >
      {active ? <CheckIcon /> : null}
      {children}
    </button>
  );
}

function EventOption({
  event,
  selected,
  onToggle,
  title,
  subtitle,
}: {
  event?: PublicEvent;
  selected: boolean;
  onToggle: () => void;
  title?: string;
  subtitle?: string;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={selected}
      onClick={onToggle}
      className={`flex w-full items-center gap-3 rounded-2xl border p-3 text-left transition-colors ${
        selected ? "border-primary bg-primary-50/60 ring-1 ring-primary" : "border-line hover:border-primary-300"
      }`}
    >
      <div className="relative h-16 w-16 shrink-0 overflow-hidden rounded-xl bg-primary-50">
        {event?.cover_thumb_url ? (
          <img src={event.cover_thumb_url} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-2xl text-primary-300">
            {event ? <ImageIcon /> : <SparklesIcon />}
          </div>
        )}
      </div>
      <div className="min-w-0 flex-1">
        <p className="truncate font-semibold text-ink">{event?.name ?? title}</p>
        <p className="mt-0.5 truncate text-xs text-ink-muted">
          {event ? `${formatDate(event.date)} · ${event.type}` : subtitle}
        </p>
        {event ? <p className="mt-0.5 text-xs text-ink-subtle">{plural(event.photo_count, "photo")}</p> : null}
      </div>
      <span
        className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 text-sm ${
          selected ? "border-primary bg-primary text-white" : "border-line-strong text-transparent"
        }`}
        aria-hidden="true"
      >
        <CheckIcon />
      </span>
    </button>
  );
}
