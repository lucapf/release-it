import { notifications } from "@mantine/notifications";

// Turn an axios/API error into a short, human-friendly message. The raw backend
// `detail` is only surfaced for client errors that are meaningful to the user
// (e.g. 409 "transition not allowed"); infrastructure-level failures get a
// plain-language message instead of leaking internals like JWT key IDs.
export function apiErrorMessage(error: any, fallback = "Something went wrong. Please try again."): string {
  const status: number | undefined = error?.response?.status;

  if (error?.sessionExpired || status === 401)
    return "Your session has expired. Please sign in again.";
  if (status === 403)
    return "You don't have permission to perform this action.";
  if (status === 413)
    return "That file is too large to upload.";
  if (status && status >= 500)
    return "The server hit an error. Please try again in a moment.";
  if (error?.code === "ERR_NETWORK" || (error?.request && !error?.response))
    return "Can't reach the server. Check your connection and try again.";

  const detail = error?.response?.data?.detail;
  return typeof detail === "string" && detail ? detail : fallback;
}

// Show a red notification for an API error. Session-expiry (401) is suppressed
// here because it's handled globally (sign-out + redirect + a single notice),
// so individual handlers don't double-report it.
export function notifyApiError(error: any, fallback?: string) {
  if (error?.sessionExpired) return;
  notifications.show({ message: apiErrorMessage(error, fallback), color: "red" });
}
