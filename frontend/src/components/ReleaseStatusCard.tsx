import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Card,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { IconAlertTriangle, IconCheck } from "@tabler/icons-react";
import { getReleaseStatus, Release } from "../api/client";
import { apiErrorMessage } from "../lib/errors";
import { StateBadge } from "./StateBadge";
import { WorkflowActions } from "./WorkflowActions";

// Per-release readiness overview: current state, allowed workflow actions, the
// open (not-yet-closed) tickets, and the uploaded document types.
//
// The issues come from the ticketing system as this renders, so this view can
// fail — and when it does it says so rather than showing a release with no open
// bugs. "We could not reach the tracker" and "there is nothing left to fix" are
// the same picture otherwise, and only one of them means the release is ready.
export function ReleaseStatusCard({ release }: { release: Release }) {
  const { data: status, isLoading, error } = useQuery({
    queryKey: ["status", release.id],
    queryFn: () => getReleaseStatus(release.id),
    retry: false,
  });

  if (isLoading) {
    return (
      <Group justify="center" py="xl">
        <Loader />
      </Group>
    );
  }

  if (error || !status) {
    return (
      <Alert
        color="red"
        variant="light"
        title="Cannot read this release's issues"
        icon={<IconAlertTriangle size={18} />}
      >
        {apiErrorMessage(error, "The issue tracker could not be reached.")} Readiness
        is decided by the ticketing system, so it cannot be shown while the tracker
        is unavailable.
      </Alert>
    );
  }

  return (
    <Stack gap="md">
      <Card withBorder padding="md" radius="md">
        <Group justify="space-between" align="center">
          <Group gap="sm">
            <Title order={4}>v{release.version}</Title>
            <StateBadge state={status.state} />
          </Group>
          {status.is_ready ? (
            <Badge color="teal" variant="filled" leftSection={<IconCheck size={13} />}>Ready</Badge>
          ) : (
            <Badge color="orange" variant="filled" leftSection={<IconAlertTriangle size={13} />}>Action needed</Badge>
          )}
        </Group>
        {release.short_description && (
          <Text size="sm" c="dimmed" mt={4}>{release.short_description}</Text>
        )}
        <Text size="xs" c="dimmed" tt="uppercase" fw={600} mt="md" mb={6}>
          Available actions
        </Text>
        <WorkflowActions release={release} status={status} />
      </Card>

      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
        {/* Open bugs ------------------------------------------------------- */}
        <Card withBorder padding="md" radius="md">
          <Group justify="space-between" mb="xs">
            <Title order={5}>Open bugs</Title>
            <Badge color={status.open_bug_count ? "red" : "teal"} variant="light">
              {status.open_bug_count} open
            </Badge>
          </Group>
          {status.open_bugs.length === 0 ? (
            <Text size="sm" c="dimmed">No unresolved bugs in this release. 🎉</Text>
          ) : (
            <Table verticalSpacing={4} fz="sm">
              <Table.Tbody>
                {status.open_bugs.map((b) => (
                  <Table.Tr key={b.key}>
                    <Table.Td fw={600}>{b.key}</Table.Td>
                    <Table.Td>{b.summary}</Table.Td>
                    <Table.Td>
                      <Badge size="sm" color="red" variant="outline">{b.status}</Badge>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Card>

        {/* Documents ------------------------------------------------------- */}
        <Card withBorder padding="md" radius="md">
          <Title order={5} mb="xs">Documents</Title>
          {status.present_doc_types.length === 0 ? (
            <Text size="sm" c="dimmed">No documents uploaded.</Text>
          ) : (
            /* Approved types are what readiness guards accept; a draft document
               is shown greyed so it's clear it doesn't unblock a transition. */
            <Group gap={6} wrap="wrap">
              {status.present_doc_types.map((t) => {
                const approved = (status.approved_doc_types ?? []).includes(t);
                return (
                  <Badge
                    key={t}
                    size="sm"
                    variant="light"
                    color={approved ? "grape" : "gray"}
                  >
                    {approved ? t : `${t} (draft)`}
                  </Badge>
                );
              })}
            </Group>
          )}
        </Card>
      </SimpleGrid>

      {!status.is_ready && (
        <Alert color="orange" variant="light" title="Not ready to approve">
          {status.open_bug_count > 0 && `${status.open_bug_count} open bug(s).`}
        </Alert>
      )}
    </Stack>
  );
}
