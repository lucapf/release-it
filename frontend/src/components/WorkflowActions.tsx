import { Box, Button, Group, Text, Tooltip } from "@mantine/core";
import { IconLock } from "@tabler/icons-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { notifications } from "@mantine/notifications";
import { getWorkflow, transitionRelease, Release } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { notifyApiError } from "../lib/errors";

// Renders only the transitions allowed from the release's current state, and
// disables those the operator's roles don't permit. The backend enforces the
// same rules (states.yaml) — this just keeps the UI honest to the workflow.
export function WorkflowActions({
  release,
  size = "compact-sm",
  onChanged,
}: {
  release: Release;
  size?: string;
  onChanged?: () => void;
}) {
  const qc = useQueryClient();
  const { hasRole } = useAuth();
  const { data: workflow } = useQuery({
    queryKey: ["workflow"],
    queryFn: getWorkflow,
    staleTime: Infinity,
  });

  const move = useMutation({
    mutationFn: (transition: string) => transitionRelease(release.id, transition),
    onSuccess: (_data, transition) => {
      qc.invalidateQueries({ queryKey: ["releases", release.product_id] });
      qc.invalidateQueries({ queryKey: ["overview"] });
      qc.invalidateQueries({ queryKey: ["status", release.id] });
      qc.invalidateQueries({ queryKey: ["history", release.id] });
      notifications.show({ message: `Applied "${transition}"`, color: "teal" });
      onChanged?.();
    },
    onError: (e: any) => notifyApiError(e, "Transition not allowed"),
  });

  const state = workflow?.states.find((s) => s.name === release.state);
  if (!state) return null;
  if (state.transitions.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        No actions — <b>{release.state}</b> is a final state.
      </Text>
    );
  }

  // Surface *why* an action is unavailable without requiring a hover: any
  // transition the operator can't perform contributes a short, persistent hint.
  const blockedRoles = new Set<string>();
  state.transitions.forEach((t) => {
    if (!hasRole(...t.roles)) t.roles.forEach((r) => blockedRoles.add(r));
  });

  return (
    <Group gap={6} align="center">
      {state.transitions.map((t) => {
        const permitted = hasRole(...t.roles);
        return (
          <Tooltip
            key={t.name}
            label={permitted ? `→ ${t.target}` : `Requires role: ${t.roles.join(", ")}`}
            withArrow
          >
            <Box component="span">
              <Button
                size={size}
                variant={permitted ? "light" : "default"}
                disabled={!permitted}
                leftSection={!permitted ? <IconLock size={13} /> : undefined}
                loading={move.isPending && move.variables === t.name}
                onClick={() => move.mutate(t.name)}
              >
                {t.name}
              </Button>
            </Box>
          </Tooltip>
        );
      })}
      {blockedRoles.size > 0 && (
        <Text size="xs" c="dimmed">
          Locked actions need: {[...blockedRoles].join(", ")}
        </Text>
      )}
    </Group>
  );
}
