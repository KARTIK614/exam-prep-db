/// <reference types="vite/client" />

// Extend the standard `ImportMetaEnv` with the app's custom VITE_ vars so
// consumers get type-checked access via `import.meta.env.VITE_API_URL`.
interface ImportMetaEnv {
  readonly VITE_API_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
