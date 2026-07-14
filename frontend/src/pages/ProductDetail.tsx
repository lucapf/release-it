import { ReactNode, useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Collapse,
  FileButton,
  Group,
  Loader,
  Menu,
  Modal,
  SegmentedControl,
  Select,
  Skeleton,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import {
  IconBug,
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconCircleMinus,
  IconClipboardText,
  IconDownload,
  IconExternalLink,
  IconEye,
  IconFile,
  IconFiles,
  IconFileText,
  IconFileTypePdf,
  IconHistory,
  IconListDetails,
  IconMarkdown,
  IconPlus,
  IconRefresh,
  IconRocket,
  IconTrash,
  IconUpload,
  IconBrandGithub,
  IconBrandGitlab,
  IconGitBranch,
  IconPencil,
} from "@tabler/icons-react";
import {
  getProduct,
  getConfig,
  getReleaseBugCount,
  listReleases,
  createRelease,
  listDocuments,
  uploadDocument,
  listDocumentVersions,
  uploadDocumentVersion,
  deleteDocument,
  downloadDocumentVersion,
  setDocumentStatus,
  listDocumentTypes,
  DocumentMeta,
  listReleaseIssues,
  searchIssues,
  addIssueToRelease,
  removeIssueFromRelease,
  getIssueDetail,
  getIssueFilter,
  saveIssueFilter,
  getReleaseHistory,
  listGitRepos,
  addGitRepo,
  updateGitRepo,
  deleteGitRepo,
  getReleaseChanges,
  Issue,
  IssueFilter,
  IssueFilterMode,
  Product,
  Release,
  AuditEntry,
  ComponentChange,
  GitRepoLink,
  GitRepoLinkCreate,
  GitRepoRole,
} from "../api/client";
import { ReleaseStatusCard } from "../components/ReleaseStatusCard";
import { EmptyState } from "../components/EmptyState";
import { useAuth } from "../auth/AuthContext";
import { apiErrorMessage, notifyApiError } from "../lib/errors";
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

// --- Total bugs in the viewed release (live from the active tracker) --------
// Counted over the same issue set the readiness gate uses — the release's saved
// sync filter, or the provider's native release grouping. The resolved filter
// comes back on the response so the tooltip can show *which* issues were counted.
function ReleaseBugTotal({ releaseId }: { releaseId: number }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["bug-count", releaseId],
    queryFn: () => getReleaseBugCount(releaseId),
    retry: false,
  });

  if (isLoading) {
    return (
      <Group gap={6}>
        <Loader size="xs" />
        <Text size="sm" c="dimmed">Counting bugs in the tracker…</Text>
      </Group>
    );
  }
  if (error || !data) {
    return (
      <Tooltip label={(error as any)?.response?.data?.detail ?? "Could not query the tracker"}>
        <Badge variant="light" color="gray" leftSection={<IconBug size={12} />}>
          Total bugs: —
        </Badge>
      </Tooltip>
    );
  }
  return (
    <Tooltip label={`Bugs among the tracker issues matching ${data.filter}`}>
      <Badge
        variant="light"
        color={data.total_bugs > 0 ? "red" : "teal"}
        leftSection={<IconBug size={12} />}
      >
        Total bugs: {data.total_bugs}
      </Badge>
    </Tooltip>
  );
}

// --- Choosing which tickets a release contains -----------------------------
// A release is defined by a search criteria (e.g. label = v0.0.1) run against the
// ticketing system. Release-It stores the criteria and nothing else: the tickets
// themselves are read from the tracker every time they are shown, so this is the
// one thing an operator has to get right.
const MODE_OPTIONS: Record<"jira" | "github", { value: IssueFilterMode; label: string }[]> = {
  github: [
    { value: "milestone", label: "Milestone" },
    { value: "label", label: "Label" },
  ],
  jira: [
    { value: "label", label: "Label" },
    { value: "jql", label: "Custom JQL" },
  ],
};

const VALUE_HINT: Record<IssueFilterMode, { label: string; placeholder: string }> = {
  milestone: { label: "Milestone", placeholder: "e.g. 0.1.0" },
  label: { label: "Label", placeholder: "e.g. v0.0.1" },
  jql: { label: "JQL query", placeholder: 'project = REL AND fixVersion = "1.2.0"' },
};

/** The criteria form: which field to search on, and what to search for. */
function CriteriaFields({
  provider,
  mode,
  value,
  onModeChange,
  onValueChange,
}: {
  provider: "jira" | "github";
  mode: IssueFilterMode;
  value: string;
  onModeChange: (m: IssueFilterMode) => void;
  onValueChange: (v: string) => void;
}) {
  const hint = VALUE_HINT[mode];
  return (
    <Group align="flex-end" gap="sm">
      <Select
        label="Find tickets by"
        data={MODE_OPTIONS[provider]}
        value={mode}
        onChange={(m) => m && onModeChange(m as IssueFilterMode)}
        maw={160}
        allowDeselect={false}
      />
      <TextInput
        label={hint.label}
        placeholder={hint.placeholder}
        value={value}
        onChange={(e) => onValueChange(e.currentTarget.value)}
        style={{ flex: 1 }}
      />
    </Group>
  );
}

/** The tickets a criteria selects, exactly as the tracker returned them. */
function IssueList({ issues }: { issues: Issue[] }) {
  return (
    <Table.ScrollContainer minWidth={480}>
      <Table striped highlightOnHover fz="sm">
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
            <Table.Tr key={i.key}>
              <Table.Td fw={600}>{i.key}</Table.Td>
              <Table.Td><Badge size="sm" variant="light" color="gray">{i.type}</Badge></Table.Td>
              <Table.Td>{i.summary}</Table.Td>
              <Table.Td>
                <Badge size="sm" variant="light" color={issueStatusColor(i.status)}>
                  {i.status}
                </Badge>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

// --- New release (version + criteria, with the tickets shown before creating) --
function NewReleaseControl({ productId }: { productId: number }) {
  const qc = useQueryClient();
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const provider = cfg?.tracker_provider ?? "jira";

  const [opened, setOpened] = useState(false);
  const [version, setVersion] = useState("1.0.0");
  const [mode, setMode] = useState<IssueFilterMode>(provider === "github" ? "milestone" : "label");
  const [value, setValue] = useState("");

  // The criteria the previewed tickets belong to. Editing the criteria after a
  // search invalidates the preview, so an operator can never create a release
  // against tickets they were not actually shown.
  const [previewed, setPreviewed] = useState<string | null>(null);
  const criteriaKey = `${mode}\u0000${value.trim()}`;
  const isPreviewCurrent = previewed === criteriaKey;

  const reset = () => {
    setOpened(false);
    setVersion("1.0.0");
    setMode(provider === "github" ? "milestone" : "label");
    setValue("");
    setPreviewed(null);
    search.reset();
  };

  const search = useMutation({
    mutationFn: () => searchIssues(productId, mode, value.trim()),
    onSuccess: () => setPreviewed(criteriaKey),
    onError: (e: any) => {
      setPreviewed(null);
      notifyApiError(e, "Could not search the ticketing system");
    },
  });

  const add = useMutation({
    mutationFn: () => createRelease(productId, version.trim(), { mode, value: value.trim() } as IssueFilter),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["releases", productId] });
      qc.invalidateQueries({ queryKey: ["overview"] });
      notifications.show({ message: "Release created", color: "teal" });
      reset();
    },
    onError: (e: any) => notifyApiError(e, "Could not create release"),
  });

  const found = search.data;

  return (
    <>
      {/* Wrapped in a Group: as a direct child of the card's Stack the button
          would stretch to the full card width. */}
      <Group>
        <Button
          size="sm"
          w="fit-content"
          leftSection={<IconRocket size={16} />}
          onClick={() => setOpened(true)}
        >
          New release
        </Button>
      </Group>

      <Modal opened={opened} onClose={reset} title="New release" size="lg">
        <Stack gap="md">
          <TextInput
            label="Version"
            placeholder="1.2.0"
            value={version}
            onChange={(e) => setVersion(e.currentTarget.value)}
            maw={200}
          />

          <div>
            <Text size="sm" fw={600}>Which tickets does this release contain?</Text>
            <Text size="xs" c="dimmed" mb="xs">
              The criteria is stored with the release. Its issues — and whether it is
              ready to ship — are read from {provider === "github" ? "GitHub" : "Jira"} with
              it, every time they are asked for.
            </Text>
            <CriteriaFields
              provider={provider}
              mode={mode}
              value={value}
              onModeChange={setMode}
              onValueChange={setValue}
            />
          </div>

          <Group>
            <Button
              variant="light"
              leftSection={<IconListDetails size={16} />}
              disabled={!value.trim()}
              loading={search.isPending}
              onClick={() => search.mutate()}
            >
              Find tickets
            </Button>
            {found && isPreviewCurrent && (
              <Text size="sm" c="dimmed">
                {found.total} ticket(s) · {found.bug_count} bug(s) · matching{" "}
                <Text span ff="monospace" size="xs">{found.query}</Text>
              </Text>
            )}
          </Group>

          {search.isError && (
            <Alert color="red" variant="light">
              {apiErrorMessage(search.error, "The ticketing system could not be searched.")}
            </Alert>
          )}

          {found && isPreviewCurrent && (
            found.total === 0 ? (
              <Alert color="orange" variant="light">
                No tickets match this criteria. You can still create the release, but it
                will contain no work until the criteria matches something.
              </Alert>
            ) : (
              <IssueList issues={found.issues} />
            )
          )}

          <Group justify="flex-end">
            <Button variant="subtle" color="gray" onClick={reset}>Cancel</Button>
            <Tooltip
              label="Search for the tickets first, so you can see what this release will contain"
              disabled={isPreviewCurrent}
            >
              <Button
                disabled={!version.trim() || !isPreviewCurrent}
                loading={add.isPending}
                onClick={() => add.mutate()}
              >
                Create release
              </Button>
            </Tooltip>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}

// --- Documents tab (uploaded files with version history) -------------------
function formatBytes(n: number | null | undefined): string {
  if (!n) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let v = n;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

// A document's approval status. Documents start as DRAFT (including anything the
// assistant generates) and an operator promotes them to APPROVED.
function DocStatusBadge({ status }: { status: DocumentMeta["status"] }) {
  const approved = status === "APPROVED";
  return (
    <Badge
      size="sm"
      variant={approved ? "filled" : "light"}
      color={approved ? "teal" : "gray"}
      leftSection={approved ? <IconCheck size={11} /> : undefined}
    >
      {approved ? "Approved" : "Draft"}
    </Badge>
  );
}

// Download control for a document version: a menu offering Markdown (to edit)
// and, when a rendered PDF companion exists, PDF (to read). Falls back to a
// single download button for documents that have no PDF (non-Markdown uploads).
function DownloadMenu({
  releaseId,
  documentId,
  versionId,
  filename,
  hasPdf,
  ariaLabel,
}: {
  releaseId: number;
  documentId: number;
  versionId: number;
  filename: string;
  hasPdf: boolean;
  ariaLabel: string;
}) {
  const dl = useMutation({
    mutationFn: (format?: "pdf") =>
      downloadDocumentVersion(releaseId, documentId, versionId, filename, format),
    onError: (e: any) => notifyApiError(e, "Download failed"),
  });

  if (!hasPdf) {
    return (
      <Tooltip label="Download">
        <ActionIcon
          variant="subtle"
          aria-label={ariaLabel}
          loading={dl.isPending}
          onClick={() => dl.mutate(undefined)}
        >
          <IconDownload size={18} />
        </ActionIcon>
      </Tooltip>
    );
  }
  return (
    <Menu shadow="md" position="bottom-end" withinPortal>
      <Menu.Target>
        <Tooltip label="Download">
          <ActionIcon variant="subtle" aria-label={ariaLabel} loading={dl.isPending}>
            <IconDownload size={18} />
          </ActionIcon>
        </Tooltip>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Download</Menu.Label>
        <Menu.Item leftSection={<IconMarkdown size={16} />} onClick={() => dl.mutate(undefined)}>
          Markdown (.md) — to edit
        </Menu.Item>
        <Menu.Item leftSection={<IconFileTypePdf size={16} />} onClick={() => dl.mutate("pdf")}>
          PDF (.pdf) — to read
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}

function VersionHistory({ releaseId, documentId }: { releaseId: number; documentId: number }) {
  const { data: versions = [], isLoading } = useQuery({
    queryKey: ["doc-versions", documentId],
    queryFn: () => listDocumentVersions(releaseId, documentId),
  });

  if (isLoading) return <Group justify="center" py="sm"><Loader size="sm" /></Group>;

  return (
    <Table.ScrollContainer minWidth={420}>
      <Table verticalSpacing="xs" fz="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Version</Table.Th>
            <Table.Th>File</Table.Th>
            <Table.Th>Size</Table.Th>
            <Table.Th>Uploaded</Table.Th>
            <Table.Th>By</Table.Th>
            <Table.Th />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {versions.map((v, idx) => (
            <Table.Tr key={v.id}>
              <Table.Td>
                <Group gap={6} wrap="nowrap">
                  <Badge size="sm" variant="light">v{v.version}</Badge>
                  {idx === 0 && <Badge size="sm" color="teal" variant="light">current</Badge>}
                </Group>
              </Table.Td>
              <Table.Td>{v.filename}</Table.Td>
              <Table.Td>{formatBytes(v.size)}</Table.Td>
              <Table.Td>{new Date(v.created_at).toLocaleString()}</Table.Td>
              <Table.Td>{v.uploaded_by || "—"}</Table.Td>
              <Table.Td>
                <DownloadMenu
                  releaseId={releaseId}
                  documentId={documentId}
                  versionId={v.id}
                  filename={v.filename}
                  hasPdf={v.pdf_size > 0}
                  ariaLabel={`Download version ${v.version}`}
                />
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

function DocumentsTab({ releaseId }: { releaseId: number }) {
  const qc = useQueryClient();
  const { hasRole } = useAuth();
  const canEdit = hasRole("Developer", "Release Manager", "Administrator");
  const canDelete = hasRole("Release Manager", "Administrator");
  const key = ["documents", releaseId];
  const { data: docs = [], isLoading } = useQuery({
    queryKey: key,
    queryFn: () => listDocuments(releaseId),
  });
  // Supported types are admin-managed on the Configuration page.
  const { data: docTypes = [] } = useQuery({
    queryKey: ["document-types"],
    queryFn: listDocumentTypes,
  });
  const [title, setTitle] = useState("");
  const [docType, setDocType] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  // A new-version upload is staged per document: picking a file selects it (and
  // re-picking replaces the selection); nothing is sent until the operator hits
  // the Upload button. Only one document can have a staged file at a time.
  const [pendingVersion, setPendingVersion] = useState<{ docId: number; file: File } | null>(null);

  const invalidate = (docId?: number) => {
    qc.invalidateQueries({ queryKey: key });
    if (docId) qc.invalidateQueries({ queryKey: ["doc-versions", docId] });
  };

  const upload = useMutation({
    mutationFn: () =>
      uploadDocument(releaseId, file as File, docType as string, title.trim() || undefined),
    onSuccess: () => {
      setFile(null);
      setTitle("");
      setDocType(null);
      invalidate();
      notifications.show({ message: "Document uploaded", color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Upload failed"),
  });

  const newVersion = useMutation({
    mutationFn: ({ docId, f }: { docId: number; f: File }) =>
      uploadDocumentVersion(releaseId, docId, f),
    onSuccess: (_d, vars) => {
      setPendingVersion(null);
      invalidate(vars.docId);
      notifications.show({ message: "New version uploaded", color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Upload failed"),
  });

  const remove = useMutation({
    mutationFn: (docId: number) => deleteDocument(releaseId, docId),
    onSuccess: () => {
      invalidate();
      notifications.show({ message: "Document deleted", color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Delete failed"),
  });

  const approve = useMutation({
    mutationFn: (docId: number) => setDocumentStatus(releaseId, docId, "APPROVED"),
    onSuccess: () => {
      invalidate();
      notifications.show({ message: "Document approved", color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Could not approve document"),
  });

  if (isLoading) return <Group justify="center" py="xl"><Loader /></Group>;

  return (
    <Stack gap="md">
      {canEdit && (
        <Card withBorder padding="md">
          <Title order={5} mb="sm">Upload a document</Title>
          <Group align="flex-end" gap="sm">
            <TextInput
              label="Title (optional)"
              placeholder="Defaults to the file name"
              value={title}
              onChange={(e) => setTitle(e.currentTarget.value)}
              style={{ flex: 1 }}
            />
            <Select
              label="Type"
              placeholder={docTypes.length ? "Select a type" : "No types configured"}
              required
              disabled={docTypes.length === 0}
              data={docTypes.map((t) => t.name)}
              value={docType}
              onChange={setDocType}
              allowDeselect={false}
              style={{ width: 170 }}
            />
            <FileButton onChange={setFile}>
              {(props) => (
                <Button {...props} variant="light" leftSection={<IconFile size={16} />}>
                  {file ? "Change file" : "Choose file"}
                </Button>
              )}
            </FileButton>
            <Button
              leftSection={<IconUpload size={16} />}
              disabled={!file || !docType}
              loading={upload.isPending}
              onClick={() => upload.mutate()}
            >
              Upload
            </Button>
          </Group>
          {file && (
            <Text size="sm" c="dimmed" mt="xs">
              Selected: {file.name} ({formatBytes(file.size)})
            </Text>
          )}
          {docTypes.length === 0 && (
            <Text size="sm" c="dimmed" mt="xs">
              No document types are configured yet — add them on the Configuration page.
            </Text>
          )}
        </Card>
      )}

      {docs.length === 0 ? (
        <Card>
          <EmptyState
            icon={IconFiles}
            title="No documents yet"
            description={
              canEdit
                ? "Upload a file above. Re-uploading to a document keeps every previous version."
                : "Documents uploaded to this release will appear here."
            }
          />
        </Card>
      ) : (
        <Stack gap="sm">
          {docs.map((d) => {
            const open = expanded === d.id;
            return (
              <Card key={d.id} withBorder padding="md">
                <Group justify="space-between" wrap="nowrap">
                  <Group gap={8} wrap="nowrap" style={{ minWidth: 0 }}>
                    <IconFileText size={18} stroke={1.6} color="var(--mantine-color-dimmed)" />
                    <div style={{ minWidth: 0 }}>
                      <Group gap={6} wrap="nowrap">
                        <Text fw={600} truncate>{d.title}</Text>
                        <Badge size="sm" variant="light" color="grape">{d.doc_type}</Badge>
                        <DocStatusBadge status={d.status} />
                      </Group>
                      <Text size="xs" c="dimmed">
                        {d.latest_filename} · {formatBytes(d.latest_size)} ·{" "}
                        {d.updated_at ? new Date(d.updated_at).toLocaleString() : "—"}
                      </Text>
                    </div>
                  </Group>
                  <Group gap={6} wrap="nowrap">
                    <Badge variant="light">v{d.latest_version ?? 1}</Badge>
                    {canEdit && d.status !== "APPROVED" && (
                      <Button
                        size="compact-sm"
                        variant="light"
                        color="teal"
                        leftSection={<IconCheck size={14} />}
                        loading={approve.isPending && approve.variables === d.id}
                        onClick={() => approve.mutate(d.id)}
                      >
                        Approve
                      </Button>
                    )}
                    {d.latest_version_id != null && (
                      <DownloadMenu
                        releaseId={releaseId}
                        documentId={d.id}
                        versionId={d.latest_version_id}
                        filename={d.latest_filename || `${d.title}.md`}
                        hasPdf={(d.latest_pdf_size ?? 0) > 0}
                        ariaLabel="Download latest"
                      />
                    )}
                    {canEdit && (
                      <FileButton onChange={(f) => f && setPendingVersion({ docId: d.id, file: f })}>
                        {(props) => (
                          <Tooltip label="Select a new version">
                            <ActionIcon
                              {...props}
                              variant="subtle"
                              aria-label="Select a new version"
                            >
                              <IconUpload size={18} />
                            </ActionIcon>
                          </Tooltip>
                        )}
                      </FileButton>
                    )}
                    <Tooltip label={open ? "Hide versions" : `Show ${d.version_count} version(s)`}>
                      <ActionIcon
                        variant="subtle"
                        aria-label="Toggle version history"
                        onClick={() => setExpanded(open ? null : d.id)}
                      >
                        {open ? <IconChevronDown size={18} /> : <IconChevronRight size={18} />}
                      </ActionIcon>
                    </Tooltip>
                    {canDelete && (
                      <Tooltip label="Delete document">
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          aria-label="Delete document"
                          loading={remove.isPending && remove.variables === d.id}
                          onClick={() => remove.mutate(d.id)}
                        >
                          <IconTrash size={18} />
                        </ActionIcon>
                      </Tooltip>
                    )}
                  </Group>
                </Group>
                {canEdit && pendingVersion?.docId === d.id && (
                  <Group align="center" gap="sm" mt="sm" wrap="nowrap">
                    <Text size="sm" style={{ flex: 1, minWidth: 0 }} truncate>
                      New version: {pendingVersion.file.name} ({formatBytes(pendingVersion.file.size)})
                    </Text>
                    <FileButton
                      onChange={(f) => f && setPendingVersion({ docId: d.id, file: f })}
                    >
                      {(props) => (
                        <Button {...props} size="compact-sm" variant="light" leftSection={<IconFile size={14} />}>
                          Change file
                        </Button>
                      )}
                    </FileButton>
                    <Button
                      size="compact-sm"
                      leftSection={<IconUpload size={14} />}
                      loading={newVersion.isPending && newVersion.variables?.docId === d.id}
                      onClick={() => newVersion.mutate({ docId: d.id, f: pendingVersion.file })}
                    >
                      Upload
                    </Button>
                    <Button
                      size="compact-sm"
                      variant="subtle"
                      color="gray"
                      onClick={() => setPendingVersion(null)}
                    >
                      Cancel
                    </Button>
                  </Group>
                )}
                <Collapse in={open}>
                  <Stack gap={0} mt="sm">
                    {open && <VersionHistory releaseId={releaseId} documentId={d.id} />}
                  </Stack>
                </Collapse>
              </Card>
            );
          })}
        </Stack>
      )}
    </Stack>
  );
}

// --- Issues tab (tracker-aware: Jira or GitHub) ----------------------------
// The issues shown here are read from the ticketing system on every render, so
// there is no "last synced" time and nothing can go stale: what you see is what
// the tracker says now.

/** A labelled line in the detail modal; renders nothing when the tracker has
 *  no value for the field (GitHub has no priority, issues may be unassigned). */
function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  if (!children) return null;
  return (
    <Group gap="xs" wrap="nowrap" align="baseline">
      <Text size="sm" c="dimmed" w={90} style={{ flexShrink: 0 }}>
        {label}
      </Text>
      <Text size="sm">{children}</Text>
    </Group>
  );
}

const formatIssueDate = (raw: string) => (raw ? new Date(raw).toLocaleString() : "");

/** One issue in full (description, people, timestamps) — more than the list
 *  needs, so it is fetched only when the operator opens it. */
function IssueDetailModal({
  releaseId,
  issueKey,
  trackerName,
  onClose,
}: {
  releaseId: number;
  issueKey: string | null;
  trackerName: string;
  onClose: () => void;
}) {
  const { data: issue, isPending, error } = useQuery({
    queryKey: ["issue-detail", releaseId, issueKey],
    queryFn: () => getIssueDetail(releaseId, issueKey!),
    enabled: !!issueKey,
    // A deleted issue (404) or an unreachable tracker (502) won't fix itself
    // within a retry window — report it instead of stalling behind backoff.
    retry: false,
  });

  return (
    <Modal opened={!!issueKey} onClose={onClose} title={issueKey ?? "Issue"} size="lg">
      {error ? (
        <Alert color="red" variant="light">
          {apiErrorMessage(error, `Could not load ${issueKey} from ${trackerName}`)}
        </Alert>
      ) : isPending || !issue ? (
        <Stack gap="xs">
          <Skeleton height={20} width="60%" />
          <Skeleton height={14} />
          <Skeleton height={14} width="80%" />
        </Stack>
      ) : (
        <Stack gap="md">
          <div>
            <Title order={5}>{issue.summary}</Title>
            <Group gap="xs" mt="xs">
              <Badge size="sm" variant="light" color="gray">{issue.type}</Badge>
              <Badge size="sm" variant="light" color={issueStatusColor(issue.status)}>
                {issue.status}
              </Badge>
              {issue.labels.map((l) => (
                <Badge key={l} size="sm" variant="outline" color="gray">{l}</Badge>
              ))}
            </Group>
          </div>

          <Stack gap={4}>
            <DetailRow label="Assignee">{issue.assignee}</DetailRow>
            <DetailRow label="Reporter">{issue.reporter}</DetailRow>
            <DetailRow label="Priority">{issue.priority}</DetailRow>
            <DetailRow label="Created">{formatIssueDate(issue.created_at)}</DetailRow>
            <DetailRow label="Updated">{formatIssueDate(issue.updated_at)}</DetailRow>
          </Stack>

          <div>
            <Text size="sm" c="dimmed" mb={4}>Description</Text>
            {issue.description ? (
              <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>{issue.description}</Text>
            ) : (
              <Text size="sm" c="dimmed" fs="italic">No description.</Text>
            )}
          </div>

          {issue.url && (
            <Group justify="flex-end">
              <Button
                component="a"
                href={issue.url}
                target="_blank"
                rel="noopener noreferrer"
                variant="light"
                leftSection={<IconExternalLink size={16} />}
              >
                Open in {trackerName}
              </Button>
            </Group>
          )}
        </Stack>
      )}
    </Modal>
  );
}

function IssuesTab({
  releaseId,
  product,
  release,
}: {
  releaseId: number;
  product: Product;
  release: Release | null;
}) {
  const qc = useQueryClient();
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const { data: criteria } = useQuery({
    queryKey: ["issue-filter", releaseId],
    queryFn: () => getIssueFilter(releaseId),
  });

  // The tickets themselves: straight from the tracker, every time. A failure here
  // is shown as a failure — an empty table would read as "this release has no
  // work left", which is the one thing it must never say by accident.
  const {
    data: issues = [],
    isFetching,
    error,
    refetch,
  } = useQuery({
    queryKey: ["issues", releaseId],
    queryFn: () => listReleaseIssues(releaseId),
    retry: false,
  });

  const version = release?.version ?? "";
  const provider = cfg?.tracker_provider ?? "jira";
  const isGitHub = provider === "github";
  const trackerName = isGitHub ? "GitHub" : "Jira";
  const repo = product.tracker_repo.trim();
  const repoMissing = isGitHub && !repo;

  const [editing, setEditing] = useState(false);
  const [mode, setMode] = useState<IssueFilterMode>(isGitHub ? "milestone" : "label");
  const [value, setValue] = useState("");
  const [detailKey, setDetailKey] = useState<string | null>(null);
  const [newKey, setNewKey] = useState("");

  // Seed the edit form from the stored criteria once it loads.
  useEffect(() => {
    if (!criteria) return;
    setMode(criteria.mode);
    setValue(criteria.value);
  }, [criteria]);

  // Everything a release's issues feed is answered by the tracker, so a ticket
  // moving in or out of the release invalidates all of it.
  const invalidateIssues = () => {
    qc.invalidateQueries({ queryKey: ["issues", releaseId] });
    qc.invalidateQueries({ queryKey: ["status", releaseId] });
    qc.invalidateQueries({ queryKey: ["bug-count", releaseId] });
    qc.invalidateQueries({ queryKey: ["history", releaseId] });
  };

  // Adding or removing a ticket edits the ticket itself in the tracker — it is
  // the only place membership exists. The notification names the edit, because
  // this changed something in the operator's ticketing system, not just here.
  const membership = useMutation({
    mutationFn: ({ key, member }: { key: string; member: boolean }) =>
      member ? addIssueToRelease(releaseId, key) : removeIssueFromRelease(releaseId, key),
    onSuccess: (data, vars) => {
      setNewKey("");
      invalidateIssues();
      notifications.show({
        color: "teal",
        message: vars.member
          ? `${data.key} added — ${data.criteria} set on the ticket in ${trackerName}`
          : `${data.key} removed — ${data.criteria} cleared on the ticket in ${trackerName}`,
      });
    },
    onError: (e: any, vars) =>
      notifyApiError(e, `Could not ${vars.member ? "add" : "remove"} the ticket`),
  });

  const save = useMutation({
    mutationFn: () => saveIssueFilter(releaseId, mode, value.trim()),
    onSuccess: (data) => {
      qc.setQueryData(["issue-filter", releaseId], data);
      // The criteria decides which tickets the release contains, so everything
      // derived from them is now answering a different question.
      qc.invalidateQueries({ queryKey: ["issues", releaseId] });
      qc.invalidateQueries({ queryKey: ["status", releaseId] });
      qc.invalidateQueries({ queryKey: ["bug-count", releaseId] });
      qc.invalidateQueries({ queryKey: ["history", releaseId] });
      setEditing(false);
      notifications.show({ message: "Criteria updated", color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Could not update the criteria"),
  });

  const describeCriteria = () => {
    if (criteria) return `${criteria.mode} = ${criteria.value}`;
    // Releases created before criteria were recorded fall back to the tracker's
    // own release grouping.
    return isGitHub ? `milestone = ${version} (default)` : `fixVersion = ${version} (default)`;
  };

  return (
    <Stack gap="md">
      <Card withBorder padding="md">
        <Group justify="space-between" mb="xs">
          <Title order={5}>Tickets in this release</Title>
          <Badge
            variant="light"
            color={isGitHub ? "dark" : "blue"}
            leftSection={isGitHub ? <IconBrandGithub size={12} /> : undefined}
          >
            {trackerName}{repo ? ` · ${repo}` : ""}
          </Badge>
        </Group>

        <Text size="sm" c="dimmed" mb="sm">
          Read from {trackerName} on every view — Release-It stores only the search
          criteria below, never the tickets.
        </Text>

        {repoMissing ? (
          <Alert color="orange" variant="light">
            This product has no target project set. Configure it in Configuration → Projects
            before its issues can be read.
          </Alert>
        ) : editing ? (
          <Stack gap="sm">
            <CriteriaFields
              provider={provider}
              mode={mode}
              value={value}
              onModeChange={setMode}
              onValueChange={setValue}
            />
            <Group>
              <Button
                disabled={!value.trim()}
                loading={save.isPending}
                onClick={() => save.mutate()}
              >
                Save criteria
              </Button>
              <Button
                variant="subtle"
                color="gray"
                onClick={() => {
                  setEditing(false);
                  if (criteria) { setMode(criteria.mode); setValue(criteria.value); }
                }}
              >
                Cancel
              </Button>
            </Group>
          </Stack>
        ) : (
          <Group gap="sm">
            <Badge size="lg" variant="light" color="grape" leftSection={<IconListDetails size={12} />}>
              {describeCriteria()}
            </Badge>
            <Button size="compact-sm" variant="light" onClick={() => setEditing(true)}>
              Change criteria
            </Button>
            <Button
              size="compact-sm"
              variant="subtle"
              leftSection={<IconRefresh size={14} />}
              loading={isFetching}
              onClick={() => refetch()}
            >
              Refresh
            </Button>
          </Group>
        )}

        {/* Adding a ticket edits the ticket: it joins the release by coming to
            match the criteria. The hint says so, because this writes to the
            operator's ticketing system. */}
        {!repoMissing && !editing && (
          <Group align="flex-end" gap="sm" mt="md">
            <TextInput
              label="Add a ticket to this release"
              description={
                criteria
                  ? `Sets ${criteria.mode} "${criteria.value}" on the ticket in ${trackerName}, so it matches this release's criteria`
                  : `Give this release a criteria first — a ticket joins it by matching one`
              }
              placeholder={isGitHub ? "e.g. #12" : "e.g. REL-1"}
              value={newKey}
              disabled={!criteria}
              onChange={(e) => setNewKey(e.currentTarget.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newKey.trim())
                  membership.mutate({ key: newKey.trim(), member: true });
              }}
              style={{ flex: 1, maxWidth: 420 }}
            />
            <Button
              leftSection={<IconPlus size={16} />}
              disabled={!newKey.trim() || !criteria}
              loading={membership.isPending && membership.variables?.member === true}
              onClick={() => membership.mutate({ key: newKey.trim(), member: true })}
            >
              Add ticket
            </Button>
          </Group>
        )}
      </Card>

      {error ? (
        <Alert color="red" variant="light" title={`Could not read the issues from ${trackerName}`}>
          {apiErrorMessage(error, "The ticketing system could not be reached.")}
        </Alert>
      ) : issues.length === 0 ? (
        <Card>
          <EmptyState
            icon={IconListDetails}
            title="No tickets match this criteria"
            description={`No issues in ${trackerName} match ${describeCriteria()}. Change the criteria above if this release should contain other work.`}
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
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {issues.map((i) => (
                <Table.Tr key={i.key}>
                  <Table.Td fw={600}>{i.key}</Table.Td>
                  <Table.Td><Badge size="sm" variant="light" color="gray">{i.type}</Badge></Table.Td>
                  <Table.Td>{i.summary}</Table.Td>
                  <Table.Td>
                    <Badge size="sm" variant="light" color={issueStatusColor(i.status)}>{i.status}</Badge>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} justify="flex-end" wrap="nowrap">
                      <Tooltip label="View details">
                        <ActionIcon
                          variant="subtle"
                          color="gray"
                          aria-label={`View details of ${i.key}`}
                          onClick={() => setDetailKey(i.key)}
                        >
                          <IconEye size={16} />
                        </ActionIcon>
                      </Tooltip>
                      {i.url && (
                        <Tooltip label={`Open in ${trackerName}`}>
                          <ActionIcon
                            variant="subtle"
                            color="gray"
                            component="a"
                            href={i.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            aria-label={`Open ${i.key} in ${trackerName}`}
                          >
                            <IconExternalLink size={16} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                      {criteria && (
                        // Spelled out, because this edits the ticket in the
                        // operator's tracker — it does not delete it, and it does
                        // not just hide it from a list of ours.
                        <Tooltip
                          label={`Remove from this release — clears ${criteria.mode} "${criteria.value}" on ${i.key} in ${trackerName}`}
                          multiline
                          w={260}
                        >
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            aria-label={`Remove ${i.key} from this release`}
                            loading={
                              membership.isPending &&
                              membership.variables?.key === i.key &&
                              membership.variables?.member === false
                            }
                            onClick={() => membership.mutate({ key: i.key, member: false })}
                          >
                            <IconCircleMinus size={16} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      <IssueDetailModal
        releaseId={releaseId}
        issueKey={detailKey}
        trackerName={trackerName}
        onClose={() => setDetailKey(null)}
      />
    </Stack>
  );
}

// --- History tab -----------------------------------------------------------
const ACTION_LABEL: Record<string, string> = {
  created: "Created",
  status_update: "State change",
  inherited: "Inherited",
  issue_criteria: "Issue criteria",
  issue_added: "Ticket added",
  issue_removed: "Ticket removed",
  jira_sync: "Jira sync",  // historical: recorded when issues were still synced
};

function describeChange(e: AuditEntry): string {
  if (e.action === "status_update") return `${e.old_value ?? "?"} → ${e.new_value ?? "?"}`;
  if (e.action === "created") return `Initial state: ${e.new_value ?? "?"}`;
  if (e.action === "inherited") return `From release #${e.old_value} → #${e.new_value}`;
  if (e.action === "issue_criteria")
    return e.old_value ? `${e.old_value} → ${e.new_value}` : (e.new_value ?? "");
  if (e.action === "issue_added" || e.action === "issue_removed") return e.new_value ?? "";
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
    <Table.ScrollContainer minWidth={640}>
      <Table verticalSpacing="sm" highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>When</Table.Th>
            <Table.Th>Step</Table.Th>
            <Table.Th>Change</Table.Th>
            <Table.Th>Note</Table.Th>
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
              <Table.Td>
                <Text size="sm" c={e.note ? undefined : "dimmed"}>{e.note || "—"}</Text>
              </Table.Td>
              <Table.Td><Text size="sm">{e.operator || "—"}</Text></Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

// --- Page ------------------------------------------------------------------
// --- Components & repositories ----------------------------------------------
// One row per linked git repository. For components, the version column shows
// what the selected release ships (moduleX 1.0.1 → 1.1.0), read live from the
// umbrella chart's tags. A hosting that could not be asked shows its error —
// it must never look like "no changes".

const ROLE_COLOR: Record<GitRepoRole, string> = {
  deployment: "grape",
  codebase: "teal",
  component: "blue",
  library: "gray",
};

// The name change detection gives the single component of a codebase repo.
const codebaseName = (r: GitRepoLink) =>
  r.component_name || r.repo.split("/").pop() || r.repo;

function ProviderIcon({ provider }: { provider: string }) {
  return provider === "gitlab" ? <IconBrandGitlab size={16} /> : <IconBrandGithub size={16} />;
}

function VersionChange({ change }: { change: ComponentChange | undefined }) {
  if (!change) return <Text size="sm" c="dimmed">—</Text>;
  if (change.status === "error") {
    return (
      <Tooltip label={change.error} multiline w={320}>
        <Badge color="red" variant="light">could not diff</Badge>
      </Tooltip>
    );
  }
  if (change.status === "added") {
    return <Text size="sm" c="teal">new in this release ({change.new_version})</Text>;
  }
  if (change.status === "removed") {
    return <Text size="sm" c="dimmed">removed (was {change.old_version})</Text>;
  }
  if (change.status === "changed") {
    return (
      <Group gap={6} wrap="nowrap">
        <Text size="sm" c="dimmed">{change.old_version}</Text>
        <Text size="sm" c="dimmed">→</Text>
        <Text size="sm" fw={600} c="teal">{change.new_version}</Text>
        {change.commit_count > 0 && (
          <Text size="xs" c="dimmed">
            ({change.commit_count} commit{change.commit_count === 1 ? "" : "s"})
          </Text>
        )}
      </Group>
    );
  }
  return <Text size="sm">{change.new_version}</Text>;
}

const EMPTY_REPO_FORM: GitRepoLinkCreate = {
  provider: "github", repo: "", role: "component",
  component_name: "", tag_pattern: "v{version}", web_url: "", chart_path: "Chart.yaml",
};

function GitRepoModal({
  productId,
  editing,
  opened,
  onClose,
}: {
  productId: number;
  editing: GitRepoLink | null;
  opened: boolean;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState<GitRepoLinkCreate>(EMPTY_REPO_FORM);
  useEffect(() => {
    setForm(editing ? {
      provider: editing.provider, repo: editing.repo, role: editing.role,
      component_name: editing.component_name, tag_pattern: editing.tag_pattern,
      web_url: editing.web_url, chart_path: editing.chart_path,
    } : EMPTY_REPO_FORM);
  }, [editing, opened]);

  const set = (patch: Partial<GitRepoLinkCreate>) => setForm((f) => ({ ...f, ...patch }));

  const save = useMutation({
    mutationFn: () =>
      editing ? updateGitRepo(productId, editing.id, form) : addGitRepo(productId, form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["git-repos", productId] });
      qc.invalidateQueries({ queryKey: ["release-changes"] });
      notifications.show({
        message: editing ? "Repository updated" : "Repository linked",
        color: "teal",
      });
      onClose();
    },
    // The backend verifies the repo against the hosting before saving; its
    // message says exactly what failed (unknown repo, connection not set up…).
    onError: (e: any) => notifyApiError(e, "Could not save the repository link"),
  });

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={editing ? "Edit repository link" : "Link a repository"}
    >
      <Stack gap="sm">
        <SegmentedControl
          data={[{ value: "github", label: "GitHub" }, { value: "gitlab", label: "GitLab" }]}
          value={form.provider}
          onChange={(v) => set({ provider: v as GitRepoLinkCreate["provider"] })}
        />
        <TextInput
          label="Repository"
          placeholder={form.provider === "github" ? "owner/repo" : "group/project"}
          value={form.repo}
          onChange={(e) => set({ repo: e.currentTarget.value })}
          required
        />
        <Select
          label="Role"
          data={[
            { value: "component", label: "Component (a service in the umbrella chart)" },
            { value: "library", label: "Library (linked for reference only)" },
            { value: "deployment", label: "Deployment (the Helm umbrella chart)" },
            { value: "codebase", label: "Codebase (simple product: the whole code in one repo)" },
          ]}
          value={form.role}
          onChange={(v) => set({ role: (v as GitRepoRole) ?? "component" })}
          allowDeselect={false}
        />
        {form.role === "codebase" && (
          <Text size="xs" c="dimmed">
            The repository is tagged with the product release version; each release
            is diffed directly against the previous one's tag.
          </Text>
        )}
        {form.role === "component" && (
          <TextInput
            label="Component name"
            description="The dependency name this service appears under in the umbrella Chart.yaml."
            value={form.component_name}
            onChange={(e) => set({ component_name: e.currentTarget.value })}
            required
          />
        )}
        {form.role === "deployment" && (
          <TextInput
            label="Chart path"
            description="Where the umbrella Chart.yaml lives inside the repository."
            value={form.chart_path}
            onChange={(e) => set({ chart_path: e.currentTarget.value })}
          />
        )}
        <TextInput
          label="Tag pattern"
          description="How a version becomes a tag in this repository ({version} is replaced)."
          value={form.tag_pattern}
          onChange={(e) => set({ tag_pattern: e.currentTarget.value })}
        />
        <TextInput
          label="Web URL (optional)"
          description="Normally derived from the provider (e.g. github.com/owner/repo) — set it only to link somewhere else."
          placeholder="derived automatically"
          value={form.web_url}
          onChange={(e) => set({ web_url: e.currentTarget.value })}
        />
        <Group justify="flex-end" mt="sm">
          <Button variant="default" onClick={onClose}>Cancel</Button>
          <Button loading={save.isPending} onClick={() => save.mutate()}>
            {editing ? "Save" : "Link repository"}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function ComponentsTab({
  productId,
  releaseId,
}: {
  productId: number;
  releaseId: number | null;
}) {
  const { hasRole } = useAuth();
  const canEdit = hasRole("Administrator");
  const qc = useQueryClient();

  const { data: repos = [], isLoading } = useQuery({
    queryKey: ["git-repos", productId],
    queryFn: () => listGitRepos(productId),
  });
  // The version anchor: the umbrella chart, or the codebase repo of a simple
  // single-repo product.
  const hasAnchor = repos.some((r) => r.role === "deployment" || r.role === "codebase");

  // The selected release's change-set. Only asked for once an anchor repo is
  // linked (without one the answer is always "unavailable", not "no changes").
  const changesQuery = useQuery({
    queryKey: ["release-changes", releaseId],
    queryFn: () => getReleaseChanges(releaseId!),
    enabled: releaseId != null && hasAnchor,
    retry: false,
  });
  const changes = changesQuery.data;
  const byComponent = useMemo(() => {
    const map = new Map<string, ComponentChange>();
    changes?.components.forEach((c) => map.set(c.name, c));
    return map;
  }, [changes]);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<GitRepoLink | null>(null);

  const remove = useMutation({
    mutationFn: (linkId: number) => deleteGitRepo(productId, linkId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["git-repos", productId] });
      qc.invalidateQueries({ queryKey: ["release-changes"] });
      notifications.show({ message: "Repository unlinked", color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Could not unlink the repository"),
  });

  if (isLoading) return <Loader />;

  return (
    <Stack gap="md">
      {repos.length === 0 ? (
        <Card>
          <EmptyState
            icon={IconGitBranch}
            title="No repositories linked"
            description="Link the product's git repositories: one per component, plus the Helm umbrella chart as the deployment repository."
          />
        </Card>
      ) : (
        <Card withBorder radius="md" padding="md">
          {!hasAnchor && (
            <Alert color="yellow" variant="light" mb="md">
              No version-anchor repository is linked, so version changes cannot be
              computed. Link the Helm umbrella chart (role "deployment") or, for a
              simple single-repo product, the codebase (role "codebase").
            </Alert>
          )}
          {changes?.baseline_missing && (
            <Alert color="yellow" variant="light" mb="md">
              {changes.baseline_missing}
            </Alert>
          )}
          {changesQuery.error != null && (
            <Alert color="red" variant="light" mb="md">
              {apiErrorMessage(changesQuery.error, "Could not read the release's changes from the git hosting.")}
            </Alert>
          )}

          <Table verticalSpacing="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Component</Table.Th>
                <Table.Th>Role</Table.Th>
                <Table.Th>Repository</Table.Th>
                <Table.Th>Version</Table.Th>
                {canEdit && <Table.Th w={90} />}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {repos.map((r) => (
                <Table.Tr key={r.id}>
                  <Table.Td>
                    <Text size="sm" fw={600}>
                      {r.role === "component" ? r.component_name : r.repo.split("/").pop()}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge color={ROLE_COLOR[r.role as GitRepoRole] ?? "gray"} variant="light">
                      {r.role}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={6} wrap="nowrap">
                      <ProviderIcon provider={r.provider} />
                      {r.web_url ? (
                        <Anchor href={r.web_url} target="_blank" size="sm">
                          {r.repo} <IconExternalLink size={12} />
                        </Anchor>
                      ) : (
                        <Text size="sm">{r.repo}</Text>
                      )}
                    </Group>
                  </Table.Td>
                  <Table.Td>
                    {r.role === "component" ? (
                      <VersionChange change={byComponent.get(r.component_name)} />
                    ) : r.role === "codebase" ? (
                      <VersionChange change={byComponent.get(codebaseName(r))} />
                    ) : r.role === "deployment" ? (
                      <Text size="sm" c="dimmed">
                        {changes?.new_tag ? `tag ${changes.new_tag}` : "—"}
                      </Text>
                    ) : (
                      <Text size="sm" c="dimmed">—</Text>
                    )}
                  </Table.Td>
                  {canEdit && (
                    <Table.Td>
                      <Group gap={4} wrap="nowrap" justify="flex-end">
                        <Tooltip label="Edit link">
                          <ActionIcon
                            variant="subtle"
                            onClick={() => { setEditing(r); setModalOpen(true); }}
                          >
                            <IconPencil size={16} />
                          </ActionIcon>
                        </Tooltip>
                        <Tooltip label="Unlink">
                          <ActionIcon
                            variant="subtle"
                            color="red"
                            loading={remove.isPending && remove.variables === r.id}
                            onClick={() => remove.mutate(r.id)}
                          >
                            <IconTrash size={16} />
                          </ActionIcon>
                        </Tooltip>
                      </Group>
                    </Table.Td>
                  )}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>

          {changes && changes.unmatched_dependencies.length > 0 && (
            <Alert color="orange" variant="light" mt="md">
              <Text size="sm" fw={600} mb={4}>
                Chart.yaml dependencies with no linked repository:
              </Text>
              {changes.unmatched_dependencies.map((d) => (
                <Text size="sm" key={d.name}>
                  {d.name}{" "}
                  {d.old_version !== d.new_version
                    ? `(${d.old_version ?? "new"} → ${d.new_version ?? "removed"})`
                    : `(${d.new_version})`}
                </Text>
              ))}
            </Alert>
          )}
        </Card>
      )}

      {canEdit && (
        <Group>
          <Button
            leftSection={<IconPlus size={16} />}
            variant="light"
            onClick={() => { setEditing(null); setModalOpen(true); }}
          >
            Link repository
          </Button>
        </Group>
      )}

      <GitRepoModal
        productId={productId}
        editing={editing}
        opened={modalOpen}
        onClose={() => setModalOpen(false)}
      />
    </Stack>
  );
}

export function ProductDetailPage() {
  const { productId } = useParams();
  const [searchParams] = useSearchParams();
  const { hasRole } = useAuth();
  const canCreate = hasRole("Developer", "Release Manager", "Administrator");
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

      {(activeRelease || canCreate) && (
        <Card withBorder radius="md" padding="md">
          <Stack gap="md">
            {activeRelease ? (
              <>
                <ReleaseSelector
                  releases={releases}
                  byKind={byKind}
                  value={activeId}
                  onChange={setSelected}
                />
                <ReleaseBugTotal releaseId={activeRelease.id} />
              </>
            ) : (
              <Text c="dimmed" size="sm">
                No releases yet. Add the first release to begin tracking it through the workflow.
              </Text>
            )}
            {canCreate && <NewReleaseControl productId={id} />}
          </Stack>
        </Card>
      )}

      <Tabs defaultValue="overview" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="overview" leftSection={<IconClipboardText size={16} />}>Overview</Tabs.Tab>
          <Tabs.Tab value="documents" leftSection={<IconFiles size={16} />}>Documents</Tabs.Tab>
          <Tabs.Tab value="issues" leftSection={<IconListDetails size={16} />}>Issues</Tabs.Tab>
          <Tabs.Tab value="components" leftSection={<IconGitBranch size={16} />}>Components</Tabs.Tab>
          <Tabs.Tab value="history" leftSection={<IconHistory size={16} />}>History</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="overview" pt="md">
          {activeRelease ? (
            <ReleaseStatusCard release={activeRelease} />
          ) : needsRelease("see its status")}
        </Tabs.Panel>

        <Tabs.Panel value="documents" pt="md">
          {activeId ? <DocumentsTab releaseId={activeId} /> : needsRelease("manage documents")}
        </Tabs.Panel>

        <Tabs.Panel value="issues" pt="md">
          {activeId && product ? (
            <IssuesTab
              releaseId={activeId}
              product={product}
              release={activeRelease}
            />
          ) : (
            needsRelease("see its tickets")
          )}
        </Tabs.Panel>

        <Tabs.Panel value="components" pt="md">
          <ComponentsTab productId={id} releaseId={activeId} />
        </Tabs.Panel>

        <Tabs.Panel value="history" pt="md">
          {activeId ? <HistoryTab releaseId={activeId} /> : needsRelease("see its history")}
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
