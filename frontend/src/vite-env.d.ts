/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** AG Studio licence key, applied via <AgStudioProvider licenseKey>. Set in frontend/.env.local (git-ignored). */
  readonly VITE_AG_STUDIO_LICENSE_KEY?: string;
  /** Bryntum (Business tier) licence key, set as globalThis.bryntum.licenseKey. Set in frontend/.env.local (git-ignored). */
  readonly VITE_BRYNTUM_LICENSE_KEY?: string;
}
