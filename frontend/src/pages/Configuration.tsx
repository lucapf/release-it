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
import { IconPencil, IconTrash } from "@tabler/icons-react";
import {
  getConfig,
  updateConfig,
  getWorkflow,
  setTransitionRoles,
  listCheckTemplates,
  addCheckTemplate,
  deleteCheckTemplate,
  getOverview,
  updateProduct,
  deleteProduct,
  ConfigUpdate,
  ProductOverview,
  TransitionRoleUpdate,
  ROLES,
  Phase,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { notifyApiError } from "../lib/errors";

// --- Workflow: structure read-only, per-transition roles admin-editable ----
function WorkflowSection({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const { data: workflow, isLoading } = useQuery({ queryKey: ["workflow"], queryFn: getWorkflow });

  // Edited roles keyed by "<state>|<transition>"; seeded from the workflow.
  const [roles, setRoles] = useState<Record<string, string[]>>({});
  useEffect(() => {
    if (!workflow) return;
    const seeded: Record<string, string[]> = {};
    workflow.states.forEach((s) =>
      s.transitions.forEach((t) => { seeded[`${s.name}|${t.name}`] = t.roles; })
    );
    setRoles(seeded);
  }, [workflow]);

  const save = useMutation({
    mutationFn: () => {
      const overrides: TransitionRoleUpdate[] = [];
      workflow?.states.forEach((s) =>
        s.transitions.forEach((t) => {
          const key = `${s.name}|${t.name}`;
          overrides.push({ state: s.name, transition: t.name, roles: roles[key] ?? t.roles });
        })
      );
      return setTransitionRoles(overrides);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["workflow"] });
      notifications.show({ message: "Transition roles updated", color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Update failed"),
  });

  if (isLoading || !workflow) return <Loader />;

  const hasEmpty = workflow.states.some((s) =>
    s.transitions.some((t) => (roles[`${s.name}|${t.name}`] ?? t.roles).length === 0)
  );

  return (
    <Card withBorder radius="md" padding="lg">
      <Group justify="space-between" mb={4}>
        <Title order={4}>Release workflow</Title>
        {canEdit && (
          <Button
            size="compact-sm"
            loading={save.isPending}
            disabled={hasEmpty}
            onClick={() => save.mutate()}
          >
            Save transition roles
          </Button>
        )}
      </Group>
      <Text c="dimmed" size="sm" mb="md">
        State graph from <code>states.yaml</code> (structure is read-only). Initial state:{" "}
        <b>{workflow.initial_state}</b>. {canEdit
          ? "Choose which roles may perform each transition below."
          : "Administrators can configure which roles may perform each transition."}
      </Text>
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
        {workflow.states.map((s) => (
          <Card key={s.name} withBorder radius="md" padding="sm" bg="var(--mantine-color-gray-0)">
            <Group justify="space-between">
              <Text fw={700}>{s.name}</Text>
              {s.is_final && <Badge size="sm" color="gray" variant="light">final</Badge>}
            </Group>
            <Stack gap="sm" mt="xs">
              {s.transitions.length === 0 ? (
                <Text size="xs" c="dimmed">No outgoing transitions.</Text>
              ) : (
                s.transitions.map((t) => {
                  const key = `${s.name}|${t.name}`;
                  return (
                    <div key={t.name}>
                      <Group gap={6} wrap="nowrap" mb={2}>
                        <Badge size="sm" variant="filled" color="indigo">{t.name}</Badge>
                        <Text size="xs">→ {t.target}</Text>
                      </Group>
                      <MultiSelect
                        data={ROLES}
                        value={roles[key] ?? t.roles}
                        onChange={(v) => setRoles((prev) => ({ ...prev, [key]: v }))}
                        disabled={!canEdit}
                        size="xs"
                        placeholder="Allowed roles"
                        comboboxProps={{ withinPortal: true }}
                        error={(roles[key] ?? t.roles).length === 0 ? "At least one role" : undefined}
                      />
                    </div>
                  );
                })
              )}
            </Stack>
          </Card>
        ))}
      </SimpleGrid>
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

function ProjectsSection({ canEdit, canDelete }: { canEdit: boolean; canDelete: boolean }) {
  const { data: projects = [], isLoading } = useQuery({
    queryKey: ["overview"],
    queryFn: getOverview,
  });
  const [editing, setEditing] = useState<ProductOverview | null>(null);
  const [deleting, setDeleting] = useState<ProductOverview | null>(null);

  return (
    <Card withBorder radius="md" padding="lg">
      <Title order={4} mb={4}>Projects</Title>
      <Text c="dimmed" size="sm" mb="md">
        Manage each project's standard configuration — its name and the issue-tracker
        project its issues are synced from — or remove a project.
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
                  <Table.Td>{p.release_count}</Table.Td>
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
