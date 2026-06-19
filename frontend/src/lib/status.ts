// Single source of truth for status colour + emphasis across the app, so badges
// form a deliberate hierarchy instead of a uniform pastel wall: the *current*
// release state reads as a solid chip, secondary metadata stays light.

// Release-state colours (names come from states.yaml).
export const STATE_COLORS: Record<string, string> = {
  Draft: "gray",
  "In QA": "yellow",
  Approved: "teal",
  Rejected: "red",
  Cancelled: "dark",
};

export const stateColor = (state: string) => STATE_COLORS[state] ?? "blue";

// Tracker issue status → colour. "Done"-like statuses are calm, open work warns.
const DONE = new Set(["done", "closed", "resolved"]);
const PROGRESS = new Set(["in progress", "in review", "review"]);
export function issueStatusColor(status: string): string {
  const s = status.trim().toLowerCase();
  if (DONE.has(s)) return "teal";
  if (PROGRESS.has(s)) return "blue";
  return "gray"; // To Do / backlog / unknown
}

export const phaseColor = (phase: string) => (phase === "pre" ? "blue" : "grape");
