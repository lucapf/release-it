import { Release } from "../api/client";

// The three release "slots" the dashboard and product view revolve around.
// The releases list from the API is ordered newest-first (created_at DESC),
// so the first match in each state is the most recent one.
export type ReleaseKind = "stable" | "approval" | "draft";

export const pickStable = (releases: Release[]): Release | null =>
  releases.find((r) => r.state === "Approved") ?? null;

export const pickApproval = (releases: Release[]): Release | null =>
  releases.find((r) => r.state === "In QA") ?? null;

export const pickDraft = (releases: Release[]): Release | null =>
  releases.find((r) => r.state === "Draft") ?? null;

export const KIND_LABEL: Record<ReleaseKind, string> = {
  stable: "Last stable",
  approval: "Under approval",
  draft: "Draft",
};
