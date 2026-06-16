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

// --- Typed API helpers -----------------------------------------------------
export interface Product { id: number; name: string; solution_id: number | null }
export interface Release {
  id: number; product_id: number; version: string; state: string;
  short_description: string; parent_release_id: number | null;
}
export interface ProductOverview extends Product {
  release_count: number;
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

// --- Releases --------------------------------------------------------------
export const listReleases = (productId: number) =>
  api.get<Release[]>(`/api/v1/product/${productId}/releases`).then((r) => r.data);
export const createRelease = (product_id: number, version: string) =>
  api.post<Release>("/api/v1/release", { product_id, version }).then((r) => r.data);
export const transitionRelease = (releaseId: number, transition: string) =>
  api.post<Release>(`/api/v1/release/${releaseId}/transition`, { transition }).then((r) => r.data);

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
  filter: { release_label?: string; jql?: string }
) => api.post<JiraIssue[]>(`/api/v1/release/${releaseId}/jira/sync`, filter).then((r) => r.data);

// --- Environments ----------------------------------------------------------
export const listEnvironments = () =>
  api.get<Environment[]>("/api/v1/environment").then((r) => r.data);
