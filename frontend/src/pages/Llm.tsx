import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  CopyButton,
  Group,
  Loader,
  PasswordInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Textarea,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconCheck, IconCopy, IconRestore } from "@tabler/icons-react";
import {
  getAssistantCapabilities,
  updateAssistantPrompts,
  getConfig,
  updateConfig,
  AssistantCapabilities,
  AssistantPrompt,
  ConfigUpdate,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { notifyApiError } from "../lib/errors";

// The Claude models an operator picks from. Anthropic's ids are not a uniform
// pattern (the tier and its version move independently), so the tier the operator
// thinks in is mapped to the exact id the API expects — picking "Sonnet" stores
// "claude-sonnet-5". Update these ids when moving to a newer generation.
const CLAUDE_MODELS = [
  { value: "claude-haiku-4-5", label: "Haiku — fastest, cheapest" },
  { value: "claude-sonnet-5", label: "Sonnet — balanced" },
  { value: "claude-opus-4-8", label: "Opus — most capable" },
];

// --- LLM engine configuration ----------------------------------------------
// Standalone page: the LLM engine used to draft release notes from tracked
// issues. Split out of the main Configuration page into its own route.
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

  // A model id configured before this list existed (or set straight in the env)
  // is kept as an option rather than silently rewritten to one of the three —
  // opening this page must not change what the engine is running on.
  const modelOptions = useMemo(
    () =>
      claudeModel && !CLAUDE_MODELS.some((m) => m.value === claudeModel)
        ? [...CLAUDE_MODELS, { value: claudeModel, label: `${claudeModel} (currently configured)` }]
        : CLAUDE_MODELS,
    [claudeModel],
  );

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
          <Select
            label="Model"
            placeholder="Select a model"
            data={modelOptions}
            value={claudeModel || null}
            onChange={(v) => v && setClaudeModel(v)}
            allowDeselect={false}
            disabled={!canEdit}
            description={claudeModel ? `Stored as ${claudeModel}` : undefined}
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

// --- Assistant prompts -------------------------------------------------------
// The ready-to-use prompts for the assistant's main jobs (generate + upload
// release notes, report release status, advance the workflow). Served by the
// backend alongside the tool registry so they stay in sync with what the model
// can actually do; placeholders in <angle brackets> are filled by the operator.
// Administrators can edit the title, description and body of each prompt; edits
// are stored as overrides on top of the built-in defaults, so "Reset" restores
// the shipped wording.
function PromptsSection({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient();
  const key = ["assistant-capabilities"];
  const { data, isLoading } = useQuery({ queryKey: key, queryFn: getAssistantCapabilities });

  // Local editable copy of the prompts, seeded whenever the server data changes.
  const [drafts, setDrafts] = useState<AssistantPrompt[]>([]);
  useEffect(() => {
    if (data) setDrafts(data.prompts);
  }, [data]);

  const dirty = useMemo(
    () => !!data && JSON.stringify(drafts) !== JSON.stringify(data.prompts),
    [drafts, data],
  );

  // Fold the saved prompts back into the shared capabilities cache so the
  // read-only "Assistant actions" page and the chat stay consistent.
  const applySaved = (prompts: AssistantPrompt[]) => {
    qc.setQueryData<AssistantCapabilities>(key, (old) =>
      old ? { ...old, prompts } : { actions: [], prompts },
    );
    setDrafts(prompts);
  };

  const save = useMutation({
    mutationFn: (prompts: AssistantPrompt[]) => updateAssistantPrompts(prompts),
    onSuccess: (prompts) => {
      applySaved(prompts);
      notifications.show({ message: "Prompts saved", color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Could not save prompts"),
  });

  const patch = (k: string, field: keyof AssistantPrompt, value: string) =>
    setDrafts((prev) => prev.map((p) => (p.key === k ? { ...p, [field]: value } : p)));

  return (
    <Card withBorder radius="md" padding="lg">
      <Group justify="space-between" wrap="nowrap" mb={4}>
        <Title order={4}>Assistant prompts</Title>
        {canEdit && (
          <Group gap="xs">
            <Button
              size="compact-sm"
              variant="default"
              leftSection={<IconRestore size={14} />}
              disabled={save.isPending || !data?.prompts.length}
              onClick={() => save.mutate([])}
            >
              Reset to defaults
            </Button>
            <Button
              size="compact-sm"
              loading={save.isPending}
              disabled={!dirty}
              onClick={() => save.mutate(drafts)}
            >
              Save prompts
            </Button>
          </Group>
        )}
      </Group>
      <Text c="dimmed" size="sm" mb="md">
        Prompts the LLM assistant is able to act on. Copy one into the chat and
        replace the <code>&lt;placeholders&gt;</code> with your product and version.
        {canEdit
          ? " Edit any prompt below and save; use Reset to restore the built-in wording."
          : ""}
      </Text>

      {isLoading || !data ? (
        <Loader />
      ) : (
        <Stack gap="md">
          {drafts.map((p) => (
            <Card key={p.key} withBorder radius="sm" padding="md">
              <Group justify="space-between" wrap="nowrap" mb={canEdit ? "xs" : 4} align="flex-start">
                {canEdit ? (
                  <Stack gap={6} style={{ flex: 1 }}>
                    <TextInput
                      value={p.title}
                      onChange={(e) => patch(p.key, "title", e.currentTarget.value)}
                      size="sm"
                      placeholder="Prompt title"
                      styles={{ input: { fontWeight: 600 } }}
                    />
                    <TextInput
                      value={p.description}
                      onChange={(e) => patch(p.key, "description", e.currentTarget.value)}
                      size="xs"
                      placeholder="Short description"
                    />
                  </Stack>
                ) : (
                  <div>
                    <Text fw={600}>{p.title}</Text>
                    <Text size="sm" c="dimmed">{p.description}</Text>
                  </div>
                )}
                <CopyButton value={p.prompt}>
                  {({ copied, copy }) => (
                    <Tooltip label={copied ? "Copied" : "Copy prompt"}>
                      <ActionIcon
                        variant="subtle"
                        color={copied ? "teal" : "gray"}
                        aria-label={`Copy prompt: ${p.title}`}
                        onClick={copy}
                      >
                        {copied ? <IconCheck size={16} /> : <IconCopy size={16} />}
                      </ActionIcon>
                    </Tooltip>
                  )}
                </CopyButton>
              </Group>
              {canEdit ? (
                <Textarea
                  value={p.prompt}
                  onChange={(e) => patch(p.key, "prompt", e.currentTarget.value)}
                  autosize
                  minRows={3}
                  styles={{
                    input: { fontFamily: "var(--mantine-font-family-monospace)", fontSize: "var(--mantine-font-size-sm)" },
                  }}
                />
              ) : (
                <Text
                  size="sm"
                  p="sm"
                  style={{
                    fontFamily: "var(--mantine-font-family-monospace)",
                    background: "light-dark(var(--mantine-color-gray-0), var(--mantine-color-dark-6))",
                    borderRadius: "var(--mantine-radius-sm)",
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {p.prompt}
                </Text>
              )}
            </Card>
          ))}
        </Stack>
      )}
    </Card>
  );
}

export function LlmPage() {
  const { hasRole } = useAuth();
  const isAdmin = hasRole("Administrator");

  return (
    <Stack gap="lg">
      <div>
        <Title order={2}>LLM engine</Title>
        <Text c="dimmed">The language model used to draft release notes from tracked issues.</Text>
      </div>
      <LLMSection canEdit={isAdmin} />
      <PromptsSection canEdit={isAdmin} />
    </Stack>
  );
}
