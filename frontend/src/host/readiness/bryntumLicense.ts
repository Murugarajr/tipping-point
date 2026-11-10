/**
 * Registers the Bryntum licence key, if one is configured, before the Gantt module loads.
 * Bryntum 8 reads it from the global `bryntum` object (documented in @bryntum/core-enterprise typings);
 * without a key the Enterprise tier runs in its standard trial mode. The value is never logged.
 */
const key = import.meta.env.VITE_BRYNTUM_LICENSE_KEY?.trim();
if (key) {
  const scope = globalThis as unknown as { bryntum?: { licenseKey?: string } };
  scope.bryntum = scope.bryntum ?? {};
  scope.bryntum.licenseKey = key;
}

export const bryntumLicenseConfigured = Boolean(key);
