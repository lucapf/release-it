import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  Loader,
  SegmentedControl,
  Select,
  SimpleGrid,
  Skeleton,
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
  IconChecklist,
  IconClipboardText,
  IconFile,
  IconFileText,
  IconHistory,
  IconListDetails,
  IconRocket,
  IconTrash,
  IconBrandGithub,
} from "@tabler/icons-react";
import {
  getProduct,
  updateProduct,
  getConfig,
  listReleases,
  createRelease,
  listDocumentation,
  addDocumentation,
  generateReleaseNotes,
  listJiraIssues,
  syncJira,
  getReleaseHistory,
  listChecks,
  addCheck,
  setCheckDone,
  deleteCheck,
  Product,
  Release,
  AuditEntry,
  Phase,
} from "../api/client";
import { StateBadge } from "../components/StateBadge";
import { WorkflowActions } from "../components/WorkflowActions";
import { ReleaseStatusCard } from "../components/ReleaseStatusCard";
import { EmptyState } from "../components/EmptyState";
import { useAuth } from "../auth/AuthContext";
import { notifyApiError } from "../lib/errors";
import { issueStatusColor } from "../lib/status";
import {
  ReleaseKind,
  KIND_LABEL,
  pickStable,
  pickApproval,
  pickDraft,
} from "../lib/releases";

// --- Release selector (segmented quick-access + full dropdown) -------------
function ReleaseSelector({
  releases,
  byKind,
  value,
  onChange,
}: {
  releases: Release[];
  byKind: Record<ReleaseKind, Release | null>;
  value: number | null;
  onChange: (id: number) => void;
}) {
  const kinds = (Object.keys(byKind) as ReleaseKind[]).filter((k) => byKind[k]);
  return (
    <Group justify="space-between" align="flex-end" wrap="wrap">
      {kinds.length > 0 && (
        <div>
          <Text size="xs" c="dimmed" fw={600} mb={4}>Quick select</Text>
          <SegmentedControl
            size="sm"
            data={kinds.map((k) => ({ value: k, label: KIND_LABEL[k] }))}
            value={kinds.find((k) => byKind[k]?.id === value) ?? ""}
            onChange={(k) => {
              const r = byKind[k as ReleaseKind];
              if (r) onChange(r.id);
            }}
          />
        </div>
      )}
      <Select
        label="Viewing release"
        data={releases.map((r) => ({ value: String(r.id), label: `v${r.version} · ${r.state}` }))}
        value={value ? String(value) : null}
        onChange={(v) => v && onChange(Number(v))}
        maw={260}
        allowDeselect={false}
      />
    </Group>
  );
}

// --- Releases tab ----------------------------------------------------------
function ReleasesTab({ productId, releases }: { productId: number; releases: Release[] }) {
  const qc = useQueryClient();
  const { hasRole } = useAuth();
  const canCreate = hasRole("Developer", "Release Manager", "Administrator");
  const [version, setVersion] = useState("1.0.0");

  const add = useMutation({
    mutationFn: () => createRelease(productId, version),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["releases", productId] });
      qc.invalidateQueries({ queryKey: ["overview"] });
      notifications.show({ message: "Release created", color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Could not create release"),
  });

  return (
    <Stack gap="md">
      {canCreate && (
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
      )}

      {releases.length === 0 ? (
        <Card>
          <EmptyState
            icon={IconRocket}
            title="No releases yet"
            description={canCreate ? "Add the first release above to begin tracking it through the workflow." : "Releases for this product will appear here."}
          />
        </Card>
      ) : (
        <Table.ScrollContainer minWidth={420}>
          <Table highlightOnHover verticalSpacing="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Version</Table.Th>
                <Table.Th>State</Table.Th>
                <Table.Th>Allowed actions</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {releases.map((r) => (
                <Table.Tr key={r.id}>
                  <Table.Td fw={600}>v{r.version}</Table.Td>
                  <Table.Td><StateBadge state={r.state} /></Table.Td>
                  <Table.Td><WorkflowActions release={r} size="compact-xs" /></Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
}

// --- Documentation tab -----------------------------------------------------
function DocumentationTab({ releaseId }: { releaseId: number }) {
  const qc = useQueryClient();
  const { hasRole } = useAuth();
  const canEdit = hasRole("Developer", "Release Manager", "Administrator");
  const key = ["documentation", releaseId];
  const { data: docs = [] } = useQuery({ queryKey: key, queryFn: () => listDocumentation(releaseId) });
  const [filename, setFilename] = useState("release-notes.md");
  const [text, setText] = useState("");

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: ["status", releaseId] });
  };
  const add = useMutation({
    mutationFn: () => addDocumentation(releaseId, filename || "document.md", text),
    onSuccess: () => {
      setText("");
      invalidate();
      notifications.show({ message: "Documentation added", color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Upload failed"),
  });
  const generate = useMutation({
    mutationFn: () => generateReleaseNotes(releaseId),
    onSuccess: () => {
      invalidate();
      notifications.show({ message: "Draft release notes generated from Jira issues", color: "teal" });
    },
  });

  return (
    <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
      <Card withBorder padding="md">
        <Group justify="space-between" mb="sm">
          <Title order={5}>Documents</Title>
          {canEdit && (
            <Button size="compact-sm" variant="light" loading={generate.isPending} onClick={() => generate.mutate()}>
              Generate from Jira
            </Button>
          )}
        </Group>
        {docs.length === 0 ? (
          <Text c="dimmed" size="sm">No documentation yet.</Text>
        ) : (
          <Stack gap="xs">
            {docs.map((d) => (
              <Group key={d.id} justify="space-between" wrap="nowrap">
                <Group gap={6} wrap="nowrap">
                  <IconFileText size={16} stroke={1.6} color="var(--mantine-color-dimmed)" />
                  <Text size="sm">{d.name}</Text>
                </Group>
                {d.is_draft ? <Badge size="sm" color="yellow" variant="light">draft</Badge> : <Badge size="sm" color="teal" variant="light">final</Badge>}
              </Group>
            ))}
          </Stack>
        )}
      </Card>

      {canEdit && (
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
      )}
    </SimpleGrid>
  );
}

// --- Per-product repository binding (GitHub) --------------------------------
function RepoBinding({ product, canEdit }: { product: Product; canEdit: boolean }) {
  const qc = useQueryClient();
  const [repo, setRepo] = useState(product.tracker_repo);
  useEffect(() => setRepo(product.tracker_repo), [product.tracker_repo]);

  const save = useMutation({
    mutationFn: () => updateProduct(product.id, { tracker_repo: repo.trim() }),
    onSuccess: (p) => {
      qc.setQueryData(["product", product.id], p);
      qc.invalidateQueries({ queryKey: ["overview"] });
      notifications.show({ message: "Repository updated", color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Could not update repository"),
  });

  const dirty = repo.trim() !== product.tracker_repo;
  return (
    <Group align="flex-end" gap="sm" mb="sm">
      <TextInput
        label="Repository (this product)"
        description="GitHub owner/repo this product's issues live in"
        placeholder="owner/repo"
        leftSection={<IconBrandGithub size={15} />}
        value={repo}
        onChange={(e) => setRepo(e.currentTarget.value)}
        disabled={!canEdit}
        style={{ flex: 1 }}
      />
      {canEdit && (
        <Button variant="light" disabled={!dirty} loading={save.isPending} onClick={() => save.mutate()}>
          Save repo
        </Button>
      )}
    </Group>
  );
}

// --- Issues tab (tracker-aware: Jira or GitHub) ----------------------------
function JiraTab({
  releaseId,
  product,
  version,
}: {
  releaseId: number;
  product: Product;
  version: string;
}) {
  const qc = useQueryClient();
  const { hasRole } = useAuth();
  const canSync = hasRole("Developer", "Release Manager", "Administrator");
  const key = ["jira", releaseId];
  const { data: issues = [] } = useQuery({ queryKey: key, queryFn: () => listJiraIssues(releaseId) });
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });

  const provider = cfg?.tracker_provider ?? "jira";
  const isGitHub = provider === "github";
  const trackerName = isGitHub ? "GitHub" : "Jira";
  const repoMissing = isGitHub && !product.tracker_repo.trim();

  // GitHub filters by milestone (default) or label; Jira by label or raw JQL.
  const [ghMode, setGhMode] = useState<"milestone" | "label">("milestone");
  const [jiraMode, setJiraMode] = useState<"label" | "jql">("label");
  const [milestone, setMilestone] = useState("");
  const [label, setLabel] = useState("");
  const [jql, setJql] = useState("");

  const sync = useMutation({
    mutationFn: () => {
      if (isGitHub) {
        return syncJira(releaseId, ghMode === "label" ? { release_label: label } : { milestone });
      }
      return syncJira(releaseId, jiraMode === "jql" ? { jql } : { release_label: label });
    },
    onSuccess: (data) => {
      qc.setQueryData(key, data);
      qc.invalidateQueries({ queryKey: ["status", releaseId] });
      notifications.show({ message: `Synced ${data.length} issue(s) from ${trackerName}`, color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Issue sync failed"),
  });

  return (
    <Stack gap="md">
      {canSync && (
        <Card withBorder padding="md">
          <Group justify="space-between" mb="xs">
            <Title order={5}>Sync issues from {trackerName}</Title>
            <Badge
              variant="light"
              color={isGitHub ? "dark" : "blue"}
              leftSection={isGitHub ? <IconBrandGithub size={12} /> : undefined}
            >
              active tracker: {trackerName}
            </Badge>
          </Group>
          <Text size="sm" c="dimmed" mb="sm">
            {isGitHub
              ? "Fetch the issues for this release from GitHub. By default they are matched by the milestone named after the release version; you can also filter by a label."
              : "Fetch the issues for this release from Jira. Filter by a release label, or provide a custom JQL query."}
          </Text>

          {isGitHub && <RepoBinding product={product} canEdit={canSync} />}

          {repoMissing ? (
            <Alert color="orange" variant="light">
              Set this product's GitHub repository above before syncing.
            </Alert>
          ) : (
            <Group align="flex-end" gap="sm">
              {isGitHub ? (
                <>
                  <Select
                    label="Filter by"
                    data={[
                      { value: "milestone", label: "Milestone" },
                      { value: "label", label: "Label" },
                    ]}
                    value={ghMode}
                    onChange={(v) => setGhMode((v as "milestone" | "label") ?? "milestone")}
                    maw={150}
                    allowDeselect={false}
                  />
                  {ghMode === "milestone" ? (
                    <TextInput
                      label="Milestone"
                      placeholder={version || "e.g. 0.1.0"}
                      description={`Defaults to the release version (${version})`}
                      value={milestone}
                      onChange={(e) => setMilestone(e.currentTarget.value)}
                      style={{ flex: 1 }}
                    />
                  ) : (
                    <TextInput
                      label="Label"
                      placeholder="e.g. release/0.1.0"
                      value={label}
                      onChange={(e) => setLabel(e.currentTarget.value)}
                      style={{ flex: 1 }}
                    />
                  )}
                </>
              ) : (
                <>
                  <Select
                    label="Filter by"
                    data={[
                      { value: "label", label: "Release label" },
                      { value: "jql", label: "Custom JQL" },
                    ]}
                    value={jiraMode}
                    onChange={(v) => setJiraMode((v as "label" | "jql") ?? "label")}
                    maw={160}
                    allowDeselect={false}
                  />
                  {jiraMode === "label" ? (
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
                </>
              )}
              <Button loading={sync.isPending} onClick={() => sync.mutate()}>
                Sync now
              </Button>
            </Group>
          )}
        </Card>
      )}

      {issues.length === 0 ? (
        <Card>
          <EmptyState
            icon={IconListDetails}
            title="No issues synced yet"
            description={canSync ? "Use the panel above to pull issues for this release from the active tracker." : "Synced tracker issues will appear here."}
          />
        </Card>
      ) : (
        <Table.ScrollContainer minWidth={520}>
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
                  <Table.Td><Badge size="sm" variant="light" color="gray">{i.issue_type}</Badge></Table.Td>
                  <Table.Td>{i.summary}</Table.Td>
                  <Table.Td>
                    <Badge size="sm" variant="light" color={issueStatusColor(i.status)}>{i.status}</Badge>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
}

// --- Checks tab ------------------------------------------------------------
function ChecksTab({ releaseId }: { releaseId: number }) {
  const qc = useQueryClient();
  const { hasRole } = useAuth();
  const canEdit = hasRole("Release Manager", "Administrator");
  const key = ["checks", releaseId];
  const { data: checks = [], isLoading } = useQuery({ queryKey: key, queryFn: () => listChecks(releaseId) });
  const [label, setLabel] = useState("");
  const [phase, setPhase] = useState<Phase>("pre");

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: ["status", releaseId] });
  };
  const add = useMutation({
    mutationFn: () => addCheck(releaseId, label, phase),
    onSuccess: () => { setLabel(""); invalidate(); },
    onError: (e: any) => notifyApiError(e, "Could not add check"),
  });
  const toggle = useMutation({
    mutationFn: ({ id, done }: { id: number; done: boolean }) => setCheckDone(id, done),
    onSuccess: invalidate,
  });
  const remove = useMutation({ mutationFn: (id: number) => deleteCheck(id), onSuccess: invalidate });

  if (isLoading) return <Group justify="center" py="xl"><Loader /></Group>;

  const groups: Phase[] = ["pre", "post"];
  return (
    <Stack gap="md">
      {groups.map((g) => {
        const items = checks.filter((c) => c.phase === g);
        return (
          <Card key={g} withBorder radius="md" padding="md">
            <Title order={5} mb="xs" tt="capitalize">{g}-installation checks</Title>
            {items.length === 0 ? (
              <Text c="dimmed" size="sm">No {g} checks.</Text>
            ) : (
              <Stack gap={6}>
                {items.map((c) => (
                  <Group key={c.id} justify="space-between">
                    <Checkbox
                      label={c.label}
                      checked={c.done}
                      disabled={!canEdit || toggle.isPending}
                      onChange={(e) => toggle.mutate({ id: c.id, done: e.currentTarget.checked })}
                    />
                    {canEdit && (
                      <ActionIcon variant="subtle" color="red" aria-label="Delete" onClick={() => remove.mutate(c.id)}>
                        <IconTrash size={16} />
                      </ActionIcon>
                    )}
                  </Group>
                ))}
              </Stack>
            )}
          </Card>
        );
      })}

      {canEdit && (
        <Card withBorder radius="md" padding="md">
          <Group align="flex-end" gap="sm">
            <Select
              label="Phase"
              data={[{ value: "pre", label: "pre" }, { value: "post", label: "post" }]}
              value={phase}
              onChange={(v) => setPhase((v as Phase) ?? "pre")}
              maw={120}
              allowDeselect={false}
            />
            <TextInput
              label="New check"
              placeholder="e.g. Backup taken"
              value={label}
              onChange={(e) => setLabel(e.currentTarget.value)}
              style={{ flex: 1 }}
            />
            <Button disabled={!label} loading={add.isPending} onClick={() => add.mutate()}>Add check</Button>
          </Group>
        </Card>
      )}
    </Stack>
  );
}

// --- History tab -----------------------------------------------------------
const ACTION_LABEL: Record<string, string> = {
  created: "Created",
  status_update: "State change",
  inherited: "Inherited",
  jira_sync: "Jira sync",
};

function describeChange(e: AuditEntry): string {
  if (e.action === "status_update") return `${e.old_value ?? "?"} → ${e.new_value ?? "?"}`;
  if (e.action === "created") return `Initial state: ${e.new_value ?? "?"}`;
  if (e.action === "inherited") return `From release #${e.old_value} → #${e.new_value}`;
  if (e.action === "jira_sync") return e.new_value ?? "";
  return [e.old_value, e.new_value].filter(Boolean).join(" → ");
}

function HistoryTab({ releaseId }: { releaseId: number }) {
  const { data: entries = [], isLoading } = useQuery({
    queryKey: ["history", releaseId],
    queryFn: () => getReleaseHistory(releaseId),
  });

  if (isLoading) return <Group justify="center" py="xl"><Loader /></Group>;
  if (entries.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={IconHistory}
          title="No history yet"
          description="State changes, syncs and other events for this release will be recorded here."
        />
      </Card>
    );
  }

  return (
    <Table.ScrollContainer minWidth={520}>
      <Table verticalSpacing="sm" highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>When</Table.Th>
            <Table.Th>Step</Table.Th>
            <Table.Th>Change</Table.Th>
            <Table.Th>By</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {entries.map((e) => (
            <Table.Tr key={e.id}>
              <Table.Td>
                <Text size="sm">{new Date(e.created_at).toLocaleString()}</Text>
              </Table.Td>
              <Table.Td>
                <Badge variant="light" color="gray">{ACTION_LABEL[e.action] ?? e.action}</Badge>
              </Table.Td>
              <Table.Td><Text size="sm">{describeChange(e)}</Text></Table.Td>
              <Table.Td><Text size="sm">{e.operator || "—"}</Text></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

// --- Page ------------------------------------------------------------------
export function ProductDetailPage() {
  const { productId } = useParams();
  const [searchParams] = useSearchParams();
  const id = Number(productId);
  const { data: product } = useQuery({ queryKey: ["product", id], queryFn: () => getProduct(id) });
  const { data: releases = [], isLoading } = useQuery({
    queryKey: ["releases", id],
    queryFn: () => listReleases(id),
  });

  const byKind = useMemo(
    () => ({
      stable: pickStable(releases),
      approval: pickApproval(releases),
      draft: pickDraft(releases),
    }),
    [releases]
  );

  // Default the active release to: requested kind → last stable → under
  // approval → draft → newest. The selector can override afterwards.
  const [selected, setSelected] = useState<number | null>(null);
  const defaultId = useMemo(() => {
    const kind = searchParams.get("kind") as ReleaseKind | null;
    const preferred = kind ? byKind[kind] : null;
    return (
      preferred?.id ??
      byKind.stable?.id ??
      byKind.approval?.id ??
      byKind.draft?.id ??
      releases[0]?.id ??
      null
    );
  }, [searchParams, byKind, releases]);
  const activeId = selected ?? defaultId;
  const activeRelease = releases.find((r) => r.id === activeId) ?? null;

  if (isLoading) {
    return (
      <Stack gap="lg">
        <Skeleton h={48} w={280} radius="md" />
        <Skeleton h={72} radius="md" />
        <Skeleton h={320} radius="md" />
      </Stack>
    );
  }

  const needsRelease = (verb: string) => (
    <Card>
      <EmptyState
        icon={IconRocket}
        title="No release selected"
        description={`Create a release first to ${verb}.`}
      />
    </Card>
  );

  return (
    <Stack gap="lg">
      <div>
        <Anchor component={Link} to="/dashboard" size="sm">← Dashboard</Anchor>
        <Group gap="sm" mt={4} align="center">
          <Title order={2}>{product?.name ?? `Product #${id}`}</Title>
          {byKind.stable && (
            <Badge color="teal" variant="filled" size="lg">
              stable v{byKind.stable.version}
            </Badge>
          )}
        </Group>
        <Text c="dimmed">{releases.length} release{releases.length === 1 ? "" : "s"}</Text>
      </div>

      {activeRelease && (
        <Card withBorder radius="md" padding="md">
          <ReleaseSelector
            releases={releases}
            byKind={byKind}
            value={activeId}
            onChange={setSelected}
          />
        </Card>
      )}

      <Tabs defaultValue="overview" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="overview" leftSection={<IconClipboardText size={16} />}>Overview</Tabs.Tab>
          <Tabs.Tab value="releases" leftSection={<IconRocket size={16} />}>Releases</Tabs.Tab>
          <Tabs.Tab value="checks" leftSection={<IconChecklist size={16} />}>Checks</Tabs.Tab>
          <Tabs.Tab value="documentation" leftSection={<IconFile size={16} />}>Documentation</Tabs.Tab>
          <Tabs.Tab value="issues" leftSection={<IconListDetails size={16} />}>Issues</Tabs.Tab>
          <Tabs.Tab value="history" leftSection={<IconHistory size={16} />}>History</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="overview" pt="md">
          {activeRelease ? (
            <ReleaseStatusCard release={activeRelease} />
          ) : needsRelease("see its status")}
        </Tabs.Panel>

        <Tabs.Panel value="releases" pt="md">
          <ReleasesTab productId={id} releases={releases} />
        </Tabs.Panel>

        <Tabs.Panel value="checks" pt="md">
          {activeId ? <ChecksTab releaseId={activeId} /> : needsRelease("manage checks")}
        </Tabs.Panel>

        <Tabs.Panel value="documentation" pt="md">
          {activeId ? <DocumentationTab releaseId={activeId} /> : needsRelease("attach documentation")}
        </Tabs.Panel>

        <Tabs.Panel value="issues" pt="md">
          {activeId && product ? (
            <JiraTab
              releaseId={activeId}
              product={product}
              version={activeRelease?.version ?? ""}
            />
          ) : (
            needsRelease("sync tracker issues")
          )}
        </Tabs.Panel>

        <Tabs.Panel value="history" pt="md">
          {activeId ? <HistoryTab releaseId={activeId} /> : needsRelease("see its history")}
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
