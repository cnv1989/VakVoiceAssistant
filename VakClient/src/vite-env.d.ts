/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_WS_URL?: string;
  readonly VITE_CHAT_API_URL?: string;
  readonly VITE_BUSINESS_NAME?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
