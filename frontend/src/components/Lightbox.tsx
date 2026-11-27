/** Full-screen photo / video viewer: next/prev, keyboard, swipe, download. */
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useFocusTrap } from "./Modal";
import { ChevronLeftIcon, ChevronRightIcon, DownloadIcon, XIcon } from "./Icons";
import { Spinner } from "./Spinner";
import { formatDuration } from "@/lib/format";

export interface LightboxPhoto {
  id: string;
  fullUrl: string | null;
  thumbUrl: string | null;
  alt: string;
  downloadUrl: string;
  /** Set for videos: played inline, with fullUrl as the poster. */
  videoUrl?: string | null;
  /** Videos: seconds where the guest appears; playback starts just before it. */
  startAt?: number | null;
}

/** Start a little before the matched moment so the guest walks into view. */
const LEAD_IN_SECONDS = 1;

interface Props {
  photos: LightboxPhoto[];
  index: number;
  onIndexChange: (index: number) => void;
  onClose: () => void;
  /** Called when the viewer nears the end (e.g. to load more results). */
  onNearEnd?: () => void;
}

const SWIPE_PX = 50;

export function Lightbox({ photos, index, onIndexChange, onClose, onNearEnd }: Props) {
  const ref = useFocusTrap(true, onClose);
  const [loaded, setLoaded] = useState(false);
  const [videoError, setVideoError] = useState(false);
  const touch = useRef<{ x: number; y: number } | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const photo = photos[index];
  const hasPrev = index > 0;
  const hasNext = index < photos.length - 1;

  const go = (delta: number) => {
    const next = index + delta;
    if (next >= 0 && next < photos.length) onIndexChange(next);
  };

  useEffect(() => {
    setLoaded(false);
    setVideoError(false);
  }, [photo?.id]);

  // Keyboard navigation.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowLeft") go(-1);
      else if (e.key === "ArrowRight") go(1);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  // Preload neighbours; ask for more results near the end.
  useEffect(() => {
    for (const i of [index - 1, index + 1]) {
      const url = photos[i]?.fullUrl;
      if (url) new Image().src = url;
    }
    if (onNearEnd && index >= photos.length - 3) onNearEnd();
  }, [index, photos, onNearEnd]);

  if (!photo) return null;

  return createPortal(
    <div
      ref={ref}
      role="dialog"
      aria-modal="true"
      aria-label={`Photo ${index + 1} of ${photos.length}`}
      tabIndex={-1}
      className="fixed inset-0 z-50 flex flex-col bg-overlay/95 text-white animate-fade-in"
      onTouchStart={(e) => {
        touch.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
      }}
      onTouchEnd={(e) => {
        if (!touch.current) return;
        const dx = e.changedTouches[0].clientX - touch.current.x;
        const dy = e.changedTouches[0].clientY - touch.current.y;
        touch.current = null;
        if (Math.abs(dx) > SWIPE_PX && Math.abs(dx) > Math.abs(dy)) go(dx < 0 ? 1 : -1);
        else if (dy > SWIPE_PX * 2 && Math.abs(dy) > Math.abs(dx)) onClose(); // swipe down to close
      }}
    >
      <div className="flex items-center justify-between gap-2 px-3 py-3 sm:px-5">
        <span className="rounded-full bg-white/10 px-3 py-1 text-sm font-medium tabular-nums" aria-live="polite">
          {index + 1} / {photos.length}
        </span>
        <div className="flex items-center gap-1">
          <a
            href={photo.downloadUrl}
            download
            className="inline-flex h-11 items-center gap-2 rounded-xl px-3 text-sm font-semibold hover:bg-white/10"
          >
            <DownloadIcon className="text-lg" />
            <span>Download</span>
          </a>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-11 w-11 items-center justify-center rounded-xl text-2xl hover:bg-white/10"
            aria-label="Close viewer"
          >
            <XIcon />
          </button>
        </div>
      </div>

      <div className="relative flex min-h-0 flex-1 items-center justify-center px-2 pb-4 sm:px-16">
        {photo.thumbUrl && !loaded ? (
          <img src={photo.thumbUrl} alt="" aria-hidden="true" className="absolute max-h-full max-w-full scale-95 object-contain opacity-60 blur-sm" />
        ) : null}
        {!loaded ? (
          <span className="absolute">
            <Spinner className="h-8 w-8" label="Loading photo" />
          </span>
        ) : null}
        {photo.videoUrl && !videoError ? (
          <video
            key={photo.id}
            ref={videoRef}
            src={photo.videoUrl}
            poster={photo.startAt ? undefined : photo.fullUrl ?? undefined}
            controls
            autoPlay
            playsInline
            preload="auto"
            aria-label={photo.alt}
            onLoadedMetadata={(e) => {
              if (photo.startAt) e.currentTarget.currentTime = Math.max(0, photo.startAt - LEAD_IN_SECONDS);
            }}
            onLoadedData={() => setLoaded(true)}
            onSeeked={() => setLoaded(true)}
            onError={() => {
              setLoaded(true);
              setVideoError(true);
            }}
            className="relative max-h-full max-w-full rounded-lg bg-black"
          />
        ) : null}
        {photo.videoUrl && videoError ? (
          <div className="relative flex max-w-md flex-col items-center gap-3 rounded-2xl bg-white/10 p-6 text-center">
            {photo.fullUrl ? <img src={photo.fullUrl} alt={photo.alt} className="max-h-[50vh] rounded-lg object-contain" /> : null}
            <p className="text-sm">This video format can't be played in your browser. Download it to watch.</p>
            <a href={photo.downloadUrl} download className="inline-flex h-10 items-center gap-2 rounded-xl bg-white/20 px-4 text-sm font-semibold hover:bg-white/30">
              <DownloadIcon /> Download video
            </a>
          </div>
        ) : null}
        {photo.fullUrl && !photo.videoUrl ? (
          <img
            key={photo.id}
            src={photo.fullUrl}
            alt={photo.alt}
            onLoad={() => setLoaded(true)}
            onError={() => setLoaded(true)}
            className={`relative max-h-full max-w-full select-none rounded-lg object-contain transition-opacity duration-200 ${loaded ? "opacity-100" : "opacity-0"}`}
            draggable={false}
          />
        ) : null}

        <button
          type="button"
          onClick={() => go(-1)}
          disabled={!hasPrev}
          aria-label="Previous photo"
          className="absolute left-1 top-1/2 hidden h-12 w-12 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-2xl hover:bg-white/20 disabled:opacity-0 sm:left-4 sm:flex"
        >
          <ChevronLeftIcon />
        </button>
        <button
          type="button"
          onClick={() => go(1)}
          disabled={!hasNext}
          aria-label="Next photo"
          className="absolute right-1 top-1/2 hidden h-12 w-12 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-2xl hover:bg-white/20 disabled:opacity-0 sm:right-4 sm:flex"
        >
          <ChevronRightIcon />
        </button>
      </div>

      {photo.videoUrl && !videoError && photo.startAt != null ? (
        <div className="flex justify-center px-4 pb-3">
          <button
            type="button"
            onClick={() => {
              const v = videoRef.current;
              if (!v) return;
              v.currentTime = Math.max(0, (photo.startAt ?? 0) - LEAD_IN_SECONDS);
              void v.play().catch(() => undefined);
            }}
            className="inline-flex h-10 items-center gap-2 rounded-full bg-primary px-4 text-sm font-semibold text-white shadow-glow hover:bg-primary-700"
          >
            You appear at {formatDuration(photo.startAt)} · Jump to your moment
          </button>
        </div>
      ) : null}

      {/* Mobile navigation bar */}
      <div className="flex items-center justify-between px-4 pb-4 sm:hidden safe-bottom">
        <button type="button" onClick={() => go(-1)} disabled={!hasPrev} aria-label="Previous photo" className="flex h-12 w-12 items-center justify-center rounded-full bg-white/10 text-2xl disabled:opacity-30">
          <ChevronLeftIcon />
        </button>
        <span className="text-xs text-white/70">Swipe to browse</span>
        <button type="button" onClick={() => go(1)} disabled={!hasNext} aria-label="Next photo" className="flex h-12 w-12 items-center justify-center rounded-full bg-white/10 text-2xl disabled:opacity-30">
          <ChevronRightIcon />
        </button>
      </div>
    </div>,
    document.body,
  );
}
