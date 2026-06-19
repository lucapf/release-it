import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  MultiSelect,
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
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconArrowDown,
  IconArrowUp,
  IconDownload,
  IconPencil,
  IconPlus,
  IconTrash,
} from "@tabler/icons-react";
import {
  getConfig,
  updateConfig,
  getWorkflow,
  updateWorkflow,
  exportWorkflowYaml,
  listCheckTemplates,
  addCheckTemplate,
  deleteCheckTemplate,
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
  Phase,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { notifyApiError } from "../lib/errors";

// --- Workflow: full graph editor (states + transitions) + YAML export -------
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

  // The editable graph, seeded from the server and mutated locally until saved.
  const [states, setStates] = useState<WorkflowStateInput[]>([]);
  useEffect(() => {
    if (workflow) setStates(toEditable(workflow));
  }, [workflow]);

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

  const moveState = (i: number, dir: -1 | 1) =>
    setStates((prev) => {
      const j = i + dir;
      if (j < 0 || j >= prev.length) return prev;
      const next = [...prev];
      [next[i], next[j]] = [next[j], next[i]];
      return next;
    });

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
        Database-backed state graph. The first state is the initial one
        (<b>{states[0]?.name || "—"}</b>); a state with no transitions is final.{" "}
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
          <Card key={si} withBorder radius="md" padding="sm" bg="var(--mantine-color-gray-0)">
            <Group justify="space-between" wrap="nowrap" mb="xs">
              <TextInput
                value={s.name}
                onChange={(e) => patchState(si, (st) => ({ ...st, name: e.currentTarget.value }))}
                disabled={!canEdit}
                size="xs"
                placeholder="State name"
                style={{ flex: 1 }}
                rightSection={
                  si === 0 ? (
                    <Badge size="xs" color="blue" variant="light">initial</Badge>
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
                    onClick={() => setStates((prev) => prev.filter((_, idx) => idx !== si))}>
                    <IconTrash size={15} />
                  </ActionIcon>
                </Group>
              )}
            </Group>

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
                      data={GUARDS}
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
    setJiraEnabled(cfg.jira.enabled);
    setJiraUrl(cfg.jira.base_url);
    setGhEnabled(cfg.github.enabled);
    setGhUrl(cfg.github.base_url);
  }, [cfg]);

  const save = useMutation({
    mutationFn: () => {
      const body: ConfigUpdate = {
        tracker_provider: provider,
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

// --- LLM engine configuration ----------------------------------------------
function LLMSection({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const { data: cfg, isLoading } = useQuery({ queryKey: ["config"], queryFn: getConfig });

  const [provider, setProvider] = useState<"claude" | "ollama">("claude");
  const [claudeModel, setClaudeModel] = useState("");
  const [claudeKey, setClaudeKey] = useState("");
  const [ollamaUrl, setOllamaUrl] = useState("");
  const [ollamaModel, setOllamaModel] = useState("");

  useEffect(() => {
    if (!cfg) return;
    setProvider(cfg.llm.provider);
    setClaudeModel(cfg.llm.claude.model);
    setOllamaUrl(cfg.llm.ollama.base_url);
    setOllamaModel(cfg.llm.ollama.model);
  }, [cfg]);

  const save = useMutation({
    mutationFn: () => {
      const body: ConfigUpdate = {
        llm_provider: provider,
        claude_model: claudeModel,
        ollama_base_url: ollamaUrl,
        ollama_model: ollamaModel,
      };
      if (claudeKey) body.claude_api_key = claudeKey; // write-only: blank = keep existing
      return updateConfig(body);
    },
    onSuccess: (data) => {
      qc.setQueryData(["config"], data);
      setClaudeKey("");
      notifications.show({ message: "LLM configuration saved", color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Save failed"),
  });

  if (isLoading || !cfg) return <Loader />;

  return (
    <Card withBorder radius="md" padding="lg">
      <Group justify="space-between" mb="md">
        <div>
          <Title order={4}>LLM engine</Title>
          <Text c="dimmed" size="sm">Used to draft release notes from tracked issues.</Text>
        </div>
        <Badge size="lg" variant="light" color={provider === "ollama" ? "grape" : "indigo"}>
          active: {provider}
        </Badge>
      </Group>

      {!canEdit && (
        <Alert color="gray" variant="light" mb="md">
          You need the Administrator role to change these settings.
        </Alert>
      )}

      <Text size="sm" fw={600} mb={4}>Engine</Text>
      <SegmentedControl
        data={[{ value: "claude", label: "Claude (Anthropic)" }, { value: "ollama", label: "Ollama (local)" }]}
        value={provider}
        onChange={(v) => setProvider(v as "claude" | "ollama")}
        disabled={!canEdit}
        mb="lg"
      />

      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
        <Stack gap="sm">
          <Text fw={600}>Claude</Text>
          <TextInput
            label="Model"
            placeholder="claude-opus-4-8"
            value={claudeModel}
            onChange={(e) => setClaudeModel(e.currentTarget.value)}
            disabled={!canEdit}
          />
          <PasswordInput
            label="API key"
            placeholder={cfg.llm.claude.api_key_set ? "•••••••• (stored)" : "not set"}
            value={claudeKey}
            onChange={(e) => setClaudeKey(e.currentTarget.value)}
            disabled={!canEdit}
            description="Leave blank to keep the current key."
          />
        </Stack>

        <Stack gap="sm">
          <Text fw={600}>Ollama</Text>
          <TextInput
            label="Server URL"
            placeholder="http://localhost:11434"
            value={ollamaUrl}
            onChange={(e) => setOllamaUrl(e.currentTarget.value)}
            disabled={!canEdit}
          />
          <TextInput
            label="Model"
            placeholder="llama3"
            value={ollamaModel}
            onChange={(e) => setOllamaModel(e.currentTarget.value)}
            disabled={!canEdit}
          />
        </Stack>
      </SimpleGrid>

      {canEdit && (
        <Group justify="flex-end" mt="lg">
          <Button loading={save.isPending} onClick={() => save.mutate()}>Save LLM configuration</Button>
        </Group>
      )}
    </Card>
  );
}

// --- Default check templates -----------------------------------------------
function CheckTemplatesSection({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const key = ["check-templates"];
  const { data: templates = [], isLoading } = useQuery({ queryKey: key, queryFn: listCheckTemplates });
  const [label, setLabel] = useState("");
  const [phase, setPhase] = useState<Phase>("pre");
  const invalidate = () => qc.invalidateQueries({ queryKey: key });

  const add = useMutation({
    mutationFn: () => addCheckTemplate(label, phase),
    onSuccess: () => { setLabel(""); invalidate(); notifications.show({ message: "Template added", color: "teal" }); },
    onError: (e: any) => notifyApiError(e, "Could not add check template"),
  });
  const remove = useMutation({
    mutationFn: (id: number) => deleteCheckTemplate(id),
    onSuccess: invalidate,
  });

  return (
    <Card withBorder radius="md" padding="lg">
      <Title order={4} mb={4}>Default checks</Title>
      <Text c="dimmed" size="sm" mb="md">
        These pre/post checks are automatically added to every new release.
      </Text>

      {isLoading ? (
        <Loader />
      ) : templates.length === 0 ? (
        <Text c="dimmed" size="sm" mb="md">No default checks configured.</Text>
      ) : (
        <Table mb="md">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Phase</Table.Th>
              <Table.Th>Check</Table.Th>
              {canEdit && <Table.Th w={48} />}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {templates.map((t) => (
              <Table.Tr key={t.id}>
                <Table.Td>
                  <Badge size="sm" variant="light" color={t.phase === "pre" ? "blue" : "grape"}>
                    {t.phase}
                  </Badge>
                </Table.Td>
                <Table.Td>{t.label}</Table.Td>
                {canEdit && (
                  <Table.Td>
                    <ActionIcon variant="subtle" color="red" onClick={() => remove.mutate(t.id)} aria-label="Delete">
                      <IconTrash size={16} />
                    </ActionIcon>
                  </Table.Td>
                )}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      {canEdit && (
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
            label="Check label"
            placeholder="e.g. Smoke test passed"
            value={label}
            onChange={(e) => setLabel(e.currentTarget.value)}
            style={{ flex: 1 }}
          />
          <Button disabled={!label} loading={add.isPending} onClick={() => add.mutate()}>
            Add check
          </Button>
        </Group>
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
          ? "Click a project's release count to manage and delete its releases."
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
                          <ActionIcon variant="subtle" color="gray" aria-label="Edit project"
                            onClick={() => setEditing(p)}>
                            <IconPencil size={16} />
                          </ActionIcon>
                        )}
                        {canDelete && (
                          <ActionIcon variant="subtle" color="red" aria-label="Delete project"
                            onClick={() => setDeleting(p)}>
                            <IconTrash size={16} />
                          </ActionIcon>
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

const SECTIONS = [
  { id: "projects", label: "Projects" },
  { id: "checks", label: "Default checks" },
  { id: "workflow", label: "Release workflow" },
  { id: "tracker", label: "Issue tracker" },
  { id: "llm", label: "LLM engine" },
];

function scrollToSection(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

// Offsets the scroll target below the fixed app header so the section title
// isn't hidden under it.
const anchorStyle = { scrollMarginTop: 80 };

export function ConfigurationPage() {
  const { hasRole } = useAuth();
  const isAdmin = hasRole("Administrator");
  const canManageChecks = hasRole("Administrator", "Release Manager");

  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>Configuration</Title>
        <Text c="dimmed">Projects, default checks, release workflow, issue tracker and LLM engine.</Text>
      </div>

      <Card withBorder radius="md" padding="sm">
        <Group gap="xs" wrap="wrap">
          <Text size="sm" fw={600} c="dimmed">Jump to:</Text>
          {SECTIONS.map((s) => (
            <Button
              key={s.id}
              size="compact-sm"
              variant="subtle"
              onClick={() => scrollToSection(s.id)}
            >
              {s.label}
            </Button>
          ))}
        </Group>
      </Card>

      <div id="projects" style={anchorStyle}>
        <ProjectsSection canEdit={canManageChecks} canDelete={isAdmin} />
      </div>
      <div id="checks" style={anchorStyle}>
        <CheckTemplatesSection canEdit={canManageChecks} />
      </div>
      <div id="workflow" style={anchorStyle}>
        <WorkflowSection canEdit={isAdmin} />
      </div>
      <div id="tracker" style={anchorStyle}>
        <TrackerSection canEdit={isAdmin} />
      </div>
      <div id="llm" style={anchorStyle}>
        <LLMSection canEdit={isAdmin} />
      </div>
    </Stack>
  );
}
