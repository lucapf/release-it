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
export interface Environment { id: number; name: string; description: string }
export interface DocumentationMeta {
  id: number; release_id: number; name: string;
  content_type: string; is_draft: boolean; created_at: string;
}
export interface JiraIssue {
  id: number; release_id: number; issue_key: string;
  issue_type: string; summary: string; status: string; synced_at: string;
}

// --- Workflow (state graph + per-transition RBAC) --------------------------
export interface WorkflowTransition { name: string; target: string; roles: string[] }
export interface WorkflowState {
  name: string; score: number; is_final: boolean; transitions: WorkflowTransition[];
}
export interface Workflow { initial_state: string; states: WorkflowState[] }

// --- Release status summary ------------------------------------------------
export interface RequiredDoc { label: string; present: boolean }
export interface ReleaseStatusSummary {
  release_id: number;
  state: string;
  open_bug_count: number;
  open_bugs: JiraIssue[];
  required_docs: RequiredDoc[];
  missing_docs: string[];
  pending_checks: number;
  total_checks: number;
  is_ready: boolean;
}

// --- Checks ----------------------------------------------------------------
export type Phase = "pre" | "post";
export interface Check {
  id: number; release_id: number; label: string;
  phase: Phase; done: boolean; created_at: string;
}
export interface CheckTemplate { id: number; label: string; phase: Phase; created_at: string }

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
  jira: JiraConfigView;
  github: GitHubConfigView;
  llm: LLMConfigView;
}
export interface ConfigUpdate {
  tracker_provider?: "jira" | "github";
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
  operator: string | null; created_at: string;
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
export const updateProduct = (productId: number, tracker_repo: string) =>
  api.patch<Product>(`/api/v1/product/${productId}`, { tracker_repo }).then((r) => r.data);

// --- Releases --------------------------------------------------------------
export const listReleases = (productId: number) =>
  api.get<Release[]>(`/api/v1/product/${productId}/releases`).then((r) => r.data);
export const createRelease = (product_id: number, version: string) =>
  api.post<Release>("/api/v1/release", { product_id, version }).then((r) => r.data);
export const transitionRelease = (releaseId: number, transition: string) =>
  api.post<Release>(`/api/v1/release/${releaseId}/transition`, { transition }).then((r) => r.data);
export const getReleaseStatus = (releaseId: number) =>
  api.get<ReleaseStatusSummary>(`/api/v1/release/${releaseId}/status`).then((r) => r.data);
export const getReleaseHistory = (releaseId: number) =>
  api.get<AuditEntry[]>(`/api/v1/release/${releaseId}/history`).then((r) => r.data);

// --- Per-release checks ----------------------------------------------------
export const listChecks = (releaseId: number) =>
  api.get<Check[]>(`/api/v1/release/${releaseId}/checks`).then((r) => r.data);
export const addCheck = (releaseId: number, label: string, phase: Phase) =>
  api.post<Check>(`/api/v1/release/${releaseId}/checks`, { label, phase }).then((r) => r.data);
export const setCheckDone = (checkId: number, done: boolean) =>
  api.patch<Check>(`/api/v1/release/checks/${checkId}`, { done }).then((r) => r.data);
export const deleteCheck = (checkId: number) =>
  api.delete(`/api/v1/release/checks/${checkId}`).then((r) => r.data);

// --- Workflow --------------------------------------------------------------
export const getWorkflow = () =>
  api.get<Workflow>("/api/v1/workflow").then((r) => r.data);

// Known ReleaseIT roles (mirrors backend app.core.jwt_verify).
export const ROLES = ["Developer", "QA Manager", "Release Manager", "Administrator"];

export interface TransitionRoleUpdate { state: string; transition: string; roles: string[] }
export const setTransitionRoles = (overrides: TransitionRoleUpdate[]) =>
  api.put("/api/v1/config/transition-roles", { overrides }).then((r) => r.data);

// --- Configuration ---------------------------------------------------------
export const getConfig = () =>
  api.get<ConfigView>("/api/v1/config").then((r) => r.data);
export const updateConfig = (body: ConfigUpdate) =>
  api.put<ConfigView>("/api/v1/config", body).then((r) => r.data);
export const listCheckTemplates = () =>
  api.get<CheckTemplate[]>("/api/v1/config/check-templates").then((r) => r.data);
export const addCheckTemplate = (label: string, phase: Phase) =>
  api.post<CheckTemplate>("/api/v1/config/check-templates", { label, phase }).then((r) => r.data);
export const deleteCheckTemplate = (id: number) =>
  api.delete(`/api/v1/config/check-templates/${id}`).then((r) => r.data);

// --- Documentation ---------------------------------------------------------
export const listDocumentation = (releaseId: number) =>
  api.get<DocumentationMeta[]>(`/api/v1/release/${releaseId}/documentation`).then((r) => r.data);
export const addDocumentation = (releaseId: number, filename: string, text: string) => {
  // Reuses the multipart UploadFile endpoint by wrapping the text as a file.
  const form = new FormData();
  form.append("file", new Blob([text], { type: "text/markdown" }), filename);
  return api
    .post<DocumentationMeta>(`/api/v1/release/${releaseId}/documentation`, form)
    .then((r) => r.data);
};
export const generateReleaseNotes = (releaseId: number) =>
  api
    .post<DocumentationMeta>(`/api/v1/release/${releaseId}/release-notes/generate`)
    .then((r) => r.data);

// --- Jira integration ------------------------------------------------------
export const listJiraIssues = (releaseId: number) =>
  api.get<JiraIssue[]>(`/api/v1/release/${releaseId}/jira/issues`).then((r) => r.data);
export const syncJira = (
  releaseId: number,
  filter: { release_label?: string; jql?: string; milestone?: string }
) => api.post<JiraIssue[]>(`/api/v1/release/${releaseId}/jira/sync`, filter).then((r) => r.data);

// --- Environments ----------------------------------------------------------
export const listEnvironments = () =>
  api.get<Environment[]>("/api/v1/environment").then((r) => r.data);

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
