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
  id: number; name: string; solution_id: number | null; tracker_repo: string;
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
export interface JiraIssue {
  id: number; release_id: number; issue_key: string;
  issue_type: string; summary: string; status: string;
  // The issue's page in the tracker's web UI; empty for issues cached before
  // the URL was recorded (they get one on the next sync).
  url: string;
  synced_at: string;
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
export interface DocumentType { id: number; name: string; created_at: string }

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
  open_bugs: JiraIssue[];
  present_doc_types: string[];
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
export interface ConfigView {
  tracker_provider: "jira" | "github";
  // Scheduled issue sync interval in minutes (0 = disabled). Default: 10.
  sync_interval_minutes: number;
  jira: JiraConfigView;
  github: GitHubConfigView;
  llm: LLMConfigView;
}
export interface ConfigUpdate {
  tracker_provider?: "jira" | "github";
  sync_interval_minutes?: number;
  jira_enabled?: boolean; jira_base_url?: string; jira_token?: string;
  github_enabled?: boolean; github_base_url?: string; github_token?: string;
  llm_provider?: "claude" | "ollama";
  claude_model?: string; claude_api_key?: string;
  ollama_base_url?: string; ollama_model?: string;
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
export const createProduct = (name: string) =>
  api.post<Product>("/api/v1/product", { name }).then((r) => r.data);
export const updateProduct = (
  productId: number,
  patch: { name?: string; tracker_repo?: string }
) => api.patch<Product>(`/api/v1/product/${productId}`, patch).then((r) => r.data);
export const deleteProduct = (productId: number) =>
  api.delete(`/api/v1/product/${productId}`).then((r) => r.data);

// --- Releases --------------------------------------------------------------
export const listReleases = (productId: number) =>
  api.get<Release[]>(`/api/v1/product/${productId}/releases`).then((r) => r.data);
export const createRelease = (product_id: number, version: string) =>
  api.post<Release>("/api/v1/release", { product_id, version }).then((r) => r.data);
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
export const addDocumentType = (name: string) =>
  api.post<DocumentType>("/api/v1/config/document-types", { name }).then((r) => r.data);
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

// --- Jira integration ------------------------------------------------------
export const listJiraIssues = (releaseId: number) =>
  api.get<JiraIssue[]>(`/api/v1/release/${releaseId}/jira/issues`).then((r) => r.data);
export const syncJira = (
  releaseId: number,
  filter: { release_label?: string; jql?: string; milestone?: string }
) => api.post<JiraIssue[]>(`/api/v1/release/${releaseId}/jira/sync`, filter).then((r) => r.data);
// Full detail for one issue, fetched from the tracker on demand (not cached).
export const getIssueDetail = (releaseId: number, key: string) =>
  api
    .get<IssueDetail>(`/api/v1/release/${releaseId}/jira/issue`, { params: { key } })
    .then((r) => r.data);

// Total bugs in a release, counted live from the active tracker by the release
// label v<major>.<minor>.<patch> (e.g. v0.0.1).
export interface ReleaseBugCount { release_id: number; label: string; total_bugs: number }
export const getReleaseBugCount = (releaseId: number) =>
  api.get<ReleaseBugCount>(`/api/v1/release/${releaseId}/bugs/count`).then((r) => r.data);

// Saved per-release tracker filter (milestone | label | jql), applied automatically.
export interface SyncFilter { release_id: number; mode: string; value: string; updated_at: string }
export const getSyncFilter = (releaseId: number) =>
  api.get<SyncFilter | null>(`/api/v1/release/${releaseId}/sync-filter`).then((r) => r.data);
export const saveSyncFilter = (releaseId: number, mode: string, value: string) =>
  api.put<SyncFilter>(`/api/v1/release/${releaseId}/sync-filter`, { mode, value }).then((r) => r.data);

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
}

// Send the full conversation so far; the backend runs the agentic tool loop and
// returns the assistant's reply plus the actions it performed. Stateless: the
// client owns the transcript.
export const sendChat = (messages: ChatMessage[]) =>
  api.post<ChatResponse>("/api/v1/chat", { messages }).then((r) => r.data);

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
