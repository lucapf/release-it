import { Badge } from "@mantine/core";
import { stateColor } from "../lib/status";

// Renders a release state with the app-wide colour mapping. `emphasis` makes the
// chip solid — use it for the *current* state of the release in focus so it
// stands out from the lighter, secondary state chips elsewhere on the page.
export function StateBadge({
  state,
  emphasis = false,
  size,
}: {
  state: string;
  emphasis?: boolean;
  size?: string;
}) {
  return (
    <Badge color={stateColor(state)} variant={emphasis ? "filled" : "light"} size={size}>
      {state}
    </Badge>
  );
}
