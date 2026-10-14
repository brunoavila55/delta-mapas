let csrf = "";
let epoch = 0;
export function setSession(token: string) {
  csrf = token;
}
export function clearSession() {
  csrf = "";
  epoch++;
}
export function sessionEpoch() {
  return epoch;
}
export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const requestEpoch = epoch;
  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type"))
    headers.set("Content-Type", "application/json");
  if (csrf) headers.set("X-CSRF-Token", csrf);
  const response = await fetch(path, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  const data = await response.json().catch(() => ({}));
  if (requestEpoch !== epoch)
    throw new Error("A sessão foi alterada. Entre novamente.");
  if (!response.ok) {
    if (
      response.status === 401 &&
      !["/api/login", "/api/register"].includes(path)
    ) {
      const hadSession = headers.has("X-CSRF-Token");
      clearSession();
      if (hadSession) window.dispatchEvent(new Event("session-expired"));
    }
    throw new Error(
      data.error ||
        `Não foi possível concluir a operação (${response.status}).`,
    );
  }
  return data as T;
}
