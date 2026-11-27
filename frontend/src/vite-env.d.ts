/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Optional API origin; defaults to same origin ("" -> /api). */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
