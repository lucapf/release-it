import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Card,
  Group,
  List,
  Loader,
  SimpleGrid,
  Stack,
  Table,
  Text,
  ThemeIcon,
  Title,
} from "@mantine/core";
import { IconAlertTriangle, IconCheck, IconX } from "@tabler/icons-react";
import { getReleaseStatus, Release } from "../api/client";
import { StateBadge } from "./StateBadge";
import { WorkflowActions } from "./WorkflowActions";

// Per-release readiness overview: current state, allowed workflow actions, the
// open (not-yet-closed) Jira bugs, the required-documentation checklist, and
// outstanding pre/post checks.
export function ReleaseStatusCard({ release }: { release: Release }) {
  const { data: status, isLoading } = useQuery({
    queryKey: ["status", release.id],
    queryFn: () => getReleaseStatus(release.id),
  });

  if (isLoading || !status) {
    return (
      <Group justify="center" py="xl">
        <Loader />
      </Group>
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
        <WorkflowActions release={release} />
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
                  <Table.Tr key={b.id}>
                    <Table.Td fw={600}>{b.issue_key}</Table.Td>
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

        {/* Documentation + checks ----------------------------------------- */}
        <Card withBorder padding="md" radius="md">
          <Title order={5} mb="xs">Documentation</Title>
          <List spacing={4} size="sm" center>
            {status.required_docs.map((d) => (
              <List.Item
                key={d.label}
                icon={
                  <ThemeIcon color={d.present ? "teal" : "red"} size={18} radius="xl">
                    {d.present ? <IconCheck size={12} /> : <IconX size={12} />}
                  </ThemeIcon>
                }
              >
                {d.label}{" "}
                {!d.present && <Text span size="xs" c="red">(missing)</Text>}
              </List.Item>
            ))}
          </List>

          {status.total_checks > 0 && (
            <>
              <Title order={5} mt="md" mb="xs">Checks</Title>
              <Text size="sm" c={status.pending_checks ? "orange" : "teal"}>
                {status.total_checks - status.pending_checks}/{status.total_checks} done
                {status.pending_checks > 0 && ` · ${status.pending_checks} pending`}
              </Text>
            </>
          )}
        </Card>
      </SimpleGrid>

      {!status.is_ready && (
        <Alert color="orange" variant="light" title="Not ready to approve">
          {status.open_bug_count > 0 && `${status.open_bug_count} open bug(s). `}
          {status.missing_docs.length > 0 &&
            `Missing docs: ${status.missing_docs.join(", ")}. `}
          {status.pending_checks > 0 && `${status.pending_checks} pending check(s).`}
        </Alert>
      )}
    </Stack>
  );
}
