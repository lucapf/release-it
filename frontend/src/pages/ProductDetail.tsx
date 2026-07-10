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
  IconRocket,
  IconTrash,
  IconUpload,
  IconBrandGithub,
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
  listJiraIssues,
  getIssueDetail,
  syncJira,
  getSyncFilter,
  saveSyncFilter,
  getReleaseHistory,
  Product,
  Release,
  AuditEntry,
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
// The tracker is filtered by the release label "v<major>.<minor>.<patch>"
// (e.g. v0.0.1) derived from the release version.
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
    <Tooltip label={`Tracker issues labelled "${data.label}" with type bug`}>
      <Badge
        variant="light"
        color={data.total_bugs > 0 ? "red" : "teal"}
        leftSection={<IconBug size={12} />}
      >
        Total bugs in {data.label}: {data.total_bugs}
      </Badge>
    </Tooltip>
  );
}

// --- New release control (lives alongside the release selector) ------------
function NewReleaseControl({ productId }: { productId: number }) {
  const qc = useQueryClient();
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
    <Group gap="xs" align="flex-end">
      <TextInput
        label="New release version"
        value={version}
        onChange={(e) => setVersion(e.currentTarget.value)}
        placeholder="1.2.0"
        maw={160}
      />
      <Button loading={add.isPending} onClick={() => add.mutate()}>
        Add release
      </Button>
    </Group>
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
// One day, in ms — releases not yet Approved go "stale" once their last sync
// is older than this and the date is highlighted.
const STALE_MS = 24 * 60 * 60 * 1000;

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

/** The issue's current state, read from the tracker when the operator asks for
 *  it — not from the synced cache, which only holds the columns the table shows. */
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

function JiraTab({
  releaseId,
  product,
  release,
}: {
  releaseId: number;
  product: Product;
  release: Release | null;
}) {
  const qc = useQueryClient();
  const key = ["jira", releaseId];
  const { data: issues = [] } = useQuery({ queryKey: key, queryFn: () => listJiraIssues(releaseId) });
  const { data: cfg } = useQuery({ queryKey: ["config"], queryFn: getConfig });
  const { data: savedFilter } = useQuery({
    queryKey: ["sync-filter", releaseId],
    queryFn: () => getSyncFilter(releaseId),
  });

  const version = release?.version ?? "";
  const provider = cfg?.tracker_provider ?? "jira";
  const isGitHub = provider === "github";
  const trackerName = isGitHub ? "GitHub" : "Jira";
  const repo = product.tracker_repo.trim();
  const repoMissing = isGitHub && !repo;

  // GitHub filters by milestone (default) or label; Jira by label or raw JQL.
  const [ghMode, setGhMode] = useState<"milestone" | "label">("milestone");
  const [jiraMode, setJiraMode] = useState<"label" | "jql">("label");
  const [milestone, setMilestone] = useState("");
  const [label, setLabel] = useState("");
  const [jql, setJql] = useState("");
  // The issue whose details are open, if any (its detail is fetched on demand).
  const [detailKey, setDetailKey] = useState<string | null>(null);

  // A saved filter is applied automatically once it (and the tracker) load.
  useEffect(() => {
    if (!savedFilter || !cfg) return;
    const { mode, value } = savedFilter;
    if (mode === "milestone") { setGhMode("milestone"); setMilestone(value); }
    else if (mode === "jql") { setJiraMode("jql"); setJql(value); }
    else if (mode === "label") {
      setLabel(value);
      if (isGitHub) setGhMode("label"); else setJiraMode("label");
    }
  }, [savedFilter, cfg, isGitHub]);

  // The (mode, value) currently chosen in the form, for sync and save.
  const currentFilter = (): { mode: string; value: string } => {
    if (isGitHub) return ghMode === "label" ? { mode: "label", value: label } : { mode: "milestone", value: milestone };
    return jiraMode === "jql" ? { mode: "jql", value: jql } : { mode: "label", value: label };
  };

  const sync = useMutation({
    mutationFn: () => {
      const f = currentFilter();
      if (f.mode === "milestone") return syncJira(releaseId, { milestone: f.value });
      if (f.mode === "jql") return syncJira(releaseId, { jql: f.value });
      return syncJira(releaseId, { release_label: f.value });
    },
    onSuccess: (data) => {
      qc.setQueryData(key, data);
      qc.invalidateQueries({ queryKey: ["status", releaseId] });
      notifications.show({ message: `Synced ${data.length} issue(s) from ${trackerName}`, color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Issue sync failed"),
  });

  const save = useMutation({
    mutationFn: () => { const f = currentFilter(); return saveSyncFilter(releaseId, f.mode, f.value); },
    onSuccess: (data) => {
      qc.setQueryData(["sync-filter", releaseId], data);
      notifications.show({ message: "Filter saved — it will be applied automatically", color: "teal" });
    },
    onError: (e: any) => notifyApiError(e, "Could not save filter"),
  });

  // Last sync = most recent synced_at across the cached issues. For releases
  // that are not yet Approved, a sync older than a day is highlighted in red.
  const lastSyncMs = issues.reduce((max, i) => Math.max(max, new Date(i.synced_at).getTime()), 0);
  const hasSync = lastSyncMs > 0;
  const isApproved = release?.state === "Approved";
  const stale = hasSync && !isApproved && Date.now() - lastSyncMs > STALE_MS;

  return (
    <Stack gap="md">
      <Card withBorder padding="md">
        <Group justify="space-between" mb="xs">
          <Title order={5}>Sync issues from {trackerName}</Title>
          <Badge
            variant="light"
            color={isGitHub ? "dark" : "blue"}
            leftSection={isGitHub ? <IconBrandGithub size={12} /> : undefined}
          >
            {trackerName}{repo ? ` · ${repo}` : ""}
          </Badge>
        </Group>

        <Text size="sm" mb="sm" c={stale ? "red" : "dimmed"} fw={stale ? 600 : undefined}>
          {hasSync
            ? `Last synced: ${new Date(lastSyncMs).toLocaleString()}${stale ? " — over a day old, re-sync recommended" : ""}`
            : "Not synced yet."}
        </Text>

        {repoMissing ? (
          <Alert color="orange" variant="light">
            This product has no target project set. Configure it in Configuration → Projects before syncing.
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
            <Button variant="light" loading={save.isPending} onClick={() => save.mutate()}>
              Save filter
            </Button>
          </Group>
        )}
      </Card>

      {issues.length === 0 ? (
        <Card>
          <EmptyState
            icon={IconListDetails}
            title="No issues synced yet"
            description="Use the panel above to pull issues for this release from the active tracker."
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
                <Table.Tr key={i.id}>
                  <Table.Td fw={600}>{i.issue_key}</Table.Td>
                  <Table.Td><Badge size="sm" variant="light" color="gray">{i.issue_type}</Badge></Table.Td>
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
                          aria-label={`View details of ${i.issue_key}`}
                          onClick={() => setDetailKey(i.issue_key)}
                        >
                          <IconEye size={16} />
                        </ActionIcon>
                      </Tooltip>
                      {/* Issues cached before the URL was recorded have none until
                          the next sync — `data-disabled` keeps the tooltip working,
                          which a truly disabled control would swallow. */}
                      {i.url ? (
                        <Tooltip label={`Open in ${trackerName}`}>
                          <ActionIcon
                            variant="subtle"
                            color="gray"
                            component="a"
                            href={i.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            aria-label={`Open ${i.issue_key} in ${trackerName}`}
                          >
                            <IconExternalLink size={16} />
                          </ActionIcon>
                        </Tooltip>
                      ) : (
                        <Tooltip label={`Re-sync to link this issue to ${trackerName}`}>
                          <ActionIcon variant="subtle" color="gray" data-disabled onClick={(e) => e.preventDefault()}>
                            <IconExternalLink size={16} />
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
            <JiraTab
              releaseId={activeId}
              product={product}
              release={activeRelease}
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
