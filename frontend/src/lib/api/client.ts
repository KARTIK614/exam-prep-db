import { ApiError, type ApiErrorEnvelope } from './types';
import { useAuthStore } from '@/stores/authStore';

/**
 * Thin `fetch` wrapper for the Rust API.
 *
 * Responsibilities:
 *   1. Prepend `VITE_API_URL` to relative paths (empty in same-origin dev).
 *   2. Attach the current access token as `Authorization: Bearer …`.
 *   3. On 401: attempt exactly one silent refresh, retry the original
 *      request, and on failure clear the auth store + redirect to /login.
 *   4. Parse the standard error envelope (`{error: {code, message, ...}}`)
 *      and throw a typed `ApiError` for anything non-2xx.
 *
 * Notes:
 *   - We don't use openapi-fetch yet (R3 §8 recommends it once the Rust
 *     backend publishes an OpenAPI spec). Hand-rolled `fetch` keeps the
 *     dependency surface minimal for Phase 8.
 *   - The refresh path is deliberately *inside* the client, not a hook,
 *     so any caller (including query loaders and mutation callbacks)
 *     benefits.
 */

const API_BASE: string = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '');

/** In-flight refresh promise — coalesces concurrent 401s. */
let refreshInFlight: Promise<boolean> | null = null;

interface ApiRequestOptions extends Omit<RequestInit, 'body'> {
  /** JSON body — will be `JSON.stringify`'d and `Content-Type` set. */
  body?: unknown;
  /** When true, do NOT attach the auth header (login/register/refresh). */
  skipAuth?: boolean;
  /** When true, do NOT attempt refresh on 401 (used by the refresh call itself). */
  skipRefresh?: boolean;
}

function joinUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  if (!API_BASE) return path;
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
}

async function parseError(response: Response): Promise<ApiError> {
  const status = response.status;
  const requestId = response.headers.get('x-request-id');
  try {
    const body = (await response.json()) as ApiErrorEnvelope | undefined;
    if (body && typeof body === 'object' && 'error' in body && body.error) {
      return new ApiError(
        status,
        body.error.code ?? 'unknown',
        body.error.message ?? response.statusText,
        body.error.request_id ?? requestId,
      );
    }
  } catch {
    // Fall through — server sent a non-JSON error.
  }
  return new ApiError(status, 'unknown', response.statusText || 'request failed', requestId);
}

/**
 * Attempt to refresh tokens using the stored refresh token. Returns true on
 * success (new tokens are already written to the auth store), false on
 * failure (tokens are cleared).
 *
 * De-duplicates concurrent callers via a module-level in-flight promise.
 */
async function tryRefresh(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;

  const doRefresh = async (): Promise<boolean> => {
    const refreshToken = useAuthStore.getState().refreshToken;
    if (!refreshToken) return false;

    try {
      const response = await fetch(joinUrl('/api/v1/auth/refresh'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!response.ok) return false;
      const data = (await response.json()) as {
        access_token: string;
        refresh_token: string;
      };
      useAuthStore.getState().setTokens({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
      });
      return true;
    } catch {
      return false;
    }
  };

  refreshInFlight = doRefresh().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

/** Force logout: clear the store and route to /login. */
function forceLogout(): void {
  useAuthStore.getState().clear();
  // Router-agnostic redirect. Using location.assign keeps history clean.
  if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.assign(`/login?next=${next}`);
  }
}

/**
 * Core request function. Generic over the response type. Returns
 * `undefined` on 204 No Content, otherwise parses JSON.
 */
export async function apiRequest<T>(
  path: string,
  opts: ApiRequestOptions = {},
): Promise<T> {
  const { body, skipAuth, skipRefresh, headers, ...rest } = opts;

  const finalHeaders = new Headers(headers);
  if (body !== undefined && !finalHeaders.has('Content-Type')) {
    finalHeaders.set('Content-Type', 'application/json');
  }
  if (!skipAuth) {
    const token = useAuthStore.getState().accessToken;
    if (token) finalHeaders.set('Authorization', `Bearer ${token}`);
  }

  const init: RequestInit = {
    ...rest,
    headers: finalHeaders,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  };

  let response = await fetch(joinUrl(path), init);

  // 401 → try refresh once, then retry the original request once.
  if (response.status === 401 && !skipAuth && !skipRefresh) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      const retryHeaders = new Headers(headers);
      if (body !== undefined && !retryHeaders.has('Content-Type')) {
        retryHeaders.set('Content-Type', 'application/json');
      }
      const retryToken = useAuthStore.getState().accessToken;
      if (retryToken) retryHeaders.set('Authorization', `Bearer ${retryToken}`);
      response = await fetch(joinUrl(path), {
        ...rest,
        headers: retryHeaders,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
      if (response.status === 401) {
        forceLogout();
        throw await parseError(response);
      }
    } else {
      forceLogout();
      throw await parseError(response);
    }
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  // 204 No Content — nothing to parse.
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, opts?: Omit<ApiRequestOptions, 'body' | 'method'>) =>
    apiRequest<T>(path, { ...opts, method: 'GET' }),
  post: <T>(path: string, body?: unknown, opts?: Omit<ApiRequestOptions, 'body' | 'method'>) =>
    apiRequest<T>(path, { ...opts, method: 'POST', body }),
  patch: <T>(path: string, body?: unknown, opts?: Omit<ApiRequestOptions, 'body' | 'method'>) =>
    apiRequest<T>(path, { ...opts, method: 'PATCH', body }),
  put: <T>(path: string, body?: unknown, opts?: Omit<ApiRequestOptions, 'body' | 'method'>) =>
    apiRequest<T>(path, { ...opts, method: 'PUT', body }),
  delete: <T>(path: string, opts?: Omit<ApiRequestOptions, 'body' | 'method'>) =>
    apiRequest<T>(path, { ...opts, method: 'DELETE' }),
};
