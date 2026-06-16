import { Badge } from "@mantine/core";

// Map release-state names (states.yaml) to a consistent colour across the app.
const STATE_COLORS: Record<string, string> = {
  Draft: "gray",
  "In QA": "yellow",
  Approved: "teal",
  Rejected: "red",
  Cancelled: "dark",
};

export function StateBadge({ state }: { state: string }) {
  return (
    <Badge color={STATE_COLORS[state] ?? "blue"} variant="light">
      {state}
    </Badge>
  );
}
