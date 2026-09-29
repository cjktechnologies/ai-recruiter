/** Server-side configuration (never exposed to the browser). */
export const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";
export const API_PREFIX = "/api/v1";
export const ACCESS_COOKIE = "rec_at";
export const REFRESH_COOKIE = "rec_rt";
export const SECURE_COOKIES = process.env.NODE_ENV === "production";
