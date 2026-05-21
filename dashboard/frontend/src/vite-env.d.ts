/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Public base URL of the FastAPI backend (e.g. https://api.yourdomain.com).
   *  Empty/unset → relative same-origin paths (VPS deploy + local Vite proxy). */
  readonly VITE_API_BASE?: string
  /** Optional explicit WebSocket base (e.g. wss://api.yourdomain.com).
   *  If unset, derived from VITE_API_BASE, else same-origin. */
  readonly VITE_WS_BASE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
