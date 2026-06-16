import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  getProduct,
  listReleases,
  createRelease,
  transitionRelease,
  listDocumentation,
  addDocumentation,
  generateReleaseNotes,
  listJiraIssues,
  syncJira,
  Release,
} from "../api/client";
import { StateBadge } from "../components/StateBadge";

const TRANSITIONS = ["Ready", "Approve", "Reject", "Cancel"];

// --- Releases tab ----------------------------------------------------------
function ReleasesTab({ productId, releases }: { productId: number; releases: Release[] }) {
  const qc = useQueryClient();
  const [version, setVersion] = useState("1.0.0");
  const invalidate = () => qc.invalidateQueries({ queryKey: ["releases", productId] });

  const add = useMutation({
    mutationFn: () => createRelease(productId, version),
    onSuccess: () => {
      invalidate();
      qc.invalidateQueries({ queryKey: ["overview"] });
      notifications.show({ message: "Release created", color: "teal" });
    },
    onError: () => notifications.show({ message: "Could not create release", color: "red" }),
  });
  const move = useMutation({
    mutationFn: ({ id, t }: { id: number; t: string }) => transitionRelease(id, t),
    onSuccess: () => {
      invalidate();
      qc.invalidateQueries({ queryKey: ["overview"] });
    },
    onError: (e: any) =>
      notifications.show({
        message: e?.response?.data?.detail ?? "Transition not allowed",
        color: "red",
      }),
  });

  return (
    <Stack gap="md">
      <Group gap="xs">
        <TextInput
          value={version}
          onChange={(e) => setVersion(e.currentTarget.value)}
          placeholder="1.2.0"
          label="New release version"
        />
        <Button mt="auto" loading={add.isPending} onClick={() => add.mutate()}>
          Add release
        </Button>
      </Group>

      {releases.length === 0 ? (
        <Text c="dimmed">No releases yet.</Text>
      ) : (
        <Table highlightOnHover verticalSpacing="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Version</Table.Th>
              <Table.Th>State</Table.Th>
              <Table.Th>Transitions</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {releases.map((r) => (
              <Table.Tr key={r.id}>
                <Table.Td fw={600}>v{r.version}</Table.Td>
                <Table.Td><StateBadge state={r.state} /></Table.Td>
                <Table.Td>
                  <Group gap={6}>
                    {TRANSITIONS.map((t) => (
                      <Button
                        key={t}
                        size="compact-xs"
                        variant="default"
                        loading={move.isPending && move.variables?.id === r.id && move.variables?.t === t}
                        onClick={() => move.mutate({ id: r.id, t })}
                      >
                        {t}
                      </Button>
                    ))}
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}

// Shared release picker used by the Documentation and Jira tabs.
function ReleasePicker({
  releases,
  value,
  onChange,
}: {
  releases: Release[];
  value: number | null;
  onChange: (id: number) => void;
}) {
  return (
    <Select
      label="Release"
      placeholder="Select a release"
      data={releases.map((r) => ({ value: String(r.id), label: `v${r.version} · ${r.state}` }))}
      value={value ? String(value) : null}
      onChange={(v) => v && onChange(Number(v))}
      maw={280}
      allowDeselect={false}
    />
  );
}

// --- Documentation tab -----------------------------------------------------
function DocumentationTab({ releaseId }: { releaseId: number }) {
  const qc = useQueryClient();
  const key = ["documentation", releaseId];
  const { data: docs = [] } = useQuery({ queryKey: key, queryFn: () => listDocumentation(releaseId) });
  const [filename, setFilename] = useState("release-notes.md");
  const [text, setText] = useState("");

  const add = useMutation({
    mutationFn: () => addDocumentation(releaseId, filename || "document.md", text),
    onSuccess: () => {
      setText("");
      qc.invalidateQueries({ queryKey: key });
      notifications.show({ message: "Documentation added", color: "teal" });
    },
    onError: (e: any) =>
      notifications.show({ message: e?.response?.data?.detail ?? "Upload failed", color: "red" }),
  });
  const generate = useMutation({
    mutationFn: () => generateReleaseNotes(releaseId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: key });
      notifications.show({ message: "Draft release notes generated from Jira issues", color: "teal" });
    },
  });

  return (
    <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
      <Card withBorder padding="md">
        <Group justify="space-between" mb="sm">
          <Title order={5}>Documents</Title>
          <Button size="compact-sm" variant="light" loading={generate.isPending} onClick={() => generate.mutate()}>
            Generate from Jira
          </Button>
        </Group>
        {docs.length === 0 ? (
          <Text c="dimmed" size="sm">No documentation yet.</Text>
        ) : (
          <Stack gap="xs">
            {docs.map((d) => (
              <Group key={d.id} justify="space-between">
                <Text size="sm">📄 {d.name}</Text>
                {d.is_draft ? <Badge size="sm" color="yellow" variant="light">draft</Badge> : <Badge size="sm" color="teal" variant="light">final</Badge>}
              </Group>
            ))}
          </Stack>
        )}
      </Card>

      <Card withBorder padding="md">
        <Title order={5} mb="sm">Add documentation</Title>
        <Stack gap="sm">
          <TextInput
            label="File name"
            value={filename}
            onChange={(e) => setFilename(e.currentTarget.value)}
          />
          <Textarea
            label="Content (Markdown)"
            autosize
            minRows={6}
            value={text}
            onChange={(e) => setText(e.currentTarget.value)}
            placeholder="# Release notes&#10;..."
          />
          <Button disabled={!text} loading={add.isPending} onClick={() => add.mutate()}>
            Save document
          </Button>
        </Stack>
      </Card>
    </SimpleGrid>
  );
}

// --- Jira tab --------------------------------------------------------------
function JiraTab({ releaseId }: { releaseId: number }) {
  const qc = useQueryClient();
  const key = ["jira", releaseId];
  const { data: issues = [] } = useQuery({ queryKey: key, queryFn: () => listJiraIssues(releaseId) });
  const [mode, setMode] = useState<"label" | "jql">("label");
  const [label, setLabel] = useState("");
  const [jql, setJql] = useState("");

  const sync = useMutation({
    mutationFn: () =>
      syncJira(releaseId, mode === "jql" ? { jql } : { release_label: label }),
    onSuccess: (data) => {
      qc.setQueryData(key, data);
      notifications.show({ message: `Synced ${data.length} issue(s) from Jira`, color: "teal" });
    },
    onError: (e: any) =>
      notifications.show({ message: e?.response?.data?.detail ?? "Jira sync failed", color: "red" }),
  });

  return (
    <Stack gap="md">
      <Card withBorder padding="md">
        <Group justify="space-between" mb="xs">
          <Title order={5}>Sync issues from Jira</Title>
          <Badge variant="dot" color="gray">stub integration</Badge>
        </Group>
        <Text size="sm" c="dimmed" mb="sm">
          Fetch the issues contained in this release. Filter by a release label, or
          provide a custom JQL query.
        </Text>
        <Group align="flex-end" gap="sm">
          <Select
            label="Filter by"
            data={[
              { value: "label", label: "Release label" },
              { value: "jql", label: "Custom JQL" },
            ]}
            value={mode}
            onChange={(v) => setMode((v as "label" | "jql") ?? "label")}
            maw={160}
            allowDeselect={false}
          />
          {mode === "label" ? (
            <TextInput
              label="Release label"
              placeholder="e.g. 2025-Q3"
              value={label}
              onChange={(e) => setLabel(e.currentTarget.value)}
              style={{ flex: 1 }}
            />
          ) : (
            <TextInput
              label="JQL query"
              placeholder='project = REL AND fixVersion = "1.2.0"'
              value={jql}
              onChange={(e) => setJql(e.currentTarget.value)}
              style={{ flex: 1 }}
            />
          )}
          <Button loading={sync.isPending} onClick={() => sync.mutate()}>
            Sync now
          </Button>
        </Group>
      </Card>

      {issues.length === 0 ? (
        <Text c="dimmed">No issues synced yet.</Text>
      ) : (
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Key</Table.Th>
              <Table.Th>Type</Table.Th>
              <Table.Th>Summary</Table.Th>
              <Table.Th>Status</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {issues.map((i) => (
              <Table.Tr key={i.id}>
                <Table.Td fw={600}>{i.issue_key}</Table.Td>
                <Table.Td><Badge size="sm" variant="light">{i.issue_type}</Badge></Table.Td>
                <Table.Td>{i.summary}</Table.Td>
                <Table.Td>{i.status}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}

// --- Page ------------------------------------------------------------------
export function ProductDetailPage() {
  const { productId } = useParams();
  const id = Number(productId);
  const { data: product } = useQuery({ queryKey: ["product", id], queryFn: () => getProduct(id) });
  const { data: releases = [], isLoading } = useQuery({
    queryKey: ["releases", id],
    queryFn: () => listReleases(id),
  });

  // Default the doc/Jira release selector to the newest release.
  const [selected, setSelected] = useState<number | null>(null);
  const activeReleaseId = useMemo(
    () => selected ?? releases[0]?.id ?? null,
    [selected, releases]
  );

  if (isLoading) {
    return <Group justify="center" py="xl"><Loader /></Group>;
  }

  return (
    <Stack gap="lg">
      <div>
        <Anchor component={Link} to="/dashboard" size="sm">← Dashboard</Anchor>
        <Title order={2} mt={4}>{product?.name ?? `Product #${id}`}</Title>
        <Text c="dimmed">{releases.length} release{releases.length === 1 ? "" : "s"}</Text>
      </div>

      <Tabs defaultValue="releases" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="releases">Releases</Tabs.Tab>
          <Tabs.Tab value="documentation">Documentation</Tabs.Tab>
          <Tabs.Tab value="jira">Jira issues</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="releases" pt="md">
          <ReleasesTab productId={id} releases={releases} />
        </Tabs.Panel>

        <Tabs.Panel value="documentation" pt="md">
          {activeReleaseId ? (
            <Stack gap="md">
              <ReleasePicker releases={releases} value={activeReleaseId} onChange={setSelected} />
              <DocumentationTab releaseId={activeReleaseId} />
            </Stack>
          ) : (
            <Text c="dimmed">Create a release first to attach documentation.</Text>
          )}
        </Tabs.Panel>

        <Tabs.Panel value="jira" pt="md">
          {activeReleaseId ? (
            <Stack gap="md">
              <ReleasePicker releases={releases} value={activeReleaseId} onChange={setSelected} />
              <JiraTab releaseId={activeReleaseId} />
            </Stack>
          ) : (
            <Text c="dimmed">Create a release first to sync Jira issues.</Text>
          )}
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
