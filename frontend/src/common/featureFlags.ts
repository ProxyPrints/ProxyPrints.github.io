/**
 * Build-time feature flags, gated the same way `isGoogleDriveAppConfigured` gates Google
 * Drive (a boolean `NEXT_PUBLIC_*` env var, empty/absent means off) - see
 * `features/googleDrive/googleDriveConfig.ts`. Unlike that one, this isn't "is a required
 * secret present" but a plain on/off switch, so it must equal the literal string "true"
 * rather than merely being non-empty - any other value (including a typo) stays off.
 */
export const isUnifiedDisplayPageEnabled = (): boolean =>
  process.env.NEXT_PUBLIC_UNIFIED_DISPLAY_ENABLED === "true";
