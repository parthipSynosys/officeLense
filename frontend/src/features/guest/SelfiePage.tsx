/** Selfie capture (front camera with face guide) + upload fallback + search. */
import { useEffect, useRef, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { Button } from "@/components/Button";
import { AlertIcon, ArrowLeftIcon, CameraIcon, PlusIcon, RefreshIcon, SparklesIcon, UploadIcon, XIcon } from "@/components/Icons";
import { SearchingOverlay } from "@/components/SearchingOverlay";
import { Spinner } from "@/components/Spinner";
import { Alert } from "@/components/States";
import { ApiError, publicApi } from "@/lib/api";
import { MAX_SELFIE_BYTES, MAX_SELFIES, useGuestFlow } from "./GuestFlowContext";
import { CAMERA_MESSAGES, selfieMessage } from "./messages";
import { useCamera } from "./useCamera";

/** How many matches to fetch per request (the grid renders 60 at a time). */
export const FETCH_LIMIT = 200;

export function SelfiePage() {
  const flow = useGuestFlow();
  const navigate = useNavigate();
  const camera = useCamera();
  const fileInput = useRef<HTMLInputElement>(null);

  const [searching, setSearching] = useState(false);
  const [rejections, setRejections] = useState<Record<string, string>>({}); // selfie id -> error code
  const [error, setError] = useState<string | null>(null);
  const [capturing, setCapturing] = useState(false);

  const canAddMore = flow.selfies.length < MAX_SELFIES;
  const showCamera = camera.state === "starting" || camera.state === "live";
  const cameraProblem = camera.state === "denied" || camera.state === "unavailable" || camera.state === "error";

  // Open the camera automatically when there is no selfie yet.
  useEffect(() => {
    if (flow.consent && flow.selfies.length === 0) void camera.start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!flow.consent) return <Navigate to="/" replace />;

  async function onCapture() {
    setCapturing(true);
    const blob = await camera.capture();
    setCapturing(false);
    if (!blob) return;
    flow.addSelfie(blob);
    camera.stop(); // turn the camera (and its light) off between shots
    setError(null);
  }

  function onFiles(files: FileList | null) {
    if (!files) return;
    setError(null);
    for (const file of Array.from(files).slice(0, MAX_SELFIES - flow.selfies.length)) {
      if (file.size > MAX_SELFIE_BYTES) {
        setError(`${selfieMessage("FILE_TOO_LARGE").title}. ${selfieMessage("FILE_TOO_LARGE").hint}`);
        continue;
      }
      flow.addSelfie(file);
    }
    camera.stop();
    if (fileInput.current) fileInput.current.value = "";
  }

  function retake(id: string) {
    flow.removeSelfie(id);
    setRejections(({ [id]: _removed, ...rest }) => rest);
    void camera.start();
  }

  async function search() {
    setSearching(true);
    setError(null);
    setRejections({});
    try {
      const response = await publicApi.match({
        selfies: flow.selfies.map((s) => s.blob),
        eventIds: flow.eventIds,
        eventTypes: flow.eventTypes,
        limit: FETCH_LIMIT,
        offset: 0,
      });
      flow.setResult({ id: Date.now(), response, threshold: undefined });
      navigate("/results");
    } catch (err) {
      if (err instanceof ApiError && err.code === "SELFIE_REJECTED") {
        const map: Record<string, string> = {};
        err.errors.forEach((e) => {
          const selfie = flow.selfies[e.index];
          if (selfie) map[selfie.id] = e.code;
        });
        setRejections(map);
        setError(
          err.errors.length === 1 && flow.selfies.length === 1
            ? null
            : "Some selfies couldn't be used. Retake or remove them, then try again.",
        );
      } else if (err instanceof ApiError && err.code === "RATE_LIMITED") {
        setError("You've searched a lot in the last minute. Please wait a moment and try again.");
      } else if (err instanceof ApiError && err.code === "MODELS_NOT_LOADED") {
        setError("Face search is starting up. Please try again in a few seconds.");
      } else if (err instanceof ApiError && err.isNetwork) {
        setError("We couldn't reach the server. Check your connection and try again.");
      } else {
        setError("Something went wrong while searching. Please try again.");
      }
    } finally {
      setSearching(false);
    }
  }

  const singleRejection = flow.selfies.length === 1 ? rejections[flow.selfies[0].id] : undefined;

  return (
    <div className="mx-auto max-w-lg">
      <SearchingOverlay open={searching} />
      <Link to="/" className="inline-flex items-center gap-1.5 rounded-lg text-sm font-medium text-ink-muted hover:text-ink">
        <ArrowLeftIcon /> Back
      </Link>
      <h1 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">Take a selfie</h1>
      <p className="mt-1 text-sm text-ink-muted">
        Face the camera in good light. Adding up to {MAX_SELFIES} selfies from different angles can find more photos.
      </p>

      {/* Camera viewport */}
      {showCamera ? (
        <div className="relative mt-5 aspect-[3/4] w-full overflow-hidden rounded-4xl bg-overlay shadow-lifted sm:aspect-square">
          <video
            ref={camera.videoRef}
            playsInline
            muted
            autoPlay
            className="h-full w-full -scale-x-100 object-cover"
            aria-label="Camera preview"
          />
          <FaceGuide />
          {camera.state === "starting" ? (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-white">
              <Spinner className="h-8 w-8" />
              <span className="text-sm">Starting camera…</span>
            </div>
          ) : (
            <p className="absolute inset-x-0 top-4 text-center text-sm font-medium text-white drop-shadow">
              Center your face in the circle
            </p>
          )}
          <div className="absolute inset-x-0 bottom-5 flex items-center justify-center">
            <button
              type="button"
              onClick={onCapture}
              disabled={camera.state !== "live" || capturing}
              aria-label="Take selfie"
              className="flex h-[76px] w-[76px] items-center justify-center rounded-full bg-white/30 ring-4 ring-white transition-transform active:scale-95 disabled:opacity-50"
            >
              <span className="h-[60px] w-[60px] rounded-full bg-white" />
            </button>
          </div>
          <button
            type="button"
            onClick={camera.stop}
            className="absolute right-3 top-3 flex h-10 w-10 items-center justify-center rounded-full bg-overlay/50 text-xl text-white"
            aria-label="Close camera"
          >
            <XIcon />
          </button>
        </div>
      ) : (
        // Keep the <video> element mounted so the ref exists when starting.
        <video ref={camera.videoRef} playsInline muted className="hidden" aria-hidden="true" />
      )}

      {cameraProblem && flow.selfies.length === 0 ? (
        <div className="mt-5">
          <Alert tone="warning" icon={<AlertIcon />}>
            <p className="font-semibold">{CAMERA_MESSAGES[camera.state as "denied" | "unavailable" | "error"].title}</p>
            <p className="mt-0.5">{CAMERA_MESSAGES[camera.state as "denied" | "unavailable" | "error"].hint}</p>
          </Alert>
        </div>
      ) : null}

      {/* Captured selfies */}
      {flow.selfies.length > 0 ? (
        <section aria-label="Your selfies" className="mt-5 space-y-3">
          <ul className="grid grid-cols-3 gap-3">
            {flow.selfies.map((s, i) => {
              const rejected = rejections[s.id];
              return (
                <li key={s.id} className="relative">
                  <img
                    src={s.previewUrl}
                    alt={`Selfie ${i + 1}`}
                    className={`aspect-square w-full rounded-2xl object-cover ${rejected ? "ring-4 ring-danger" : "ring-1 ring-line"}`}
                  />
                  <button
                    type="button"
                    onClick={() => retake(s.id)}
                    className="absolute -right-2 -top-2 flex h-8 w-8 items-center justify-center rounded-full bg-surface text-base text-ink shadow-soft ring-1 ring-line"
                    aria-label={`Remove selfie ${i + 1} and retake`}
                  >
                    <XIcon />
                  </button>
                  {rejected ? (
                    <span className="absolute inset-x-1 bottom-1 rounded-lg bg-danger px-1.5 py-0.5 text-center text-[11px] font-semibold text-white">
                      {selfieMessage(rejected).title}
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>

          {Object.keys(rejections).length > 0 && !singleRejection ? (
            <ul className="space-y-2">
              {flow.selfies.map((s, i) =>
                rejections[s.id] ? (
                  <li key={s.id}>
                    <Alert tone="danger" icon={<AlertIcon />}>
                      <span className="font-semibold">Selfie {i + 1}: {selfieMessage(rejections[s.id]).title}.</span>{" "}
                      {selfieMessage(rejections[s.id]).hint}
                    </Alert>
                  </li>
                ) : null,
              )}
            </ul>
          ) : null}

          {singleRejection ? (
            <Alert tone="danger" icon={<AlertIcon />}>
              <p className="font-semibold">{selfieMessage(singleRejection).title}</p>
              <p className="mt-0.5">{selfieMessage(singleRejection).hint}</p>
              <Button variant="secondary" size="sm" className="mt-3" icon={<RefreshIcon />} onClick={() => retake(flow.selfies[0].id)}>
                Retake selfie
              </Button>
            </Alert>
          ) : null}
        </section>
      ) : null}

      {error ? (
        <div className="mt-4">
          <Alert tone="danger" icon={<AlertIcon />}>
            {error}
          </Alert>
        </div>
      ) : null}

      {/* Actions */}
      <div className="mt-6 space-y-3">
        {flow.selfies.length > 0 && !showCamera ? (
          <Button
            size="lg"
            fullWidth
            icon={<SparklesIcon />}
            loading={searching}
            disabled={Object.keys(rejections).length > 0}
            onClick={search}
          >
            {searching ? "Finding your photos…" : "Find my photos"}
          </Button>
        ) : null}

        {!showCamera && canAddMore ? (
          <Button
            variant={flow.selfies.length === 0 ? "primary" : "secondary"}
            size={flow.selfies.length === 0 ? "lg" : "md"}
            fullWidth
            icon={flow.selfies.length === 0 ? <CameraIcon /> : <PlusIcon />}
            onClick={() => void camera.start()}
            disabled={searching || camera.state === "denied" || camera.state === "unavailable"}
          >
            {flow.selfies.length === 0 ? "Open camera" : `Add another selfie (${flow.selfies.length}/${MAX_SELFIES})`}
          </Button>
        ) : null}

        {canAddMore ? (
          <>
            <Button
              variant={cameraProblem && flow.selfies.length === 0 ? "primary" : "ghost"}
              size={cameraProblem && flow.selfies.length === 0 ? "lg" : "md"}
              fullWidth
              icon={<UploadIcon />}
              onClick={() => fileInput.current?.click()}
              disabled={searching}
            >
              Upload a selfie
            </Button>
            <input
              ref={fileInput}
              type="file"
              accept="image/jpeg,image/png,image/webp,image/heic,image/heif,.heic,.heif"
              className="sr-only"
              tabIndex={-1}
              aria-hidden="true"
              onChange={(e) => onFiles(e.target.files)}
            />
          </>
        ) : null}
      </div>

      <p className="mt-6 text-center text-xs text-ink-subtle">
        Your selfie is only used to find your photos. It is never saved.
      </p>
    </div>
  );
}

/** Dark vignette with a circular cut-out and dashed ring to guide face placement. */
function FaceGuide() {
  return (
    <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <defs>
        <mask id="face-cutout">
          <rect width="100" height="100" fill="white" />
          <ellipse cx="50" cy="46" rx="30" ry="36" fill="black" />
        </mask>
      </defs>
      <rect width="100" height="100" className="fill-overlay/55" mask="url(#face-cutout)" />
      <ellipse cx="50" cy="46" rx="30" ry="36" fill="none" className="stroke-white" strokeWidth="0.8" strokeDasharray="3 2" />
    </svg>
  );
}
