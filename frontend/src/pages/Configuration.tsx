import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Collapse,
  Group,
  Loader,
  Modal,
  MultiSelect,
  NumberInput,
  PasswordInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconArrowDown,
  IconArrowUp,
  IconChevronDown,
  IconChevronRight,
  IconDownload,
  IconPencil,
  IconPlus,
  IconTrash,
  IconVersions,
} from "@tabler/icons-react";
import {
  getAssistantCapabilities,
  getConfig,
  updateConfig,
  getWorkflow,
  updateWorkflow,
  exportWorkflowYaml,
  listDocumentTypes,
  addDocumentType,
  deleteDocumentType,
  DocumentType,
  getOverview,
  updateProduct,
  deleteProduct,
  listReleases,
  deleteRelease,
  ConfigUpdate,
  ProductOverview,
  Release,
  WorkflowStateInput,
  Workflow,
  GUARDS,
  ROLES,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { notifyApiError } from "../lib/errors";

// --- Workflow: full graph editor (states + transitions) + YAML export -------
// The starting state and the terminal outcomes are structural: they cannot be
// deleted from the graph (the backend always expects them to exist).
const INITIAL_STATE = "Draft";
const PROTECTED_STATES = new Set([INITIAL_STATE, "Rejected", "Approved"]);

const toEditable = (wf: Workflow): WorkflowStateInput[] =>
  [...wf.states]
    .sort((a, b) => a.score - b.score)
    .map((s) => ({
      name: s.name,
      transitions: s.transitions.map((t) => ({
        name: t.name,
        target: t.target,
        roles: [...t.roles],
        requires: [...t.requires],
      })),
    }));

// Returns a human-readable error if the edited graph is invalid, else null.
// Mirrors the backend validation so the admin gets feedback before saving.
function validateGraph(states: WorkflowStateInput[]): string | null {
  if (states.length === 0) return "Add at least one state.";
  const names = states.map((s) => s.name.trim());
  if (names.some((n) => !n)) return "Every state needs a name.";
  if (new Set(names).size !== names.length) return "State names must be unique.";
  for (const required of PROTECTED_STATES) {
    if (!names.includes(required)) return `The “${required}” state is required and cannot be removed.`;
  }
  const known = new Set(names);
  for (const s of states) {
    const seen = new Set<string>();
    for (const t of s.transitions) {
      const tn = t.name.trim();
      if (!tn) return `A transition in “${s.name}” has no name.`;
      if (seen.has(tn)) return `“${s.name}” has a duplicate transition “${tn}”.`;
      seen.add(tn);
      if (!known.has(t.target)) return `Transition “${tn}” targets an unknown state.`;
    }
  }
  return null;
}

function downloadYaml(text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/x-yaml" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "states.yaml";
  a.click();
  URL.revokeObjectURL(url);
}

function WorkflowSection({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const { data: workflow, isLoading } = useQuery({ queryKey: ["workflow"], queryFn: getWorkflow });
  // Document types feed the parameterised `document:<type>` readiness guards.
  const { data: docTypes = [] } = useQuery({ queryKey: ["document-types"], queryFn: listDocumentTypes });
  // Guard options for the readiness MultiSelect: the fixed guards plus one
  // `document:<type>` entry per configured document type.
  const guardData = useMemo(() => {
    const groups: { group: string; items: { value: string; label: string }[] }[] = [
      { group: "General", items: GUARDS.map((g) => ({ value: g, label: g })) },
    ];
    if (docTypes.length) {
      groups.push({
        group: "Required document",
        items: docTypes.map((t) => ({ value: `document:${t.name}`, label: `Document: ${t.name}` })),
      });
    }
    return groups;
  }, [docTypes]);

  // The editable graph, seeded from the server and mutated locally until saved.
  const [states, setStates] = useState<WorkflowStateInput[]>([]);
  // Indices of state cards whose transitions are collapsed (default: expanded).
  // Kept in sync with `states` as cards are reordered/removed below.
  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  useEffect(() => {
    if (!workflow) return;
    const editable = toEditable(workflow);
    setStates(editable);
    // Cards start collapsed; the admin expands the ones they want to edit.
    setCollapsed(new Set(editable.map((_, i) => i)));
  }, [workflow]);

  const toggleCollapsed = (i: number) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(i) ? next.delete(i) : next.add(i);
      return next;
    });

  // Immutable update of one state by index.
  const patchState = (i: number, fn: (s: WorkflowStateInput) => WorkflowStateInput) =>
    setStates((prev) => prev.map((s, idx) => (idx === i ? fn(s) : s)));
  const patchTransition = (
    si: number,
    ti: number,
    patch: Partial<WorkflowStateInput["transitions"][number]>,
  ) =>
    patchState(si, (s) => ({
      ...s,
      transitions: s.transitions.map((t, idx) => (idx === ti ? { ...t, ...patch } : t)),
    }));

  const moveState = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= states.length) return;
    setStates((prev) => {
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });
    // Keep the collapsed flags attached to their cards as they swap places.
    setCollapsed((prev) => {
      const next = new Set(prev);
      const hi = prev.has(i);
      const hj = prev.has(j);
      next.delete(i);
      next.delete(j);
      if (hj) next.add(i);
      if (hi) next.add(j);
      return next;
    });
  };

  // Remove a state and shift the collapsed flags of the cards after it.
  const removeState = (si: number) => {
    setStates((prev) => prev.filter((_, idx) => idx !== si));
    setCollapsed((prev) => {
      const next = new Set<number>();
      prev.forEach((idx) => {
        if (idx < si) next.add(idx);
        else if (idx > si) next.add(idx - 1);
      });
      return next;
    });
  };

  const save = useMutation({
    mutationFn: () => updateWorkflow(states),
    onSuccess: (wf) => {
      qc.setQueryData(["workflow"], wf);
      notifications.show({ message: "Workflow saved", color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Could not save workflow"),
  });

  const exportYaml = useMutation({
    mutationFn: exportWorkflowYaml,
    onSuccess: downloadYaml,
    onError: (e: any) => notifyApiError(e, "Export failed"),
  });

  if (isLoading || !workflow) return <Loader />;

  const error = validateGraph(states);
  const stateOptions = states.map((s) => s.name).filter(Boolean);

  return (
    <Card withBorder radius="md" padding="lg">
      <Group justify="space-between" mb={4}>
        <Title order={4}>Release workflow</Title>
        <Group gap="xs">
          <Button
            size="compact-sm"
            variant="default"
            leftSection={<IconDownload size={14} />}
            loading={exportYaml.isPending}
            onClick={() => exportYaml.mutate()}
          >
            Export YAML
          </Button>
          {canEdit && (
            <Button
              size="compact-sm"
              loading={save.isPending}
              disabled={!!error}
              onClick={() => save.mutate()}
            >
              Save workflow
            </Button>
          )}
        </Group>
      </Group>
      <Text c="dimmed" size="sm" mb="md">
        Database-backed state graph. <b>{INITIAL_STATE}</b> is the starting state and
        a state with no transitions is final; <b>{INITIAL_STATE}</b>, <b>Rejected</b> and{" "}
        <b>Approved</b> are structural and cannot be removed.{" "}
        {canEdit
          ? "Edit states, transitions, roles and readiness guards below."
          : "Administrators can edit the workflow."} Use <b>Export YAML</b> to download a{" "}
        <code>states.yaml</code>-compatible definition.
      </Text>

      {canEdit && error && (
        <Alert color="orange" variant="light" mb="md">{error}</Alert>
      )}

      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
        {states.map((s, si) => (
          <Card
            key={si}
            withBorder
            radius="md"
            padding="sm"
            bg={s.name === INITIAL_STATE ? "var(--mantine-color-blue-0)" : "var(--mantine-color-gray-0)"}
            style={
              s.name === INITIAL_STATE
                ? { borderColor: "var(--mantine-color-blue-4)" }
                : undefined
            }
          >
            <Group justify="space-between" wrap="nowrap" mb="xs">
              <ActionIcon
                variant="subtle"
                color="gray"
                size="sm"
                aria-label={collapsed.has(si) ? "Expand state" : "Collapse state"}
                onClick={() => toggleCollapsed(si)}
              >
                {collapsed.has(si) ? <IconChevronRight size={16} /> : <IconChevronDown size={16} />}
              </ActionIcon>
              <TextInput
                value={s.name}
                onChange={(e) => patchState(si, (st) => ({ ...st, name: e.currentTarget.value }))}
                disabled={!canEdit}
                size="xs"
                placeholder="State name"
                style={{ flex: 1 }}
                rightSection={
                  s.name === INITIAL_STATE ? (
                    <Badge size="xs" color="blue" variant="filled">start</Badge>
                  ) : s.transitions.length === 0 ? (
                    <Badge size="xs" color="gray" variant="light">final</Badge>
                  ) : null
                }
                rightSectionWidth={60}
              />
              {canEdit && (
                <Group gap={2} wrap="nowrap">
                  <ActionIcon variant="subtle" color="gray" size="sm" aria-label="Move up"
                    disabled={si === 0} onClick={() => moveState(si, -1)}>
                    <IconArrowUp size={15} />
                  </ActionIcon>
                  <ActionIcon variant="subtle" color="gray" size="sm" aria-label="Move down"
                    disabled={si === states.length - 1} onClick={() => moveState(si, 1)}>
                    <IconArrowDown size={15} />
                  </ActionIcon>
                  <ActionIcon variant="subtle" color="red" size="sm" aria-label="Delete state"
                    disabled={PROTECTED_STATES.has(s.name)}
                    title={PROTECTED_STATES.has(s.name) ? "This state cannot be removed" : undefined}
                    onClick={() => removeState(si)}>
                    <IconTrash size={15} />
                  </ActionIcon>
                </Group>
              )}
            </Group>

            {collapsed.has(si) && (
              s.transitions.length === 0 ? (
                <Text size="xs" c="dimmed">No outgoing transitions (final state).</Text>
              ) : (
                <Group gap={6} wrap="wrap">
                  {s.transitions.map((t, ti) => (
                    <Badge
                      key={ti}
                      variant="light"
                      color="gray"
                      size="sm"
                      style={{ textTransform: "none" }}
                    >
                      {(t.name || "(unnamed)") + " → " + (t.target || "?")}
                    </Badge>
                  ))}
                </Group>
              )
            )}

            <Collapse in={!collapsed.has(si)}>
            <Stack gap="sm">
              {s.transitions.length === 0 ? (
                <Text size="xs" c="dimmed">No outgoing transitions (final state).</Text>
              ) : (
                s.transitions.map((t, ti) => (
                  <Card key={ti} withBorder radius="sm" padding="xs">
                    <Group gap={6} wrap="nowrap" mb={6}>
                      <TextInput
                        value={t.name}
                        onChange={(e) => patchTransition(si, ti, { name: e.currentTarget.value })}
                        disabled={!canEdit}
                        size="xs"
                        placeholder="Action"
                        style={{ flex: 1 }}
                      />
                      <Text size="xs" c="dimmed">→</Text>
                      <Select
                        data={stateOptions}
                        value={t.target || null}
                        onChange={(v) => patchTransition(si, ti, { target: v ?? "" })}
                        disabled={!canEdit}
                        size="xs"
                        placeholder="Target"
                        comboboxProps={{ withinPortal: true }}
                        style={{ flex: 1 }}
                        error={t.target && !stateOptions.includes(t.target) ? true : undefined}
                      />
                      {canEdit && (
                        <ActionIcon variant="subtle" color="red" size="sm" aria-label="Delete transition"
                          onClick={() => patchState(si, (st) => ({
                            ...st,
                            transitions: st.transitions.filter((_, idx) => idx !== ti),
                          }))}>
                          <IconTrash size={15} />
                        </ActionIcon>
                      )}
                    </Group>
                    <MultiSelect
                      data={ROLES}
                      value={t.roles}
                      onChange={(v) => patchTransition(si, ti, { roles: v })}
                      disabled={!canEdit}
                      size="xs"
                      label="Allowed roles"
                      placeholder="Defaults if empty"
                      comboboxProps={{ withinPortal: true }}
                      mb={6}
                    />
                    <MultiSelect
                      data={guardData}
                      value={t.requires}
                      onChange={(v) => patchTransition(si, ti, { requires: v })}
                      disabled={!canEdit}
                      size="xs"
                      label="Readiness guards"
                      placeholder="None"
                      comboboxProps={{ withinPortal: true }}
                    />
                  </Card>
                ))
              )}
              {canEdit && (
                <Button
                  size="compact-xs"
                  variant="light"
                  leftSection={<IconPlus size={13} />}
                  onClick={() => patchState(si, (st) => ({
                    ...st,
                    transitions: [...st.transitions, { name: "", target: "", roles: [], requires: [] }],
                  }))}
                >
                  Add transition
                </Button>
              )}
            </Stack>
            </Collapse>
          </Card>
        ))}
      </SimpleGrid>

      {canEdit && (
        <Button
          mt="md"
          variant="light"
          leftSection={<IconPlus size={15} />}
          onClick={() => setStates((prev) => [...prev, { name: "", transitions: [] }])}
        >
          Add state
        </Button>
      )}
    </Card>
  );
}

// --- Issue tracker configuration -------------------------------------------
function TrackerSection({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const { data: cfg, isLoading } = useQuery({ queryKey: ["config"], queryFn: getConfig });

  const [provider, setProvider] = useState<"jira" | "github">("jira");
  const [syncMinutes, setSyncMinutes] = useState<number>(10);
  const [jiraEnabled, setJiraEnabled] = useState(false);
  const [jiraUrl, setJiraUrl] = useState("");
  const [jiraToken, setJiraToken] = useState("");
  const [ghEnabled, setGhEnabled] = useState(false);
  const [ghUrl, setGhUrl] = useState("");
  const [ghToken, setGhToken] = useState("");

  // Seed local form state once the current config loads.
  useEffect(() => {
    if (!cfg) return;
    setProvider(cfg.tracker_provider);
    setSyncMinutes(cfg.sync_interval_minutes);
    setJiraEnabled(cfg.jira.enabled);
    setJiraUrl(cfg.jira.base_url);
    setGhEnabled(cfg.github.enabled);
    setGhUrl(cfg.github.base_url);
  }, [cfg]);

  const save = useMutation({
    mutationFn: () => {
      const body: ConfigUpdate = {
        tracker_provider: provider,
        sync_interval_minutes: syncMinutes,
        jira_enabled: jiraEnabled,
        jira_base_url: jiraUrl,
        github_enabled: ghEnabled,
        github_base_url: ghUrl,
      };
      if (jiraToken) body.jira_token = jiraToken; // write-only: blank = keep existing
      if (ghToken) body.github_token = ghToken;
      return updateConfig(body);
    },
    onSuccess: (data) => {
      qc.setQueryData(["config"], data);
      setJiraToken("");
      setGhToken("");
      notifications.show({ message: "Configuration saved", color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Save failed"),
  });

  if (isLoading || !cfg) return <Loader />;

  return (
    <Card withBorder radius="md" padding="lg">
      <Group justify="space-between" mb="md">
        <div>
          <Title order={4}>Issue tracker</Title>
          <Text c="dimmed" size="sm">Configure tracker access. Only one tracker can be enabled at a time.</Text>
        </div>
        <Badge size="lg" variant="light" color={provider === "github" ? "dark" : "blue"}>
          active: {provider}
        </Badge>
      </Group>

      {!canEdit && (
        <Alert color="gray" variant="light" mb="md">
          You need the Administrator role to change these settings.
        </Alert>
      )}

      <Text size="sm" fw={600} mb={4}>Active tracker</Text>
      <SegmentedControl
        data={[{ value: "jira", label: "Jira" }, { value: "github", label: "GitHub" }]}
        value={provider}
        onChange={(v) => setProvider(v as "jira" | "github")}
        disabled={!canEdit}
        mb="lg"
      />

      <NumberInput
        label="Scheduled sync (minutes)"
        description="Every running release's issues are re-synced from the tracker on this schedule. Set 0 to disable. Default: every 10 minutes."
        min={0}
        step={1}
        allowDecimal={false}
        value={syncMinutes}
        onChange={(v) => setSyncMinutes(typeof v === "number" ? v : 10)}
        disabled={!canEdit}
        maw={280}
        mb="lg"
      />

      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={600}>Jira</Text>
            <Switch
              checked={jiraEnabled}
              onChange={(e) => {
                const on = e.currentTarget.checked;
                setJiraEnabled(on);
                if (on) { setGhEnabled(false); setProvider("jira"); } // only one tracker at a time
              }}
              label="Enabled"
              disabled={!canEdit}
            />
          </Group>
          <TextInput
            label="Base URL"
            placeholder="https://your-org.atlassian.net"
            value={jiraUrl}
            onChange={(e) => setJiraUrl(e.currentTarget.value)}
            disabled={!canEdit}
          />
          <PasswordInput
            label="API token"
            placeholder={cfg.jira.token_set ? "•••••••• (stored)" : "not set"}
            value={jiraToken}
            onChange={(e) => setJiraToken(e.currentTarget.value)}
            disabled={!canEdit}
            description="Leave blank to keep the current token."
          />
        </Stack>

        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={600}>GitHub</Text>
            <Switch
              checked={ghEnabled}
              onChange={(e) => {
                const on = e.currentTarget.checked;
                setGhEnabled(on);
                if (on) { setJiraEnabled(false); setProvider("github"); } // only one tracker at a time
              }}
              label="Enabled"
              disabled={!canEdit}
            />
          </Group>
          <TextInput
            label="API base URL"
            placeholder="https://api.github.com"
            value={ghUrl}
            onChange={(e) => setGhUrl(e.currentTarget.value)}
            disabled={!canEdit}
          />
          <Text size="xs" c="dimmed">
            The repository is configured per product, on each product's Issues tab.
          </Text>
          <PasswordInput
            label="Access token"
            placeholder={cfg.github.token_set ? "•••••••• (stored)" : "not set"}
            value={ghToken}
            onChange={(e) => setGhToken(e.currentTarget.value)}
            disabled={!canEdit}
            description="Leave blank to keep the current token."
          />
        </Stack>
      </SimpleGrid>

      {canEdit && (
        <Group justify="flex-end" mt="lg">
          <Button loading={save.isPending} onClick={() => save.mutate()}>Save configuration</Button>
        </Group>
      )}
    </Card>
  );
}

// --- Document types: admin-managed supported document types ----------------
function DocumentTypesSection({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const key = ["document-types"];
  const { data: types = [], isLoading } = useQuery({ queryKey: key, queryFn: listDocumentTypes });
  const [name, setName] = useState("");
  const invalidate = () => qc.invalidateQueries({ queryKey: key });

  const add = useMutation({
    mutationFn: () => addDocumentType(name.trim()),
    onSuccess: () => { setName(""); invalidate(); notifications.show({ message: "Document type added", color: "teal" }); },
    onError: (e: any) => notifyApiError(e, "Could not add document type"),
  });
  const remove = useMutation({
    mutationFn: (id: number) => deleteDocumentType(id),
    onSuccess: (_d, id) => {
      // Drop the deleted type from the cache immediately so the list updates
      // without waiting on a refetch (and the badge can't be clicked twice),
      // then reconcile with the server.
      qc.setQueryData<DocumentType[]>(key, (old) => old?.filter((t) => t.id !== id));
      invalidate();
    },
    onError: (e: any) => notifyApiError(e, "Could not delete document type"),
  });

  return (
    <Card withBorder radius="md" padding="lg">
      <Title order={4} mb={4}>Document types</Title>
      <Text c="dimmed" size="sm" mb="md">
        The supported types operators can mark uploaded documents with. Removing a
        type leaves already-classified documents untouched.
      </Text>

      {isLoading ? (
        <Loader />
      ) : types.length === 0 ? (
        <Text c="dimmed" size="sm" mb="md">No document types configured.</Text>
      ) : (
        <Group gap="xs" mb="md" wrap="wrap">
          {types.map((t) => (
            <Badge
              key={t.id}
              size="lg"
              variant="light"
              color="grape"
              pr={canEdit ? 3 : undefined}
              rightSection={
                canEdit ? (
                  <ActionIcon
                    size="xs"
                    color="grape"
                    variant="transparent"
                    aria-label={`Delete ${t.name}`}
                    loading={remove.isPending && remove.variables === t.id}
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(t.id)}
                  >
                    <IconTrash size={12} />
                  </ActionIcon>
                ) : undefined
              }
            >
              {t.name}
            </Badge>
          ))}
        </Group>
      )}

      {canEdit && (
        <Group align="flex-end" gap="sm">
          <TextInput
            label="New type"
            placeholder="e.g. Security Review"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && name.trim()) add.mutate(); }}
            style={{ flex: 1 }}
          />
          <Button disabled={!name.trim()} loading={add.isPending} onClick={() => add.mutate()}>
            Add type
          </Button>
        </Group>
      )}
    </Card>
  );
}

// --- Assistant actions: what the LLM assistant is capable of ----------------
// Read-only: the list is described by the backend from the assistant's live
// tool registry, so it can never drift from what the model can actually do.
function AssistantActionsSection() {
  const { data, isLoading } = useQuery({
    queryKey: ["assistant-capabilities"],
    queryFn: getAssistantCapabilities,
  });

  return (
    <Card withBorder radius="md" padding="lg">
      <Title order={4} mb={4}>Assistant actions</Title>
      <Text c="dimmed" size="sm" mb="md">
        Everything the LLM assistant can do on an operator's behalf. Every action
        goes through the same role and readiness checks as the UI, and each one the
        assistant performs is reported back in the chat.
      </Text>

      {isLoading || !data ? (
        <Loader />
      ) : (
        <Table.ScrollContainer minWidth={520}>
          <Table verticalSpacing="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Action</Table.Th>
                <Table.Th w={90}>Type</Table.Th>
                <Table.Th>What it does</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {data.actions.map((a) => (
                <Table.Tr key={a.name}>
                  <Table.Td fw={600} style={{ whiteSpace: "nowrap" }}>
                    <code>{a.name}</code>
                  </Table.Td>
                  <Table.Td>
                    <Badge size="sm" variant="light" color={a.kind === "action" ? "orange" : "blue"}>
                      {a.kind === "action" ? "action" : "read"}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm">{a.description}</Text>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Card>
  );
}

// --- Projects: per-project settings + lifecycle ----------------------------
function EditProjectModal({
  project,
  onClose,
}: {
  project: ProductOverview | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [repo, setRepo] = useState("");
  useEffect(() => {
    if (project) {
      setName(project.name);
      setRepo(project.tracker_repo);
    }
  }, [project]);

  const save = useMutation({
    mutationFn: () =>
      updateProduct(project!.id, { name: name.trim(), tracker_repo: repo.trim() }),
    onSuccess: (p) => {
      qc.setQueryData(["product", p.id], p);
      qc.invalidateQueries({ queryKey: ["overview"] });
      notifications.show({ message: "Project updated", color: "teal" });
      onClose();
    },
    onError: (e: any) => notifyApiError(e, "Could not update project"),
  });

  return (
    <Modal opened={!!project} onClose={onClose} title="Edit project" size="md">
      <Stack gap="md">
        <TextInput
          label="Project name"
          data-autofocus
          value={name}
          onChange={(e) => setName(e.currentTarget.value)}
        />
        <TextInput
          label="Issue tracker project"
          description="GitHub owner/repo (or tracker project key) this project's issues live in"
          placeholder="owner/repo"
          value={repo}
          onChange={(e) => setRepo(e.currentTarget.value)}
        />
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button disabled={!name.trim()} loading={save.isPending} onClick={() => save.mutate()}>
            Save changes
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function DeleteProjectModal({
  project,
  onClose,
}: {
  project: ProductOverview | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const del = useMutation({
    mutationFn: () => deleteProduct(project!.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["overview"] });
      notifications.show({ message: "Project deleted", color: "teal" });
      onClose();
    },
    onError: (e: any) => notifyApiError(e, "Could not delete project"),
  });

  return (
    <Modal opened={!!project} onClose={onClose} title="Delete project" size="md">
      <Stack gap="md">
        <Alert color="red" variant="light">
          This permanently deletes <b>{project?.name}</b> and its{" "}
          {project?.release_count ?? 0} release(s), including all checks, documents
          and synced issues. This cannot be undone.
        </Alert>
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button color="red" loading={del.isPending} onClick={() => del.mutate()}>
            Delete project
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

// Lists a project's releases and lets a Release Manager / Administrator delete
// any of them (with a per-row confirmation). Deleting a release removes all its
// checks, documents and synced issues.
function ManageReleasesModal({
  project,
  onClose,
}: {
  project: ProductOverview | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [confirmId, setConfirmId] = useState<number | null>(null);
  const { data: releases = [], isLoading } = useQuery({
    queryKey: ["product-releases", project?.id],
    queryFn: () => listReleases(project!.id),
    enabled: !!project,
  });

  const del = useMutation({
    mutationFn: (id: number) => deleteRelease(id),
    onSuccess: (_d, id) => {
      setConfirmId((cur) => (cur === id ? null : cur));
      qc.invalidateQueries({ queryKey: ["product-releases", project?.id] });
      qc.invalidateQueries({ queryKey: ["overview"] });
      qc.invalidateQueries({ queryKey: ["product", project?.id] });
      notifications.show({ message: "Release deleted", color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Could not delete release"),
  });

  return (
    <Modal
      opened={!!project}
      onClose={onClose}
      title={`Releases — ${project?.name ?? ""}`}
      size="lg"
    >
      {isLoading ? (
        <Loader />
      ) : releases.length === 0 ? (
        <Text c="dimmed" size="sm">This project has no releases.</Text>
      ) : (
        <Table verticalSpacing="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Version</Table.Th>
              <Table.Th>State</Table.Th>
              <Table.Th w={180} />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {releases.map((r: Release) => (
              <Table.Tr key={r.id}>
                <Table.Td fw={600}>{r.version}</Table.Td>
                <Table.Td>
                  <Badge variant="light" color="gray">{r.state}</Badge>
                </Table.Td>
                <Table.Td>
                  {confirmId === r.id ? (
                    <Group gap={6} wrap="nowrap" justify="flex-end">
                      <Text size="xs" c="red">Delete?</Text>
                      <Button size="compact-xs" color="red"
                        loading={del.isPending && del.variables === r.id}
                        onClick={() => del.mutate(r.id)}>
                        Confirm
                      </Button>
                      <Button size="compact-xs" variant="default"
                        onClick={() => setConfirmId(null)}>
                        Cancel
                      </Button>
                    </Group>
                  ) : (
                    <Group justify="flex-end">
                      <ActionIcon variant="subtle" color="red" aria-label="Delete release"
                        onClick={() => setConfirmId(r.id)}>
                        <IconTrash size={16} />
                      </ActionIcon>
                    </Group>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Modal>
  );
}

function ProjectsSection({ canEdit, canDelete }: { canEdit: boolean; canDelete: boolean }) {
  const { data: projects = [], isLoading } = useQuery({
    queryKey: ["overview"],
    queryFn: getOverview,
  });
  const [editing, setEditing] = useState<ProductOverview | null>(null);
  const [deleting, setDeleting] = useState<ProductOverview | null>(null);
  const [managing, setManaging] = useState<ProductOverview | null>(null);

  return (
    <Card withBorder radius="md" padding="lg">
      <Title order={4} mb={4}>Projects</Title>
      <Text c="dimmed" size="sm" mb="md">
        Manage each project's standard configuration — its name and the issue-tracker
        project its issues are synced from — or remove a project. {canEdit
          ? "Use the releases icon (or click a project's release count) to manage and delete its releases."
          : ""}
      </Text>

      {isLoading ? (
        <Loader />
      ) : projects.length === 0 ? (
        <Text c="dimmed" size="sm">No projects yet.</Text>
      ) : (
        <Table.ScrollContainer minWidth={520}>
          <Table verticalSpacing="sm" highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Project</Table.Th>
                <Table.Th>Issue tracker project</Table.Th>
                <Table.Th w={90}>Releases</Table.Th>
                {(canEdit || canDelete) && <Table.Th w={90} />}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {projects.map((p) => (
                <Table.Tr key={p.id}>
                  <Table.Td fw={600}>
                    <Anchor component={Link} to={`/products/${p.id}`}>{p.name}</Anchor>
                  </Table.Td>
                  <Table.Td>
                    {p.tracker_repo ? (
                      <Badge variant="light" color="gray" style={{ textTransform: "none" }}>
                        {p.tracker_repo}
                      </Badge>
                    ) : (
                      <Text size="sm" c="dimmed">— not set —</Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    {canEdit && p.release_count > 0 ? (
                      <Anchor component="button" type="button" onClick={() => setManaging(p)}>
                        {p.release_count}
                      </Anchor>
                    ) : (
                      p.release_count
                    )}
                  </Table.Td>
                  {(canEdit || canDelete) && (
                    <Table.Td>
                      <Group gap={4} wrap="nowrap">
                        {canEdit && (
                          <Tooltip
                            label={p.release_count > 0 ? "Manage / delete releases" : "No releases yet"}
                            withArrow
                          >
                            <ActionIcon variant="subtle" color="gray" aria-label="Manage releases"
                              disabled={p.release_count === 0}
                              onClick={() => setManaging(p)}>
                              <IconVersions size={16} />
                            </ActionIcon>
                          </Tooltip>
                        )}
                        {canEdit && (
                          <Tooltip label="Edit project" withArrow>
                            <ActionIcon variant="subtle" color="gray" aria-label="Edit project"
                              onClick={() => setEditing(p)}>
                              <IconPencil size={16} />
                            </ActionIcon>
                          </Tooltip>
                        )}
                        {canDelete && (
                          <Tooltip label="Delete project" withArrow>
                            <ActionIcon variant="subtle" color="red" aria-label="Delete project"
                              onClick={() => setDeleting(p)}>
                              <IconTrash size={16} />
                            </ActionIcon>
                          </Tooltip>
                        )}
                      </Group>
                    </Table.Td>
                  )}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      <EditProjectModal project={editing} onClose={() => setEditing(null)} />
      <DeleteProjectModal project={deleting} onClose={() => setDeleting(null)} />
      <ManageReleasesModal project={managing} onClose={() => setManaging(null)} />
    </Card>
  );
}

// The Configuration sub-pages, in nav order. Each renders on its own dedicated
// route at /configuration/<path>. Default checks come last; the LLM engine is
// also one of these sub-pages (its component lives in ./Llm).
export const CONFIG_SECTIONS = [
  { path: "projects", label: "Projects" },
  { path: "users", label: "Users" },
  { path: "document-types", label: "Document types" },
  { path: "workflow", label: "Release workflow" },
  { path: "tracker", label: "Issue tracker" },
  { path: "assistant-actions", label: "Assistant actions" },
  { path: "llm", label: "LLM engine" },
];

// Shared page frame for every Configuration sub-page: an order-2 heading and
// description above the section card.
function ConfigPage({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>{title}</Title>
        <Text c="dimmed">{description}</Text>
      </div>
      {children}
    </Stack>
  );
}

export function ProjectsPage() {
  const { hasRole } = useAuth();
  return (
    <ConfigPage title="Projects" description="Manage each project's standard configuration and lifecycle.">
      <ProjectsSection
        canEdit={hasRole("Administrator", "Release Manager")}
        canDelete={hasRole("Administrator")}
      />
    </ConfigPage>
  );
}

export function DocumentTypesPage() {
  const { hasRole } = useAuth();
  return (
    <ConfigPage title="Document types" description="The supported types operators can classify uploaded documents with.">
      <DocumentTypesSection canEdit={hasRole("Administrator", "Release Manager")} />
    </ConfigPage>
  );
}

export function WorkflowPage() {
  const { hasRole } = useAuth();
  return (
    <ConfigPage title="Release workflow" description="The database-backed state graph releases move through.">
      <WorkflowSection canEdit={hasRole("Administrator")} />
    </ConfigPage>
  );
}

export function TrackerPage() {
  const { hasRole } = useAuth();
  return (
    <ConfigPage title="Issue tracker" description="Configure tracker access for syncing issues.">
      <TrackerSection canEdit={hasRole("Administrator")} />
    </ConfigPage>
  );
}

export function AssistantActionsPage() {
  return (
    <ConfigPage
      title="Assistant actions"
      description="What the LLM assistant is capable of doing on an operator's behalf."
    >
      <AssistantActionsSection />
    </ConfigPage>
  );
}
