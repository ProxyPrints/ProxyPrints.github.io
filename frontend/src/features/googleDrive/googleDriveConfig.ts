export const isGoogleDriveAppConfigured = (): boolean =>
  (process.env.NEXT_PUBLIC_GOOGLE_DRIVE_CLIENT_ID ?? "") !== "" &&
  (process.env.NEXT_PUBLIC_GOOGLE_DRIVE_APP_ID ?? "") !== "";
