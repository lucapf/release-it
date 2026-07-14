import axios from "axios";

// Single axios instance. The Bearer token (obtained from the auth service) is
// attached to every request; resource-server endpoints live under /api/v1.
export const api = axios.create({ baseURL: "/" });

const TOKEN_KEY = "releaseit_token";

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Event the app listens for to sign the user out on an expired/invalid token.
export const SESSION_EXPIRED_EVENT = "releaseit:session-expired";

// A 401 on any authenticated call means the stored token is expired or invalid.
// Clear it and notify the app so it can redirect to login — but leave the login
// request's own 401 ("invalid credentials") for the login form to handle.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const url: string = error?.config?.url ?? "";
    const isLogin = url.includes("/user-management/login");
    if (error?.response?.status === 401 && !isLogin) {
      error.sessionExpired = true;
      if (getToken()) {
        setToken(null);
        window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
      }
    }
    return Promise.reject(error);
  }
);

// --- Typed API helpers -----------------------------------------------------
export interface Product {
  id: number; name: string; tracker_repo: string;
}
export interface Release {
  id: number; product_id: number; version: string; state: string;
  short_description: string; parent_release_id: number | null;
}
export interface ProductOverview extends Product {
  release_count: number;
  last_stable: Release | null;
  draft: Release | null;
  under_approval: Release | null;
}
// One ticket, as the ticketing system reports it *now*. Nothing about issues is
// stored by Release-It, so there is no row id and no "synced at" — every list is
// read from the tracker when it is displayed.
export interface Issue {
  key: string; type: string; summary: string; status: string;
  // Whether the tracker considers the issue finished — its own verdict (Jira's
  // statusCategory, GitHub/GitLab's issue state), not a match against a status
  // name. A project may call its done-status "Resolved" and this is still true.
  closed: boolean;
  url: string;  // the issue's page in the tracker's web UI
}

// The search criteria that defines which tickets a release contains, e.g.
// label = v0.0.1. Which modes are valid depends on the tracker: GitHub takes
// milestone/label, Jira takes label/jql.
export type IssueFilterMode = "milestone" | "label" | "jql";
export interface IssueFilter { mode: IssueFilterMode; value: string }
export interface IssueFilterView extends IssueFilter {
  release_id: number; updated_at: string;
}
// What a criteria finds, previewed before it is bound to a release.
export interface IssueSearchResult {
  query: string; total: number; bug_count: number; issues: Issue[];
}
// One issue read live from the tracker. Fields the active tracker does not
// carry come back empty (GitHub has no priority, an unassigned issue no assignee).
export interface IssueDetail {
  key: string; type: string; summary: string; status: string; url: string;
  description: string; assignee: string; reporter: string; priority: string;
  labels: string[]; created_at: string; updated_at: string;
}
// Supported document types are admin-managed (configured on the Configuration
// page); fetch the live set via listDocumentTypes rather than hardcoding them.
export type DocumentTypeKind = "manual" | "generated";
export interface DocumentType {
  id: number;
  name: string;
  kind: DocumentTypeKind;
  generation_prompt: string;
  created_at: string;
}

export type DocumentStatus = "DRAFT" | "APPROVED";
export interface DocumentMeta {
  id: number; release_id: number; title: string; doc_type: string;
  status: DocumentStatus; created_at: string;
  version_count: number;
  latest_version_id: number | null;
  latest_version: number | null;
  latest_filename: string | null;
  latest_content_type: string | null;
  latest_size: number | null;
  latest_pdf_size: number | null;
  latest_uploaded_by: string | null;
  updated_at: string | null;
}
export interface DocumentVersionMeta {
  id: number; document_id: number; version: number; filename: string;
  content_type: string; size: number; pdf_size: number;
  uploaded_by: string | null; created_at: string;
}

// --- Workflow (state graph + per-transition RBAC) --------------------------
export interface WorkflowTransition { name: string; target: string; roles: string[]; requires: string[] }
export interface WorkflowState {
  name: string; score: number; is_final: boolean; transitions: WorkflowTransition[];
}
export interface Workflow { initial_state: string; states: WorkflowState[] }

// Payload to replace the whole graph (PUT /api/v1/workflow). State order
// defines scoring, so the first state is the initial one.
export interface WorkflowTransitionInput { name: string; target: string; roles: string[]; requires: string[] }
export interface WorkflowStateInput { name: string; transitions: WorkflowTransitionInput[] }
export interface WorkflowUpdate { states: WorkflowStateInput[] }

// --- Release status summary ------------------------------------------------
export interface ReleaseStatusSummary {
  release_id: number;
  state: string;
  open_bug_count: number;
  open_bugs: Issue[];
  present_doc_types: string[];
  // The approved subset of present_doc_types — what `document:<type>` guards need.
  approved_doc_types: string[];
  is_ready: boolean;
}

// --- Runtime configuration -------------------------------------------------
export interface JiraConfigView { enabled: boolean; base_url: string; token_set: boolean }
export interface GitHubConfigView {
  // The repository is configured per-product (Product.tracker_repo), not here.
  enabled: boolean; base_url: string; token_set: boolean;
}
export interface ClaudeConfigView { model: string; api_key_set: boolean }
export interface OllamaConfigView { base_url: string; model: string }
export interface LLMConfigView {
  provider: "claude" | "ollama";
  claude: ClaudeConfigView;
  ollama: OllamaConfigView;
}
// Git hosting connections. Both may be enabled at once (a product's repos can
// span GitHub and a self-hosted GitLab); the repositories themselves are
// linked per-product.
export interface GitProviderConfigView { enabled: boolean; base_url: string; token_set: boolean }
export interface GitConfigView { github: GitProviderConfigView; gitlab: GitProviderConfigView }
export interface ConfigView {
  tracker_provider: "jira" | "github";
  jira: JiraConfigView;
  github: GitHubConfigView;
  llm: LLMConfigView;
  git: GitConfigView;
}
export interface ConfigUpdate {
  tracker_provider?: "jira" | "github";
  jira_enabled?: boolean; jira_base_url?: string; jira_token?: string;
  github_enabled?: boolean; github_base_url?: string; github_token?: string;
  llm_provider?: "claude" | "ollama";
  claude_model?: string; claude_api_key?: string;
  ollama_base_url?: string; ollama_model?: string;
  git_github_enabled?: boolean; git_github_base_url?: string; git_github_token?: string;
  git_gitlab_enabled?: boolean; git_gitlab_base_url?: string; git_gitlab_token?: string;
}

// --- Audit / history -------------------------------------------------------
export interface AuditEntry {
  id: number; entity_type: string; entity_id: number; action: string;
  old_value: string | null; new_value: string | null;
  operator: string | null; note: string | null; created_at: string;
}

export async function login(username: string, password: string): Promise<string> {
  const { data } = await api.post("/api/v1/user-management/login", { username, password });
  return data.access_token as string;
}

// --- Products / dashboard --------------------------------------------------
export const listProducts = () => api.get<Product[]>("/api/v1/product").then((r) => r.data);
export const getOverview = () =>
  api.get<ProductOverview[]>("/api/v1/product/overview").then((r) => r.data);
export const getProduct = (productId: number) =>
  api.get<Product>(`/api/v1/product/${productId}`).then((r) => r.data);
// The issue-tracker project is optional here, but the backend verifies it exists
// when one is given — a project bound to a repo that isn't there would fail later,
// at the point where a release tries to read its tickets.
export const createProduct = (name: string, tracker_repo = "") =>
  api.post<Product>("/api/v1/product", { name, tracker_repo }).then((r) => r.data);
export const updateProduct = (
  productId: number,
  patch: { name?: string; tracker_repo?: string }
) => api.patch<Product>(`/api/v1/product/${productId}`, patch).then((r) => r.data);
export const deleteProduct = (productId: number) =>
  api.delete(`/api/v1/product/${productId}`).then((r) => r.data);

// --- Releases --------------------------------------------------------------
export const listReleases = (productId: number) =>
  api.get<Release[]>(`/api/v1/product/${productId}/releases`).then((r) => r.data);
// A release is created with the criteria that says which tickets it contains —
// the API requires it, and the UI shows the operator those tickets first.
export const createRelease = (
  product_id: number,
  version: string,
  issue_filter: IssueFilter
) =>
  api.post<Release>("/api/v1/release", { product_id, version, issue_filter }).then((r) => r.data);
export const deleteRelease = (releaseId: number) =>
  api.delete(`/api/v1/release/${releaseId}`).then((r) => r.data);
export const transitionRelease = (releaseId: number, transition: string, note = "") =>
  api
    .post<Release>(`/api/v1/release/${releaseId}/transition`, { transition, note })
    .then((r) => r.data);
export const getReleaseStatus = (releaseId: number) =>
  api.get<ReleaseStatusSummary>(`/api/v1/release/${releaseId}/status`).then((r) => r.data);
export const getReleaseHistory = (releaseId: number) =>
  api.get<AuditEntry[]>(`/api/v1/release/${releaseId}/history`).then((r) => r.data);

// --- Workflow --------------------------------------------------------------
export const getWorkflow = () =>
  api.get<Workflow>("/api/v1/workflow").then((r) => r.data);

// Replace the entire workflow graph (admin only).
export const updateWorkflow = (states: WorkflowStateInput[]) =>
  api.put<Workflow>("/api/v1/workflow", { states }).then((r) => r.data);

// Download the persisted workflow as states.yaml-compatible YAML.
export const exportWorkflowYaml = () =>
  api.get<string>("/api/v1/workflow/export", { responseType: "text" }).then((r) => r.data);

// Known ReleaseIT roles (mirrors backend app.core.jwt_verify).
export const ROLES = ["Developer", "QA Manager", "Release Manager", "Administrator"];

// Readiness guards a transition may require (mirrors backend KNOWN_GUARDS).
export const GUARDS = ["no_open_issues"];

export interface TransitionRoleUpdate { state: string; transition: string; roles: string[] }
export const setTransitionRoles = (overrides: TransitionRoleUpdate[]) =>
  api.put("/api/v1/config/transition-roles", { overrides }).then((r) => r.data);

// --- Configuration ---------------------------------------------------------
export const getConfig = () =>
  api.get<ConfigView>("/api/v1/config").then((r) => r.data);
export const updateConfig = (body: ConfigUpdate) =>
  api.put<ConfigView>("/api/v1/config", body).then((r) => r.data);
// Supported document types (admin-managed on the Configuration page).
export const listDocumentTypes = () =>
  api.get<DocumentType[]>("/api/v1/config/document-types").then((r) => r.data);
export const addDocumentType = (
  name: string,
  kind: DocumentTypeKind = "manual",
  generation_prompt = ""
) =>
  api
    .post<DocumentType>("/api/v1/config/document-types", { name, kind, generation_prompt })
    .then((r) => r.data);
export const updateDocumentType = (
  id: number,
  patch: { name?: string; kind?: DocumentTypeKind; generation_prompt?: string }
) =>
  api.patch<DocumentType>(`/api/v1/config/document-types/${id}`, patch).then((r) => r.data);
export const deleteDocumentType = (id: number) =>
  api.delete(`/api/v1/config/document-types/${id}`).then((r) => r.data);

// --- Document management (versioned) ---------------------------------------
const DOCS = (releaseId: number) => `/api/v1/release/${releaseId}/documents`;

export const listDocuments = (releaseId: number) =>
  api.get<DocumentMeta[]>(DOCS(releaseId)).then((r) => r.data);

// Create a new document from an uploaded file (becomes version 1). The operator
// marks it with a supported type (fixed for all later versions); the title
// defaults to the file name server-side when omitted.
export const uploadDocument = (
  releaseId: number,
  file: File,
  docType: string,
  title?: string
) => {
  const form = new FormData();
  form.append("file", file);
  form.append("doc_type", docType);
  if (title) form.append("title", title);
  return api.post<DocumentMeta>(DOCS(releaseId), form).then((r) => r.data);
};

export const listDocumentVersions = (releaseId: number, documentId: number) =>
  api
    .get<DocumentVersionMeta[]>(`${DOCS(releaseId)}/${documentId}/versions`)
    .then((r) => r.data);

// Upload a new version of an existing document.
export const uploadDocumentVersion = (releaseId: number, documentId: number, file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api
    .post<DocumentMeta>(`${DOCS(releaseId)}/${documentId}/versions`, form)
    .then((r) => r.data);
};

export const deleteDocument = (releaseId: number, documentId: number) =>
  api.delete(`${DOCS(releaseId)}/${documentId}`).then((r) => r.data);

// Approve a document (or return it to draft).
export const setDocumentStatus = (
  releaseId: number,
  documentId: number,
  status: DocumentStatus
) =>
  api
    .patch<DocumentMeta>(`${DOCS(releaseId)}/${documentId}/status`, { status })
    .then((r) => r.data);

// Swap a filename's extension to .pdf for the rendered-PDF download.
const asPdfName = (filename: string) =>
  filename.includes(".") ? filename.replace(/\.[^.]+$/, ".pdf") : `${filename}.pdf`;

// Download a specific version. The endpoint is Bearer-protected, so we fetch it
// as a blob via axios (which attaches the token) and trigger a save in-browser.
// `format: "pdf"` fetches the rendered-PDF companion (Markdown documents only).
export async function downloadDocumentVersion(
  releaseId: number,
  documentId: number,
  versionId: number,
  filename: string,
  format?: "pdf"
) {
  const { data } = await api.get(
    `${DOCS(releaseId)}/${documentId}/versions/${versionId}/content`,
    { responseType: "blob", params: format ? { format } : undefined }
  );
  const url = URL.createObjectURL(data as Blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = format === "pdf" ? asPdfName(filename) : filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// --- Issues (always read live from the ticketing system) -------------------
// There is no sync and no stored issue list: a release stores the criteria that
// says which tickets belong to it, and every read below resolves that criteria
// against the tracker and returns what it says right now.
export const listReleaseIssues = (releaseId: number) =>
  api.get<Issue[]>(`/api/v1/release/${releaseId}/issues`).then((r) => r.data);

// Preview the tickets a criteria selects, before a release exists. This is what
// the operator confirms when creating one.
export const searchIssues = (
  product_id: number,
  mode: IssueFilterMode,
  value: string
) =>
  api
    .post<IssueSearchResult>("/api/v1/release/issues/search", { product_id, mode, value })
    .then((r) => r.data);

// Adding/removing a ticket EDITS THE TICKET in the ticketing system: a ticket is
// in a release because it matches the release's criteria, so adding one means
// making it match (criteria `label = v0.0.1` → the label v0.0.1 is put on the
// ticket) and removing one means making it stop. The result is read back from the
// tracker, so `member` is what the tracker says, not what we hoped.
export interface IssueMembershipResult {
  key: string; member: boolean; criteria: string; total: number; issues: Issue[];
}
export const addIssueToRelease = (releaseId: number, key: string) =>
  api
    .post<IssueMembershipResult>(`/api/v1/release/${releaseId}/issues/add`, { key })
    .then((r) => r.data);
export const removeIssueFromRelease = (releaseId: number, key: string) =>
  api
    .post<IssueMembershipResult>(`/api/v1/release/${releaseId}/issues/remove`, { key })
    .then((r) => r.data);

// Full detail for one issue (description, people, timestamps).
export const getIssueDetail = (releaseId: number, key: string) =>
  api
    .get<IssueDetail>(`/api/v1/release/${releaseId}/issue`, { params: { key } })
    .then((r) => r.data);

// Total bugs in a release, counted over the same tickets the readiness gate
// uses — the release's stored criteria.
export interface ReleaseBugCount { release_id: number; filter: string; total_bugs: number }
export const getReleaseBugCount = (releaseId: number) =>
  api.get<ReleaseBugCount>(`/api/v1/release/${releaseId}/bugs/count`).then((r) => r.data);

// The release's stored criteria. `null` only for releases created before criteria
// were recorded — those fall back to the tracker's native release grouping.
export const getIssueFilter = (releaseId: number) =>
  api.get<IssueFilterView | null>(`/api/v1/release/${releaseId}/issue-filter`).then((r) => r.data);
export const saveIssueFilter = (releaseId: number, mode: IssueFilterMode, value: string) =>
  api
    .put<IssueFilterView>(`/api/v1/release/${releaseId}/issue-filter`, { mode, value })
    .then((r) => r.data);

// --- Product git repositories ------------------------------------------------
// A product's code: one repo per component (component_name matches the umbrella
// Chart.yaml dependency name), libraries (link-only), and exactly one version
// anchor — either the Helm umbrella chart (role "deployment") or, for a simple
// single-repo product, the whole codebase (role "codebase"), tagged with the
// product release version.
export type GitProvider = "github" | "gitlab";
export type GitRepoRole = "component" | "library" | "deployment" | "codebase";
export interface GitRepoLink {
  id: number; product_id: number; provider: GitProvider; repo: string;
  role: GitRepoRole; component_name: string; tag_pattern: string;
  web_url: string; chart_path: string; created_at: string;
}
export interface GitRepoLinkCreate {
  provider: GitProvider; repo: string; role: GitRepoRole;
  component_name?: string; tag_pattern?: string; web_url?: string; chart_path?: string;
}
export const listGitRepos = (productId: number) =>
  api.get<GitRepoLink[]>(`/api/v1/product/${productId}/git-repos`).then((r) => r.data);
export const addGitRepo = (productId: number, body: GitRepoLinkCreate) =>
  api.post<GitRepoLink>(`/api/v1/product/${productId}/git-repos`, body).then((r) => r.data);
export const updateGitRepo = (
  productId: number, linkId: number, patch: Partial<GitRepoLinkCreate>
) =>
  api
    .patch<GitRepoLink>(`/api/v1/product/${productId}/git-repos/${linkId}`, patch)
    .then((r) => r.data);
export const deleteGitRepo = (productId: number, linkId: number) =>
  api.delete(`/api/v1/product/${productId}/git-repos/${linkId}`).then((r) => r.data);

// --- Release code changes (read live from the git hosting) --------------------
export interface CommitView {
  sha: string; short_sha: string; subject: string; author: string; url: string;
  tickets: string[];  // empty = unmapped (reported, never guessed)
}
export type ComponentChangeStatus = "changed" | "added" | "removed" | "unchanged" | "error";
export interface ComponentChange {
  name: string; repo_id: number | null; repo: string; provider: string;
  web_url: string;
  old_version: string | null; new_version: string | null;
  status: ComponentChangeStatus;
  error: string;         // why the component's diff could not be produced
  compare_url: string;
  commit_count: number; commits_truncated: boolean; commits: CommitView[];
  mapped_count: number; unmapped_count: number;
}
export interface UnmatchedDependency {
  name: string; old_version: string | null; new_version: string | null;
}
export interface ReleaseChanges {
  release_id: number; version: string;
  previous_release_id: number | null; previous_version: string | null;
  // "umbrella": Chart.yaml diffed between release tags, then each service.
  // "single-repo": the one codebase repo diffed directly between release tags.
  mode: "umbrella" | "single-repo";
  // The anchor repo: the umbrella chart, or the codebase repo in single-repo mode.
  umbrella_repo: string; umbrella_provider: string;
  old_tag: string | null; new_tag: string | null;
  baseline_missing: string;  // why there is no baseline ("" when there is one)
  components: ComponentChange[];
  unmatched_dependencies: UnmatchedDependency[];
  library_repos: GitRepoLink[];
}
export const getReleaseChanges = (releaseId: number) =>
  api.get<ReleaseChanges>(`/api/v1/release/${releaseId}/changes`).then((r) => r.data);
// Run the advisory AI code review; the report lands as a DRAFT
// "Code Review Report" document on the release. Slow (one LLM pass per
// changed component).
export const runCodeReview = (releaseId: number) =>
  api.post<DocumentMeta>(`/api/v1/release/${releaseId}/code-review`).then((r) => r.data);

// --- LLM assistant (chat) --------------------------------------------------
export interface ChatMessage { role: "user" | "assistant"; content: string }
export interface ChatAction { tool: string; ok: boolean; summary: string }
export interface ChatDocumentRef {
  release_id: number; document_id: number; version_id: number | null;
  title: string; doc_type: string; status: DocumentStatus;
  filename: string; has_pdf: boolean;
}
export interface ChatResponse {
  reply: string; actions: ChatAction[]; documents: ChatDocumentRef[];
  // Attachments the assistant linked to a document this turn — they are spent,
  // so the client stops sending them.
  linked_attachment_ids: number[];
}

// A file the operator attached in the chat. It is staged server-side and shown
// to the assistant as metadata only; it reaches a release only once the
// assistant links it to a document (after confirming with the operator).
export interface ChatAttachment {
  id: number; filename: string; content_type: string; size: number;
}
export const uploadChatAttachment = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api.post<ChatAttachment>("/api/v1/chat/attachments", form).then((r) => r.data);
};

// Send the full conversation so far, plus the ids of any attached files not yet
// linked; the backend runs the agentic tool loop and returns the assistant's
// reply plus the actions it performed. Stateless: the client owns the transcript.
export const sendChat = (messages: ChatMessage[], attachmentIds: number[] = []) =>
  api
    .post<ChatResponse>("/api/v1/chat", { messages, attachment_ids: attachmentIds })
    .then((r) => r.data);

// What the assistant can do — its actions (from the live tool registry) and
// ready-to-use prompt templates for its main jobs.
export interface AssistantAction { name: string; kind: "read" | "action"; description: string }
export interface AssistantPrompt { key: string; title: string; description: string; prompt: string }
export interface AssistantCapabilities { actions: AssistantAction[]; prompts: AssistantPrompt[] }
export const getAssistantCapabilities = () =>
  api.get<AssistantCapabilities>("/api/v1/chat/capabilities").then((r) => r.data);

// Admin-editable assistant prompts. The full desired state is sent; the backend
// stores only what differs from the built-in defaults (so an unchanged prompt
// keeps tracking the default) and returns the resulting effective prompts.
export const updateAssistantPrompts = (prompts: AssistantPrompt[]) =>
  api.put<AssistantPrompt[]>("/api/v1/config/prompts", { prompts }).then((r) => r.data);

// --- User management (admin only; served by the auth service) --------------
export interface User {
  id: number; username: string; email: string | null;
  created_at: string; roles: string[];
}
const UM = "/api/v1/user-management";
export const listUsers = () => api.get<User[]>(`${UM}/users`).then((r) => r.data);
export const createUser = (body: {
  username: string; password: string; email?: string; roles: string[];
}) => api.post<User>(`${UM}/users`, body).then((r) => r.data);
export const updateUser = (
  userId: number,
  patch: { email?: string; roles?: string[] }
) => api.put<User>(`${UM}/users/${userId}`, patch).then((r) => r.data);
export const deleteUser = (userId: number) =>
  api.delete(`${UM}/users/${userId}`).then((r) => r.data);

// --- Current user (decoded from the JWT; backend remains the enforcer) ------
export interface CurrentUser { subject: string; roles: string[] }

function base64UrlDecode(segment: string): string {
  const padded = segment.replace(/-/g, "+").replace(/_/g, "/");
  return atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
}

// Decode the stored access token's claims to drive UI gating only — the token
// is verified server-side, so this is purely for showing the right controls.
export function currentUser(): CurrentUser | null {
  const token = getToken();
  if (!token) return null;
  try {
    const [, payload] = token.split(".");
    const claims = JSON.parse(base64UrlDecode(payload));
    const raw = claims.roles ?? [];
    const roles = Array.isArray(raw) ? raw : [raw];
    return { subject: String(claims.sub ?? ""), roles };
  } catch {
    return null;
  }
}
