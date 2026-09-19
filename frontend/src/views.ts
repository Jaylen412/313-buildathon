/**
 * The app's top-level views. Lives here rather than in App.tsx so components
 * (Sidebar, and the neighborhoods page) don't have to import from their own
 * parent.
 */
export type ViewName = "home" | "map" | "neighborhoods" | "insights" | "settings";
