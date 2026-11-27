/** Results: count, per-event tabs, lazy grid with infinite scroll, lightbox, ZIP downloads. */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { Button } from "@/components/Button";
import { CameraIcon, DownloadIcon, ImageIcon, InfoIcon, PlayIcon, RefreshIcon, SparklesIcon } from "@/components/Icons";
import { Lightbox, type LightboxPhoto } from "@/components/Lightbox";
import { Modal } from "@/components/Modal";
import { Spinner } from "@/components/Spinner";
import { Alert, EmptyState, ProgressBar, errorMessage } from "@/components/States";
import { ApiError, publicApi, type MatchByEvent, type MatchPhoto } from "@/lib/api";
import { formatDate, formatDuration, formatNumber, plural, slugify } from "@/lib/format";
import { downloadZip, type ZipProgress } from "@/lib/zip";
import { LOW_THRESHOLD, useGuestFlow, type SearchResult } from "./GuestFlowContext";
import { TIPS } from "./messages";
import { FETCH_LIMIT } from "./SelfiePage";

const PAGE_SIZE = 60; // photos rendered per "page" of infinite scroll
const ALL = "all";

interface ViewState {
  photos: MatchPhoto[];
  total: number;
  loading: boolean;
  error: unknown;
}

export function ResultsPage() {
  const flow = useGuestFlow();
  if (!flow.result || flow.selfies.length === 0) return <Navigate to="/" replace />;
  // Re-mount (fresh state) whenever a new search result arrives.
  return <Results key={flow.result.id} result={flow.result} />;
}

function Results({ result }: { result: SearchResult }) {
  const flow = useGuestFlow();
  const navigate = useNavigate();
  const { response, threshold } = result;
  const byEvent = response.by_event;
  const eventsById = useMemo(() => new Map(byEvent.map((e) => [e.event_id, e])), [byEvent]);

  const [views, setViews] = useState<Record<string, ViewState>>({
    [ALL]: { photos: response.photos, total: response.total, loading: false, error: null },
  });
  const viewsRef = useRef(views);
  viewsRef.current = views;

  const [tab, setTab] = useState<string>(ALL);
  const [rendered, setRendered] = useState(PAGE_SIZE);
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  const [rerunning, setRerunning] = useState(false);
  const [rerunError, setRerunError] = useState<string | null>(null);
  const [zip, setZip] = useState<{ label: string; progress: ZipProgress | null; ctrl: AbortController } | null>(null);
  const [zipNotice, setZipNotice] = useState<string | null>(null);

  const all = views[ALL];
  const allComplete = all.photos.length >= all.total;
  const lowered = threshold !== undefined && threshold <= LOW_THRESHOLD;

  // Photos + total for the active tab. Event tabs filter "all" when it is fully
  // loaded, otherwise they load their own pages with an event filter.
  const current: ViewState = useMemo(() => {
    if (tab === ALL) return all;
    const total = eventsById.get(tab)?.count ?? 0;
    if (allComplete) return { photos: all.photos.filter((p) => p.event_id === tab), total, loading: false, error: null };
    return views[tab] ?? { photos: [], total, loading: true, error: null };
  }, [tab, all, allComplete, views, eventsById]);

  /** Update a view in state AND in the ref immediately (async loops read the ref). */
  const updateView = useCallback((key: string, state: ViewState) => {
    viewsRef.current = { ...viewsRef.current, [key]: state };
    setViews(viewsRef.current);
  }, []);

  /** Fetch the next page for a view key (ALL or an event id). Returns the merged list. */
  const fetchPage = useCallback(
    async (key: string): Promise<MatchPhoto[] | null> => {
      const existing = viewsRef.current[key];
      if (existing?.loading) return null;
      const total = existing?.total ?? (key === ALL ? response.total : eventsById.get(key)?.count ?? 0);
      const have = existing?.photos ?? [];
      if (existing && have.length >= total) return have;

      updateView(key, { photos: have, total, loading: true, error: null });
      try {
        const res = await publicApi.match({
          selfies: flow.selfies.map((s) => s.blob),
          eventIds: key === ALL ? flow.eventIds : [key],
          eventTypes: key === ALL ? flow.eventTypes : [],
          threshold,
          limit: FETCH_LIMIT,
          offset: have.length,
        });
        const seen = new Set(have.map((p) => p.id));
        const merged = [...have, ...res.photos.filter((p) => !seen.has(p.id))];
        // If the server returned nothing new, treat the view as complete.
        const newTotal = merged.length === have.length ? merged.length : total;
        updateView(key, { photos: merged, total: newTotal, loading: false, error: null });
        return merged;
      } catch (err) {
        updateView(key, { photos: have, total, loading: false, error: err });
        return null;
      }
    },
    [flow.selfies, flow.eventIds, flow.eventTypes, threshold, response.total, eventsById, updateView],
  );

  // Event tab opened before "all" is complete -> load that event's photos.
  useEffect(() => {
    if (tab !== ALL && !allComplete && !viewsRef.current[tab]) void fetchPage(tab);
  }, [tab, allComplete, fetchPage]);

  // Infinite scroll sentinel.
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = sentinel.current;
    if (!node) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries[0].isIntersecting) return;
        if (rendered < current.photos.length) setRendered((r) => r + PAGE_SIZE);
        else if (current.photos.length < current.total && !current.loading && !current.error) {
          void fetchPage(tab === ALL || !allComplete ? tab : ALL);
        }
      },
      { rootMargin: "600px 0px" },
    );
    io.observe(node);
    return () => io.disconnect();
  }, [rendered, current, fetchPage, tab, allComplete]);

  function selectTab(key: string) {
    setTab(key);
    setRendered(PAGE_SIZE);
  }

  function onTabKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const keys = [ALL, ...byEvent.map((b) => b.event_id)];
    const i = keys.indexOf(tab);
    const next = keys[(i + (e.key === "ArrowRight" ? 1 : -1) + keys.length) % keys.length];
    selectTab(next);
    document.getElementById(`tab-${next}`)?.focus();
  }

  async function showMoreMatches() {
    setRerunning(true);
    setRerunError(null);
    try {
      const res = await publicApi.match({
        selfies: flow.selfies.map((s) => s.blob),
        eventIds: flow.eventIds,
        eventTypes: flow.eventTypes,
        threshold: LOW_THRESHOLD,
        limit: FETCH_LIMIT,
        offset: 0,
      });
      flow.setResult({ id: Date.now(), response: res, threshold: LOW_THRESHOLD });
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (err) {
      setRerunError(errorMessage(err));
      setRerunning(false);
    }
  }

  async function loadEverything(key: string): Promise<MatchPhoto[] | null> {
    let list = key === ALL ? viewsRef.current[ALL].photos : current.photos;
    const total = key === ALL ? response.total : eventsById.get(key)?.count ?? 0;
    const sourceKey = key === ALL || !allComplete ? key : ALL;
    while (list.length < total) {
      const next = await fetchPage(sourceKey);
      if (!next || next.length <= list.length) break;
      list = sourceKey === ALL && key !== ALL ? next.filter((p) => p.event_id === key) : next;
    }
    return list;
  }

  async function downloadAsZip(key: string) {
    const ctrl = new AbortController();
    const label = key === ALL ? "all your photos" : eventsById.get(key)?.name ?? "this event";
    setZipNotice(null);
    setZip({ label, progress: null, ctrl });
    try {
      const photos = await loadEverything(key);
      if (!photos || ctrl.signal.aborted) throw new DOMException("Cancelled", "AbortError");
      const counters = new Map<string, number>();
      const items = photos
        .filter((p) => (p.media_type === "video" ? p.video_url : p.full_url))
        .map((p) => {
          const ev = eventsById.get(p.event_id);
          const slug = slugify(ev?.name ?? "event");
          const n = (counters.get(slug) ?? 0) + 1;
          counters.set(slug, n);
          const isVideo = p.media_type === "video";
          const url = (isVideo ? p.video_url : p.full_url) as string;
          const ext = isVideo ? url.slice(url.lastIndexOf(".")) : ".jpg";
          const name = `${slug}-${String(n).padStart(3, "0")}${ext}`;
          return { url, filename: key === ALL ? `${slug}/${name}` : name };
        });
      const zipName = key === ALL ? "my-event-photos.zip" : `${slugify(label)}-photos.zip`;
      const { failed } = await downloadZip(items, zipName, (progress) => setZip((z) => (z ? { ...z, progress } : z)), ctrl.signal);
      if (failed > 0) setZipNotice(`${plural(failed, "photo")} couldn't be added to the ZIP. You can download them individually.`);
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setZipNotice(err instanceof ApiError ? errorMessage(err) : "The download failed. Please try again.");
      }
    } finally {
      setZip(null);
    }
  }

  function startOver() {
    flow.reset();
    navigate("/", { replace: true });
  }

  function tryAnotherSelfie() {
    flow.clearSelfies();
    flow.setResult(null);
    navigate("/selfie");
  }

  const lightboxPhotos: LightboxPhoto[] = useMemo(
    () =>
      current.photos.map((p, i) => ({
        id: p.id,
        fullUrl: p.full_url,
        thumbUrl: p.thumb_url,
        alt: `${p.media_type === "video" ? "Video" : "Photo"} ${i + 1} of ${current.total} from ${eventsById.get(p.event_id)?.name ?? "the event"}`,
        downloadUrl: publicApi.downloadUrl(p.id),
        videoUrl: p.media_type === "video" ? p.video_url : null,
      })),
    [current.photos, current.total, eventsById],
  );

  // ---------------------------------------------------------------- empty
  if (response.total === 0) {
    return (
      <div className="mx-auto max-w-lg">
        <div className="card">
          <EmptyState
            icon={<ImageIcon />}
            title="We couldn't find you in any photos yet"
            description={lowered ? "Even with a wider search we found no matches." : "Don't worry — a few small changes often help."}
          >
            <ul className="mt-5 w-full space-y-2 text-left">
              {TIPS.map((tip) => (
                <li key={tip} className="flex gap-2.5 rounded-xl bg-background px-3 py-2.5 text-sm text-ink-muted">
                  <SparklesIcon className="mt-0.5 shrink-0 text-primary" /> {tip}
                </li>
              ))}
            </ul>
            <div className="mt-6 flex w-full flex-col gap-2">
              {!lowered ? (
                <Button size="lg" fullWidth icon={<SparklesIcon />} loading={rerunning} onClick={showMoreMatches}>
                  Show more possible matches
                </Button>
              ) : null}
              <Button variant={lowered ? "primary" : "secondary"} fullWidth icon={<CameraIcon />} onClick={tryAnotherSelfie}>
                Try another selfie
              </Button>
              <Button variant="ghost" fullWidth onClick={startOver}>
                Start over
              </Button>
            </div>
            {rerunError ? <p className="mt-3 text-sm text-danger" role="alert">{rerunError}</p> : null}
          </EmptyState>
        </div>
      </div>
    );
  }

  // -------------------------------------------------------------- results
  const visible = current.photos.slice(0, rendered);
  const activeEvent: MatchByEvent | undefined = tab === ALL ? undefined : eventsById.get(tab);

  return (
    <div>
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wide text-primary">Your photos</p>
          <h1 className="mt-1 text-3xl font-extrabold tracking-tight sm:text-4xl">
            We found {formatNumber(response.total)} {response.total === 1 ? "photo" : "photos"} of you{" "}
            <span role="img" aria-label="celebration">
              🎉
            </span>
          </h1>
          <p className="mt-1 text-sm text-ink-muted">across {plural(byEvent.length, "event")}</p>
        </div>
        <div className="flex gap-2">
          <Button icon={<DownloadIcon />} onClick={() => downloadAsZip(ALL)} disabled={!!zip}>
            Download all
          </Button>
          <Button variant="secondary" icon={<RefreshIcon />} onClick={startOver}>
            Start over
          </Button>
        </div>
      </header>

      {lowered ? (
        <div className="mt-4">
          <Alert tone="info" icon={<InfoIcon />}>
            Showing more possible matches — a few of these may not be you.
          </Alert>
        </div>
      ) : null}
      {zipNotice ? (
        <div className="mt-4">
          <Alert tone="warning" icon={<InfoIcon />}>
            {zipNotice}
          </Alert>
        </div>
      ) : null}

      {/* Per-event tabs */}
      <div className="sticky top-16 z-20 -mx-4 mt-6 border-b border-line bg-background/90 px-4 backdrop-blur">
        <div role="tablist" aria-label="Filter photos by event" className="flex gap-1 overflow-x-auto scrollbar-none" onKeyDown={onTabKeyDown}>
          <TabButton id={ALL} active={tab === ALL} onSelect={selectTab} label="All" count={response.total} />
          {byEvent.map((e) => (
            <TabButton key={e.event_id} id={e.event_id} active={tab === e.event_id} onSelect={selectTab} label={e.name} count={e.count} />
          ))}
        </div>
      </div>

      <section id={`panel-${tab}`} role="tabpanel" aria-labelledby={`tab-${tab}`} className="pt-4">
        {activeEvent ? (
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-ink-muted">
              {formatDate(activeEvent.event_date)} · {activeEvent.type} · {plural(activeEvent.count, "photo")}
            </p>
            <Button variant="soft" size="sm" icon={<DownloadIcon />} onClick={() => downloadAsZip(tab)} disabled={!!zip}>
              Download this event
            </Button>
          </div>
        ) : null}

        {current.photos.length === 0 && current.loading ? (
          <PhotoGridSkeleton />
        ) : (
          <ul className="grid grid-cols-3 gap-1.5 sm:grid-cols-4 sm:gap-3 lg:grid-cols-5">
            {visible.map((p, i) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => setLightboxIndex(i)}
                  className="group relative block aspect-square w-full overflow-hidden rounded-xl bg-line sm:rounded-2xl"
                  aria-label={`Open ${p.media_type === "video" ? "video" : "photo"} ${i + 1} of ${current.total}`}
                >
                  {p.thumb_url ? (
                    <img
                      src={p.thumb_url}
                      alt={`Photo ${i + 1} from ${eventsById.get(p.event_id)?.name ?? "event"}`}
                      loading="lazy"
                      decoding="async"
                      className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                    />
                  ) : null}
                  {p.media_type === "video" ? <VideoOverlay duration={p.duration} /> : null}
                </button>
              </li>
            ))}
          </ul>
        )}

        <div ref={sentinel} aria-hidden="true" className="h-px" />
        {current.loading && current.photos.length > 0 ? (
          <div className="flex justify-center py-6 text-primary">
            <Spinner label="Loading more photos" />
          </div>
        ) : null}
        {current.error ? (
          <div className="mt-6">
            <Alert tone="danger">
              {errorMessage(current.error)}{" "}
              <button type="button" className="font-semibold underline" onClick={() => void fetchPage(tab === ALL || !allComplete ? tab : ALL)}>
                Try again
              </button>
            </Alert>
          </div>
        ) : null}
      </section>

      {/* Missing photos? */}
      <section className="card mt-10 p-5 sm:p-6" aria-labelledby="missing-heading">
        <h2 id="missing-heading" className="font-semibold">
          Missing some photos?
        </h2>
        <p className="mt-1 text-sm text-ink-muted">
          {lowered
            ? "You're already seeing the widest search. Adding another selfie from a different angle can still help."
            : "We only show confident matches. You can widen the search to include less certain ones."}
        </p>
        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          {!lowered ? (
            <Button variant="soft" icon={<SparklesIcon />} loading={rerunning} onClick={showMoreMatches}>
              Show more possible matches
            </Button>
          ) : null}
          <Button variant="secondary" icon={<CameraIcon />} onClick={tryAnotherSelfie}>
            Try another selfie
          </Button>
        </div>
        {rerunError ? <p className="mt-3 text-sm text-danger" role="alert">{rerunError}</p> : null}
      </section>

      {lightboxIndex !== null ? (
        <Lightbox
          photos={lightboxPhotos}
          index={lightboxIndex}
          onIndexChange={(i) => {
            setLightboxIndex(i);
            if (i >= rendered - 3) setRendered((r) => Math.max(r, i + PAGE_SIZE));
          }}
          onClose={() => setLightboxIndex(null)}
          onNearEnd={() => {
            if (current.photos.length < current.total && !current.loading) void fetchPage(tab === ALL || !allComplete ? tab : ALL);
          }}
        />
      ) : null}

      <Modal
        open={!!zip}
        onClose={() => zip?.ctrl.abort()}
        title={`Downloading ${zip?.label ?? ""}`}
        description="Keep this page open while we prepare your ZIP file."
        size="sm"
        dismissible={false}
        footer={
          <Button variant="secondary" onClick={() => zip?.ctrl.abort()}>
            Cancel
          </Button>
        }
      >
        <div className="space-y-2 pb-2">
          <ProgressBar value={zip?.progress?.fraction ?? 0} label="ZIP download progress" />
          <p className="text-sm text-ink-muted" aria-live="polite">
            {!zip?.progress
              ? "Getting your photo list…"
              : zip.progress.phase === "fetching"
                ? `Fetching photo ${Math.min(zip.progress.done + 1, zip.progress.total)} of ${zip.progress.total}…`
                : "Creating ZIP file…"}
          </p>
        </div>
      </Modal>
    </div>
  );
}

function TabButton({ id, active, onSelect, label, count }: { id: string; active: boolean; onSelect: (id: string) => void; label: string; count: number }) {
  return (
    <button
      id={`tab-${id}`}
      type="button"
      role="tab"
      aria-selected={active}
      aria-controls={`panel-${id}`}
      tabIndex={active ? 0 : -1}
      onClick={() => onSelect(id)}
      className={`relative shrink-0 whitespace-nowrap px-3 py-3 text-sm font-semibold transition-colors ${
        active ? "text-primary" : "text-ink-muted hover:text-ink"
      }`}
    >
      {label} <span className={active ? "text-primary" : "text-ink-subtle"}>· {formatNumber(count)}</span>
      {active ? <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary" /> : null}
    </button>
  );
}

function PhotoGridSkeleton() {
  return (
    <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-4 sm:gap-3 lg:grid-cols-5" aria-busy="true" aria-label="Loading photos">
      {Array.from({ length: 15 }, (_, i) => (
        <div key={i} className="skeleton aspect-square rounded-xl sm:rounded-2xl" />
      ))}
    </div>
  );
}

function VideoOverlay({ duration }: { duration: number | null }) {
  return (
    <>
      <span className="pointer-events-none absolute inset-0 flex items-center justify-center">
        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-black/55 text-lg text-white sm:h-12 sm:w-12">
          <PlayIcon />
        </span>
      </span>
      {duration ? (
        <span className="pointer-events-none absolute bottom-1.5 right-1.5 rounded-md bg-black/65 px-1.5 py-0.5 text-[11px] font-semibold tabular-nums text-white">
          {formatDuration(duration)}
        </span>
      ) : null}
    </>
  );
}
