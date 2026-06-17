# 3. Frontend Authentication and Role Separation

## Objective

Implement frontend authentication flow with login pages, token management, protected routes, role-based access control, and session expiry handling on the Next.js application.

## Prerequisites

- Phase 2 (backend auth) complete — auth endpoints working, tests passing
- Backend running locally or in Docker
- Phase 1 (baseline audit) complete — frontend builds cleanly

## Detailed Steps

### Step 1: Create AuthContext provider
- **Action:** Build a React context that manages authentication state across the app.
- **Files:** `services/frontend/src/contexts/AuthContext.tsx` (new), `services/frontend/src/lib/auth.ts` (new)
- **Details:**

  **`auth.ts`** — Pure auth utility functions (no React):
  ```typescript
  export interface AuthUser {
    id: string;
    email: string;
    name: string;
    role: 'admin' | 'student' | 'professor';
    is_active: boolean;
    created_at: string;
  }

  export interface LoginCredentials {
    email: string;
    password: string;
  }

  export interface TokenPair {
    access_token: string;
    refresh_token: string;
    token_type: string;
  }

  export async function login(credentials: LoginCredentials): Promise<{ user: AuthUser; tokens: TokenPair }> {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(credentials),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Login failed' }));
      throw new Error(err.detail);
    }
    const data = await res.json();
    // Store tokens
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    return { user: data.user, tokens: data };
  }

  export async function refreshTokens(): Promise<TokenPair> {
    const refreshToken = localStorage.getItem('refresh_token');
    if (!refreshToken) throw new Error('No refresh token');
    const res = await fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!res.ok) throw new Error('Refresh failed');
    const data = await res.json();
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    return data;
  }

  export function logout(): void {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
  }

  export function getAccessToken(): string | null {
    return localStorage.getItem('access_token');
  }
  ```

  **`AuthContext.tsx`** — React context with provider:
  - State: `user` (AuthUser | null), `isLoading` (boolean, true while checking stored token on mount)
  - Methods: `login(credentials)`, `logout()`
  - On mount: check if `access_token` exists in localStorage, call `GET /auth/me` to validate it. If valid, set user. If 401, try `refreshTokens()`. If refresh also fails, clear tokens and set user to null.
  - `isAuthenticated`: derived from `user !== null`
  - Export `useAuth()` hook that reads the context and throws if used outside provider.

### Step 2: Update api.ts with auth interceptor
- **Action:** Modify the existing API client to automatically attach the JWT access token and handle 401 globally.
- **Files:** `services/frontend/src/lib/api.ts`
- **Details:**
  - Create a new `apiRequest()` function (parallel to the existing `request()`) that:
    1. Reads `access_token` from localStorage.
    2. Attaches `Authorization: Bearer <token>` header.
    3. On 401 response, attempts token refresh (`POST /auth/refresh`).
    4. If refresh succeeds, retry the original request with the new token.
    5. If refresh fails, clear auth state and redirect to `/login?expired=true`.
  - Keep the existing `request()` function for backward compatibility during migration, but mark it as deprecated.
  - Create a new `adminRequest()` variant that checks for admin role and redirects to `/` if user is not admin after getting a 403.
  - Update all existing API functions to use the new auth-aware request function. For admin endpoints that currently use `X-Admin-Key`, replace with the new JWT-based calls.

### Step 3: Create login pages
- **Action:** Build login UI for students and a separate admin login page.
- **Files:**
  - `services/frontend/src/app/login/page.tsx` (new)
  - `services/frontend/src/app/admin/login/page.tsx` (new)
- **Details:**

  **Student login (`/login`):**
  - Form with email input, password input, submit button, "Iniciar sesión" text.
  - Client-side validation: email format, password non-empty.
  - On submit: call `auth.login()`, on success redirect to `/`.
  - On error: show error message (e.g., "Email o contraseña incorrectos").
  - Link to `/register` if registration is implemented.
  - If URL has `?expired=true` query param, show toast "Tu sesión ha expirado. Inicia sesión de nuevo."
  - Use existing UI components (shadcn/ui style). The project has `@radix-ui/react-label` and `lucide-react` already.

  **Admin login (`/admin/login`):**
  - Same form but styled differently with an "Admin" header.
  - On success, redirect to `/admin`.
  - If user is already authenticated (check on mount), redirect immediately to `/admin`.
  - Subtle "Only administrators" label below the heading.

### Step 4: Implement ProtectedRoute component
- **Action:** Create a wrapper component that checks authentication and role.
- **Files:** `services/frontend/src/components/auth/ProtectedRoute.tsx` (new), `services/frontend/src/components/auth/AdminRoute.tsx` (new)
- **Details:**

  **`ProtectedRoute`:**
  - Props: `requiredRole?: 'admin' | 'student'`
  - If `isLoading`: show a full-page spinner or skeleton.
  - If not `isAuthenticated`: redirect to `/login?redirect={currentPath}`.
  - If `requiredRole` is specified and user's role doesn't match: show a 403 page with "No tienes permiso para acceder a esta página" and a "Volver al inicio" link. Do NOT redirect (avoid redirect loops).
  - Wraps `{children}` when all checks pass.

  **`AdminRoute`:**
  - Convenience wrapper: `<ProtectedRoute requiredRole="admin">`.
  - Used in admin layout to protect all admin pages.

### Step 5: Update admin layout with auth guard
- **Action:** Wrap the admin layout with `AdminRoute` to protect all admin pages.
- **Files:** `services/frontend/src/app/admin/layout.tsx`
- **Details:**
  - Import `AdminRoute` and wrap `{children}`.
  - This ensures every page under `/admin/*` requires authentication and admin role.
  - Add a sidebar or top bar with user name, role badge, and logout button for the admin area.
  - The admin layout currently exists at `services/frontend/src/app/admin/layout.tsx` — read it first to modify, don't overwrite.

### Step 6: App layout wrap with AuthProvider
- **Action:** Wrap the root layout with the AuthContext provider.
- **Files:** `services/frontend/src/app/layout.tsx`
- **Details:**
  - Since this is a server component layout (Next.js App Router), you cannot use a client-side context provider directly in `layout.tsx`.
  - Create a client wrapper: `services/frontend/src/components/auth/AuthProviderWrapper.tsx`:

    ```tsx
    'use client';
    import { AuthProvider } from '@/contexts/AuthContext';
    export default function AuthProviderWrapper({ children }: { children: React.ReactNode }) {
      return <AuthProvider>{children}</AuthProvider>;
    }
    ```

  - In `layout.tsx`, wrap the `{children}` with `<AuthProviderWrapper>`.
  - Keep the existing `<Toaster>` component inside the wrapper so toasts work from auth context.
  - Remove `NEXT_PUBLIC_ADMIN_KEY` from the layout and from any server-side props.

### Step 7: Handle session expiry globally
- **Action:** Ensure that when any API call returns a 401, the frontend handles it gracefully.
- **Files:** `services/frontend/src/lib/api.ts`, `services/frontend/src/lib/auth.ts`
- **Details:**
  - Create an event-based mechanism: when token refresh fails, emit a custom event `auth:expired`.
  - In `AuthContext`, listen for `auth:expired` and automatically log out and redirect.
  - Alternative simpler approach: after a failed refresh, call `logout()` and `window.location.href = '/login?expired=true'`.
  - Show a sonner toast: "Tu sesión ha expirado. Inicia sesión de nuevo."
  - Ensure this does NOT create an infinite redirect loop (check that we're not already on `/login` before redirecting).

### Step 8: Update README with auth migration notes
- **Action:** Document the authentication implementation.
- **Files:** `README.md`
- **Details:**
  - Update the "Open Items" table: mark item 5 (Admin portal auth) and item 6 (Student auth) as "Done".
  - Add a section on authentication flow.
  - Note that `X-Admin-Key` is deprecated and will be removed.

## Acceptance Criteria

- [ ] Login page at `/login` accepts email/password and redirects to `/` on success.
- [ ] Admin login at `/admin/login` redirects to `/admin` on success.
- [ ] Unauthenticated users accessing `/admin/*` are redirected to `/admin/login`.
- [ ] Authenticated student users accessing `/admin/*` see a 403 page.
- [ ] Token refresh works transparently when access token expires.
- [ ] When refresh fails, user is logged out and redirected to `/login?expired=true`.
- [ ] `Logout` clears tokens and redirects to `/login`.
- [ ] Loading state (spinner/skeleton) shows while checking auth on page load.
- [ ] All admin API calls use Bearer token instead of `X-Admin-Key`.
- [ ] Auth state persists across page refreshes (tokens in localStorage).
- [ ] `npm run build` succeeds with no TypeScript errors.

## Risks & Notes

- **localStorage vs httpOnly cookies:** localStorage is simpler but vulnerable to XSS. The backend can set httpOnly cookies in the future without frontend changes if we use the `Set-Cookie` header. For now, localStorage is acceptable. Document this tradeoff.
- **Next.js App Router and client contexts:** Auth context must be a client component. The wrapper pattern (`AuthProviderWrapper`) ensures we don't have to convert the root layout to 'use client'.
- **Server-side rendering:** Protected routes that fetch data server-side (e.g., admin dashboard) need to pass the auth token from client to server. Use cookies for server-side auth checks or make those pages client-rendered.
- **Token refresh race condition:** If multiple API calls happen simultaneously and all get 401, multiple refresh attempts could occur. Implement a simple mutex/lock in the API client: while a refresh is in progress, queue other 401 retries. After refresh completes, retry all queued requests. If refresh fails, reject all.
- **Admin layout already exists:** Read `services/frontend/src/app/admin/layout.tsx` before modifying to ensure we don't break existing admin navigation.

## Dependencies

- Backend auth endpoints from Phase 2 (`/auth/login`, `/auth/refresh`, `/auth/me`)
- No additional npm packages required (fetch, localStorage, React context are all built-in)
- `sonner` already in package.json for toast notifications
