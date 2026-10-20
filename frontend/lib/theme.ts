// Shared by the server layout and the client toggle, so it can't live in a
// "use client" module (the server would get a reference, not the string).
export type Theme = "system" | "light" | "dark";
export const THEME_COOKIE = "resume-tailor-theme";
