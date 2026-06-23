import { Box, Button, Group, Text, Tooltip } from "@mantine/core";
import { IconAlertTriangle, IconLock } from "@tabler/icons-react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { notifications } from "@mantine/notifications";
import { getWorkflow, transitionRelease, Release, ReleaseStatusSummary } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { notifyApiError } from "../lib/errors";

// Readiness guards a transition can declare (mirrors states.yaml `requires`).
// Each maps to the reason it is unmet given the current release status.
function unmetRequirements(
  requires: string[],
  status?: ReleaseStatusSummary,
): string[] {
  if (!status) return [];
  const reasons: string[] = [];
  if (requires.includes("no_open_issues") && status.open_bug_count > 0)
    reasons.push(`${status.open_bug_count} open issue(s) must be closed`);
  if (requires.includes("docs_complete") && status.missing_docs.length > 0)
    reasons.push(`missing docs: ${status.missing_docs.join(", ")}`);
  if (requires.includes("checks_done") && status.pending_checks > 0)
    reasons.push(`${status.pending_checks} check(s) pending`);
  // Parameterised guard: document:<TypeName> needs an uploaded document of that type.
  const present = new Set(status.present_doc_types ?? []);
  requires
    .filter((r) => r.startsWith("document:"))
    .map((r) => r.slice("document:".length))
    .filter((docType) => !present.has(docType))
    .forEach((docType) => reasons.push(`missing document: ${docType}`));
  return reasons;
}

// Renders only the transitions allowed from the release's current state, and
// disables those the operator's roles don't permit or whose readiness guards
// aren't met. The backend enforces the same rules (states.yaml) — this just
// keeps the UI honest to the workflow.
export function WorkflowActions({
  release,
  status,
  size = "compact-sm",
  onChanged,
}: {
  release: Release;
  status?: ReleaseStatusSummary;
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
        const unmet = permitted ? unmetRequirements(t.requires, status) : [];
        const blocked = unmet.length > 0;
        const tip = !permitted
          ? `Requires role: ${t.roles.join(", ")}`
          : blocked
            ? `Blocked: ${unmet.join("; ")}`
            : `→ ${t.target}`;
        return (
          <Tooltip key={t.name} label={tip} withArrow multiline maw={260}>
            <Box component="span">
              <Button
                size={size}
                variant={permitted && !blocked ? "light" : "default"}
                color={blocked ? "orange" : undefined}
                disabled={!permitted || blocked}
                leftSection={
                  !permitted ? <IconLock size={13} /> : blocked ? <IconAlertTriangle size={13} /> : undefined
                }
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
