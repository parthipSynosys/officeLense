/**
 * Typed client for the Locator event-photos API. The frontend only ever talks to /api.
 */

const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

// ---------------------------------------------------------------------------
// Types (mirror backend/app/schemas)
// ---------------------------------------------------------------------------

export const EVENT_TYPES = [
  "Conference",
  "Workshop",
  "Cultural",
  "Sports",
  "Award Ceremony",
  "Team Outing",
  "Other",
] as const;
export type EventType = (typeof EVENT_TYPES)[number];

export interface PublicEvent {
  id: string;
  name: string;
  type: EventType;
  date: string; // YYYY-MM-DD
  cover_thumb_url: string | null;
  photo_count: number;
}

export interface MatchByEvent {
  event_id: string;
  name: string;
  type: EventType;
  event_date: string;
  count: number;
}

export interface MatchPhoto {
  id: string;
  event_id: string;
  thumb_url: string | null;
  full_url: string | null;
  width: number | null;
  height: number | null;
  media_type: MediaType;
  video_url: string | null;
  duration: number | null;
  similarity: number;
  /** Videos: seconds into the clip where the guest was seen. */
  match_time: number | null;
}

export interface MatchResponse {
  total: number;
  by_event: MatchByEvent[];
  photos: MatchPhoto[];
  limit: number;
  offset: number;
  /** Photos/videos in the searched events still being processed (not searchable yet). */
  pending?: number;
}

export interface SelfieErrorItem {
  index: number;
  code: string;
  message: string;
}

export type PhotoStatus = "queued" | "processing" | "done" | "failed";
export type MediaType = "photo" | "video";

export interface AdminEvent {
  id: string;
  name: string;
  type: EventType;
  event_date: string;
  description: string;
  cover_photo_id: string | null;
  cover_thumb_url: string | null;
  is_published: boolean;
  created_at: string;
  updated_at: string;
  photo_count: number;
  done_count: number;
  failed_count: number;
  face_count: number;
}

export interface EventInput {
  name: string;
  type: EventType;
  event_date: string;
  description: string;
  is_published: boolean;
}

export interface AdminPhoto {
  id: string;
  event_id: string;
  original_filename: string;
  status: PhotoStatus;
  error: string | null;
  face_count: number;
  width: number | null;
  height: number | null;
  thumb_url: string | null;
  full_url: string | null;
  media_type: MediaType;
  video_url: string | null;
  duration: number | null; // seconds, videos only
  created_at: string;
}

export interface PhotoPage {
  items: AdminPhoto[];
  total: number;
  page: number;
  page_size: number;
}

export interface EventStatus {
  total: number;
  queued: number;
  processing: number;
  done: number;
  failed: number;
  faces: number;
}

export interface Stats {
  events: number;
  published_events: number;
  photos: number;
  videos: number;
  faces: number;
  failed: number;
  processing: number;
  queue: number | null;
}

export interface UploadResult {
  accepted: { id: string; filename: string }[];
  duplicates: string[];
  rejected: { filename: string; error: string }[];
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  email: string;
}

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string,
    public errors: SelfieErrorItem[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }

  get isNetwork(): boolean {
    return this.status === 0;
  }
}

async function toApiError(res: Response): Promise<ApiError> {
  let code = "ERROR";
  let message = `Request failed (${res.status})`;
  let errors: SelfieErrorItem[] = [];
  try {
    const body = await res.json();
    const detail = body?.detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      code = detail.code ?? code;
      message = detail.message ?? message;
      if (Array.isArray(detail.errors) && detail.errors.every((e: unknown) => typeof e === "object" && e && "code" in e)) {
        errors = detail.errors as SelfieErrorItem[];
      }
    } else if (typeof detail === "string") {
      message = detail;
    }
  } catch {
    /* non-JSON error body */
  }
  if (res.status === 429) code = "RATE_LIMITED";
  return new ApiError(message, res.status, code, errors);
}

interface RequestOptions {
  method?: string;
  json?: unknown;
  form?: FormData;
  token?: string | null;
  signal?: AbortSignal;
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: BodyInit | undefined;
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  } else if (opts.form) {
    body = opts.form;
  }
  if (opts.token) headers.Authorization = `Bearer ${opts.token}`;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api${path}`, { method: opts.method ?? "GET", headers, body, signal: opts.signal });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError("Network error", 0, "NETWORK");
  }
  if (!res.ok) throw await toApiError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface MatchParams {
  selfies: Blob[];
  eventIds?: string[];
  eventTypes?: string[];
  threshold?: number;
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
}

export const publicApi = {
  listEvents: (signal?: AbortSignal) => request<PublicEvent[]>("/events", { signal }),
  eventTypes: (signal?: AbortSignal) => request<{ types: EventType[] }>("/event-types", { signal }),

  match(p: MatchParams): Promise<MatchResponse> {
    const form = new FormData();
    p.selfies.forEach((blob, i) => form.append("selfies", blob, `selfie-${i + 1}.jpg`));
    p.eventIds?.forEach((id) => form.append("event_ids", id));
    p.eventTypes?.forEach((t) => form.append("event_types", t));
    if (p.threshold !== undefined) form.append("threshold", String(p.threshold));
    form.append("limit", String(p.limit ?? 60));
    form.append("offset", String(p.offset ?? 0));
    return request<MatchResponse>("/match", { method: "POST", form, signal: p.signal });
  },

  downloadUrl: (photoId: string) => `${API_BASE}/api/photos/${photoId}/download`,
};

// ---------------------------------------------------------------------------
// Admin API
// ---------------------------------------------------------------------------

export function login(email: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>("/admin/login", { method: "POST", json: { email, password } });
}

export type AdminApi = ReturnType<typeof createAdminApi>;

/** Admin client bound to a token. `onUnauthorized` is called on any 401 (e.g. expired token). */
export function createAdminApi(token: string, onUnauthorized: () => void) {
  async function call<T>(path: string, opts: Omit<RequestOptions, "token"> = {}): Promise<T> {
    try {
      return await request<T>(`/admin${path}`, { ...opts, token });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) onUnauthorized();
      throw err;
    }
  }

  return {
    stats: (signal?: AbortSignal) => call<Stats>("/stats", { signal }),
    listEvents: (signal?: AbortSignal) => call<AdminEvent[]>("/events", { signal }),
    getEvent: (id: string, signal?: AbortSignal) => call<AdminEvent>(`/events/${id}`, { signal }),
    createEvent: (input: EventInput) => call<AdminEvent>("/events", { method: "POST", json: input }),
    updateEvent: (id: string, patch: Partial<EventInput> & { cover_photo_id?: string | null }) =>
      call<AdminEvent>(`/events/${id}`, { method: "PUT", json: patch }),
    deleteEvent: (id: string) => call<void>(`/events/${id}`, { method: "DELETE" }),

    listPhotos: (id: string, page: number, pageSize: number, status?: PhotoStatus, signal?: AbortSignal) => {
      const qs = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
      if (status) qs.set("status", status);
      return call<PhotoPage>(`/events/${id}/photos?${qs}`, { signal });
    },
    status: (id: string, signal?: AbortSignal) => call<EventStatus>(`/events/${id}/status`, { signal }),
    retryFailed: (id: string) => call<{ queued: number }>(`/events/${id}/retry-failed`, { method: "POST" }),
    reindex: (id: string) => call<{ queued: number }>(`/events/${id}/reindex`, { method: "POST" }),
    deletePhoto: (photoId: string) => call<void>(`/photos/${photoId}`, { method: "DELETE" }),

    /** Upload a batch of files with byte-level progress (XHR: fetch has no upload progress). */
    uploadPhotos(
      eventId: string,
      files: File[],
      onProgress?: (loaded: number, total: number) => void,
      signal?: AbortSignal,
    ): Promise<UploadResult> {
      return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", `${API_BASE}/api/admin/events/${eventId}/photos`);
        xhr.setRequestHeader("Authorization", `Bearer ${token}`);
        xhr.setRequestHeader("Accept", "application/json");
        xhr.responseType = "text";
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) onProgress?.(e.loaded, e.total);
        };
        xhr.onload = async () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            try {
              resolve(JSON.parse(xhr.responseText) as UploadResult);
            } catch {
              reject(new ApiError("Invalid server response", xhr.status, "BAD_RESPONSE"));
            }
            return;
          }
          if (xhr.status === 401) onUnauthorized();
          reject(await toApiError(new Response(xhr.responseText, { status: xhr.status })));
        };
        xhr.onerror = () => reject(new ApiError("Network error", 0, "NETWORK"));
        xhr.onabort = () => reject(new DOMException("Upload aborted", "AbortError"));
        signal?.addEventListener("abort", () => xhr.abort(), { once: true });

        const form = new FormData();
        files.forEach((f) => form.append("files", f, f.name));
        xhr.send(form);
      });
    },
  };
}
