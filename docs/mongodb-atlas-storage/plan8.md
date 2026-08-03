# MongoDB Atlas Storage Phase 6: Client UI And Boot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let local users save/connect/disconnect/migrate Atlas storage from
Settings, show read-only cloud status in deploy mode, and connect/hydrate cloud
settings exactly once before application render.

**Architecture:** Mongo URI/database remain under one browser-only localStorage
key. Boot requests status, conditionally connects, hydrates provider/search
settings from Mongo, then renders app. A serialized settings-change listener
writes complete snapshots back to Mongo while active. UI follows existing
collapsible Settings card language and Cyber Yellow action hierarchy.

**Tech Stack:** React 19, TypeScript strict mode, Axios, Testing Library,
Vitest, existing Tailwind 4/lucide-react patterns.

**Source references:** `docs/mongodb-atlas-storage/goal.md` and
`docs/mongodb-atlas-storage/research.md`, especially boot and Settings flows.
Follow root `AGENTS.md`; referenced `.planning/codebase/*` files were absent.

**Command note:** For multiline `powershell` blocks, join wrapped lines into one
line and omit display-only trailing `\` characters. `bash` blocks use `\` as
normal shell continuation.

---

## UI Direction

Preserve existing Settings visual system instead of introducing new typography
or page chrome. New section uses `Database` icon, current Cyber Yellow accent,
and one compact vertical connection rail: status badge -> target fields ->
actions -> migration result. This rail makes storage state legible without a
generic dashboard card grid. On mobile actions wrap into full-width buttons;
cloud mode removes secret inputs and destructive controls entirely.

Copy uses user-recognizable actions: `Save connection`, `Connect`,
`Disconnect`, `Migrate local data`. Errors state corrective action and use
`role="alert"`; status uses `role="status"`.

## Scope And File Map

| File | Responsibility |
|------|----------------|
| `client/src/types/storage.ts` | Storage API contracts |
| `client/src/lib/mongoStorageSettings.ts` | Browser URI/database persistence |
| `client/src/lib/storageApi.ts` | Storage REST calls |
| `client/src/lib/storageBoot.ts` | Boot-once connect/hydrate/write-through |
| `client/src/lib/startApplication.ts` | Await boot before invoking renderer |
| `client/src/lib/providerSettings.ts` | Emit settings-change event |
| `client/src/features/settings/StorageSettingsPanel.tsx` | Local/cloud controls |
| `client/src/features/settings/SettingsPage.tsx` | Mount Storage section |
| `client/src/main.tsx` | Await bounded storage boot before render |
| Co-located `*.test.ts(x)` | Unit/component tests |

Every new `.ts`/`.tsx` file requires mandatory `AGENTS.md` header. Existing
files need refreshed header only if changed by more than 30 percent. Match each
file's existing quote/indent style; do not reformat unrelated code.

## Task 1: Browser-Only Mongo Connection Settings

**Files:**
- Create: `client/src/lib/mongoStorageSettings.ts`
- Create: `client/src/lib/mongoStorageSettings.test.ts`

- [ ] **Step 1: Write failing safe-parse tests**

Create test file with mandatory TypeScript header:

```ts
import {
  clearMongoStorageSettings,
  getMongoStorageSettings,
  setMongoStorageSettings,
} from '@/lib/mongoStorageSettings';

describe('mongoStorageSettings', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('returns null when settings are absent or malformed', () => {
    expect(getMongoStorageSettings()).toBeNull();
    localStorage.setItem('a2ui_mongo_storage', '{bad');
    expect(getMongoStorageSettings()).toBeNull();
  });

  it('round-trips a trimmed URI and database name', () => {
    setMongoStorageSettings({
      uri: ' mongodb+srv://user:secret@cluster ',
      dbName: ' a2ui ',
    });
    expect(getMongoStorageSettings()).toEqual({
      uri: 'mongodb+srv://user:secret@cluster',
      dbName: 'a2ui',
    });
  });

  it('clears only Mongo connection settings', () => {
    localStorage.setItem('agui-theme', 'dark');
    setMongoStorageSettings({ uri: 'mongodb://host', dbName: 'a2ui' });
    clearMongoStorageSettings();
    expect(getMongoStorageSettings()).toBeNull();
    expect(localStorage.getItem('agui-theme')).toBe('dark');
  });
});
```

- [ ] **Step 2: Run test and verify RED**

```powershell
npm run test -- --run src/lib/mongoStorageSettings.test.ts
```

Run with workdir `client`. Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement narrow localStorage helper**

Create source file with mandatory header:

```ts
const MONGO_STORAGE_KEY = 'a2ui_mongo_storage';

export interface MongoStorageSettings {
  uri: string;
  dbName: string;
}

export function getMongoStorageSettings(): MongoStorageSettings | null {
  try {
    const raw = localStorage.getItem(MONGO_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    const value = parsed as Record<string, unknown>;
    if (typeof value.uri !== 'string' ||
        typeof value.dbName !== 'string') {
      return null;
    }
    const uri = value.uri.trim();
    const dbName = value.dbName.trim();
    return uri && dbName ? { uri, dbName } : null;
  } catch {
    return null;
  }
}

export function setMongoStorageSettings(
  settings: MongoStorageSettings,
): void {
  localStorage.setItem(
    MONGO_STORAGE_KEY,
    JSON.stringify({
      uri: settings.uri.trim(),
      dbName: settings.dbName.trim(),
    }),
  );
}

export function clearMongoStorageSettings(): void {
  localStorage.removeItem(MONGO_STORAGE_KEY);
}
```

Never export key through API module or log stored value.

- [ ] **Step 4: Run test and commit**

```powershell
npm run test -- --run src/lib/mongoStorageSettings.test.ts
```

Expected: three tests PASS.

```bash
git add client/src/lib/mongoStorageSettings.ts \
  client/src/lib/mongoStorageSettings.test.ts
git commit -m "feat(storage): persist Mongo connection in browser"
```

## Task 2: Typed Storage API Client

**Files:**
- Create: `client/src/types/storage.ts`
- Create: `client/src/lib/storageApi.ts`
- Create: `client/src/lib/storageApi.test.ts`

- [ ] **Step 1: Write failing API path tests**

Mock Axios like existing `learningApi.test.ts` and assert:

```ts
it('posts Mongo credentials only to connect', async () => {
  mockedAxios.post.mockResolvedValue({ data: mongoStatus });
  await connectStorage({ uri: 'mongodb://host', dbName: 'a2ui' });
  expect(mockedAxios.post).toHaveBeenCalledWith(
    '/settings/storage/connect',
    { uri: 'mongodb://host', dbName: 'a2ui' },
  );
});

it('sends complete browser snapshots to migrate', async () => {
  mockedAxios.post.mockResolvedValue({ data: migrationResult });
  await migrateStorage(providerSettings, webSearchSettings);
  expect(mockedAxios.post).toHaveBeenCalledWith(
    '/settings/storage/migrate',
    { providerSettings, webSearchSettings },
  );
});
```

Also test GET status/app-settings, PUT app-settings, and POST disconnect paths.

- [ ] **Step 2: Run test and verify RED**

```powershell
npm run test -- --run src/lib/storageApi.test.ts
```

Expected: FAIL because types/API module are absent.

- [ ] **Step 3: Add exact client contracts**

Create `client/src/types/storage.ts` with mandatory header:

```ts
import type { AIProviderSettings } from '@/lib/providerSettings';
import type { WebSearchSettings } from '@/types/webSearch';

export type DeploymentMode = 'local' | 'cloud';
export type StorageBackend = 'sqlite' | 'mongo';

export interface StorageStatus {
  deploymentMode: DeploymentMode;
  activeBackend: StorageBackend;
  connected: boolean;
  mongoDbName: string | null;
  canConnect: boolean;
  canDisconnect: boolean;
  canMigrate: boolean;
  localDataPresent: boolean;
}

export interface AppSettingsSnapshot {
  providerSettings: AIProviderSettings | null;
  webSearchSettings: WebSearchSettings | null;
}

export interface CollectionMigrationResult {
  rows: number;
  matched: number;
  upserted: number;
  modified: number;
}

export interface StorageMigrationResult {
  collections: Record<string, CollectionMigrationResult>;
  checkpoints: number;
  checkpointWrites: number;
  warnings: string[];
}
```

- [ ] **Step 4: Implement Axios client**

Create `storageApi.ts` with mandatory header and one private Axios instance:

```ts
const storageApi = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  timeout: 10_000,
});

export async function getStorageStatus(): Promise<StorageStatus> {
  const response = await storageApi.get<StorageStatus>(
    '/settings/storage/status',
  );
  return response.data;
}

export async function connectStorage(
  settings: MongoStorageSettings,
): Promise<StorageStatus> {
  const response = await storageApi.post<StorageStatus>(
    '/settings/storage/connect',
    settings,
  );
  return response.data;
}
```

Implement `disconnectStorage`, `migrateStorage`, `getAppSettings`, and
`putAppSettings` with paths from server contract. Let Axios throw; callers map
errors to UI messages.

- [ ] **Step 5: Run test and commit**

```powershell
npm run test -- --run src/lib/storageApi.test.ts
```

Expected: all API tests PASS.

```bash
git add client/src/types/storage.ts client/src/lib/storageApi.ts \
  client/src/lib/storageApi.test.ts
git commit -m "feat(storage): add typed storage API client"
```

## Task 3: Boot-Once Connect And Hydration

**Files:**
- Create: `client/src/lib/storageBoot.ts`
- Create: `client/src/lib/storageBoot.test.ts`
- Modify: `client/src/lib/providerSettings.ts`
- Modify: `client/src/lib/providerSettings.test.ts`

- [ ] **Step 1: Write failing boot flow tests**

Mock settings/API modules. Tests must cover exact order:

```ts
it('connects once then hydrates when local credentials exist', async () => {
  getStorageStatusMock.mockResolvedValue(localStatus);
  getMongoStorageSettingsMock.mockReturnValue(connection);
  connectStorageMock.mockResolvedValue(mongoStatus);
  getAppSettingsMock.mockResolvedValue(cloudSnapshot);

  const first = bootstrapStorage();
  const second = bootstrapStorage();
  await Promise.all([first, second]);

  expect(first).toBe(second);
  expect(connectStorageMock).toHaveBeenCalledTimes(1);
  expect(setProviderSettingsMock).toHaveBeenCalledWith(
    cloudSnapshot.providerSettings,
  );
  expect(setWebSearchSettingsMock).toHaveBeenCalledWith(
    cloudSnapshot.webSearchSettings,
  );
});

it('does not post connect in cloud deployment', async () => {
  getStorageStatusMock.mockResolvedValue(cloudStatus);
  getAppSettingsMock.mockResolvedValue(cloudSnapshot);
  await bootstrapStorage();
  expect(connectStorageMock).not.toHaveBeenCalled();
  expect(getAppSettingsMock).toHaveBeenCalledTimes(1);
});

it('continues boot when status request fails', async () => {
  getStorageStatusMock.mockRejectedValue(new Error('offline'));
  await expect(bootstrapStorage()).resolves.toEqual(
    expect.objectContaining({ error: expect.any(String) }),
  );
});
```

Expose `resetStorageBootForTests()` only for test isolation.

- [ ] **Step 2: Write failing settings-change event test**

In `providerSettings.test.ts`:

```ts
it('emits one settings change event after provider save', () => {
  const listener = vi.fn();
  window.addEventListener(APP_SETTINGS_CHANGED_EVENT, listener);
  setProviderSettings({ activeProvider: 'generalcompute' });
  expect(listener).toHaveBeenCalledTimes(1);
  window.removeEventListener(APP_SETTINGS_CHANGED_EVENT, listener);
});
```

Add equivalent web-search save assertion.

- [ ] **Step 3: Run tests and verify RED**

```powershell
npm run test -- --run src/lib/storageBoot.test.ts \
  src/lib/providerSettings.test.ts
```

Expected: FAIL because boot/event contracts are absent.

- [ ] **Step 4: Emit settings-change events**

In `providerSettings.ts` export:

```ts
export const APP_SETTINGS_CHANGED_EVENT = 'a2ui-app-settings-changed';
export const APP_SETTINGS_HYDRATED_EVENT = 'a2ui-app-settings-hydrated';

function emitSettingsChanged(): void {
  window.dispatchEvent(new Event(APP_SETTINGS_CHANGED_EVENT));
}
```

Call after successful `localStorage.setItem` in `setProviderSettings` and
`setWebSearchSettings`. Do not emit from read/migration helpers.

- [ ] **Step 5: Implement boot singleton and hydration**

Create `storageBoot.ts` with mandatory header. Core state:

```ts
export interface StorageBootResult {
  status: StorageStatus | null;
  error: string | null;
}

let bootPromise: Promise<StorageBootResult> | null = null;
let stopCloudSync: (() => void) | null = null;

export function bootstrapStorage(): Promise<StorageBootResult> {
  if (!bootPromise) bootPromise = runStorageBoot();
  return bootPromise;
}
```

Flow:

```ts
async function runStorageBoot(): Promise<StorageBootResult> {
  try {
    let status = await getStorageStatus();
    if (status.deploymentMode === 'local' && !status.connected) {
      const connection = getMongoStorageSettings();
      if (connection) status = await connectStorage(connection);
    }
    if (status.activeBackend === 'mongo') {
      const snapshot = await getAppSettings();
      if (snapshot.providerSettings) {
        setProviderSettings(snapshot.providerSettings);
      }
      if (snapshot.webSearchSettings) {
        setWebSearchSettings(snapshot.webSearchSettings);
      }
      window.dispatchEvent(new Event(APP_SETTINGS_HYDRATED_EVENT));
      startCloudSettingsSync();
    }
    return { status, error: null };
  } catch (error: unknown) {
    const message = error instanceof Error
      ? error.message
      : 'Storage boot failed';
    return { status: null, error: message };
  }
}
```

Register sync only after hydration to avoid writing fetched data back. Serialize
writes to preserve latest order:

```ts
let queue = Promise.resolve();
const listener = () => {
  const snapshot = {
    providerSettings: getProviderSettings(),
    webSearchSettings: getWebSearchSettings(),
  };
  queue = queue
    .then(() => putAppSettings(snapshot))
    .catch(() => undefined);
};
```

`stopCloudSettingsSync` removes listener on disconnect. Export
`hydrateAndEnableCloudSettings()` for Settings panel connect and
`disableCloudSettingsSync()` for disconnect.

- [ ] **Step 6: Run tests and commit**

```powershell
npm run test -- --run src/lib/storageBoot.test.ts \
  src/lib/providerSettings.test.ts
```

Expected: PASS, including one-connect promise identity.

```bash
git add client/src/lib/storageBoot.ts \
  client/src/lib/storageBoot.test.ts \
  client/src/lib/providerSettings.ts \
  client/src/lib/providerSettings.test.ts
git commit -m "feat(storage): connect and hydrate once at boot"
```

## Task 4: Storage Settings Panel

**Files:**
- Create: `client/src/features/settings/StorageSettingsPanel.tsx`
- Create: `client/src/features/settings/StorageSettingsPanel.test.tsx`

- [ ] **Step 1: Write failing local/cloud rendering tests**

Create component test with mandatory header, mock storage APIs, and test:

```ts
it('renders local connection controls and status', async () => {
  getStorageStatusMock.mockResolvedValue(localStatus);
  render(<StorageSettingsPanel />);
  expect(await screen.findByText('Local SQLite')).toBeInTheDocument();
  expect(screen.getByLabelText('MongoDB URI')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Connect' })).toBeEnabled();
});

it('renders cloud status without secret or mutation controls', async () => {
  getStorageStatusMock.mockResolvedValue(cloudStatus);
  render(<StorageSettingsPanel />);
  expect(await screen.findByText('Cloud storage')).toBeInTheDocument();
  expect(screen.queryByLabelText('MongoDB URI')).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Disconnect' }))
    .not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Migrate/ }))
    .not.toBeInTheDocument();
});

it('disables migrate until connected with local data', async () => {
  getStorageStatusMock.mockResolvedValue(localStatus);
  render(<StorageSettingsPanel />);
  expect(await screen.findByRole('button', {
    name: 'Migrate local data',
  })).toBeDisabled();
});
```

Add interaction tests: save writes browser helper; connect saves+posts+hydrates;
disconnect posts+stops sync but does not clear saved URI; migrate sends current
provider/search snapshots and renders counts/warnings; 409 detail tells user to
cancel/wait for listed sessions.

- [ ] **Step 2: Run test and verify RED**

```powershell
npm run test -- --run \
  src/features/settings/StorageSettingsPanel.test.tsx
```

Expected: FAIL because component does not exist.

- [ ] **Step 3: Implement component state and actions**

Create source with mandatory header. State:

```ts
const saved = getMongoStorageSettings();
const [uri, setUri] = useState(saved?.uri ?? '');
const [dbName, setDbName] = useState(saved?.dbName ?? 'a2ui');
const [status, setStatus] = useState<StorageStatus | null>(null);
const [pendingAction, setPendingAction] = useState<
  'connect' | 'disconnect' | 'migrate' | null
>(null);
const [error, setError] = useState<string | null>(null);
const [migration, setMigration] =
  useState<StorageMigrationResult | null>(null);
```

Fetch status in effect with cancellation flag. Do not put URI in React Query
cache or errors. Connect action validates nonblank fields, calls API, persists
browser settings only after success, then calls
`hydrateAndEnableCloudSettings()`. Failed credentials must not replace last
known working browser target.

Migrate action:

```ts
const result = await migrateStorage(
  getProviderSettings(),
  getWebSearchSettings(),
);
setMigration(result);
setStatus(await getStorageStatus());
```

Render structure:

```tsx
<div className="space-y-5">
  <div className="flex items-center justify-between gap-3">
    <div>
      <p className="text-sm font-semibold">Data storage</p>
      <p className="text-xs text-muted-foreground">
        Choose local SQLite or one MongoDB Atlas database.
      </p>
    </div>
    <span role="status" className={statusBadgeClass}>...</span>
  </div>
  {/* local-only URI/database fields */}
  <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
    {/* Save connection, Connect, Disconnect, Migrate local data */}
  </div>
  {/* alert, migration counts/warnings, security footer */}
</div>
```

Password URI input uses `type="password"`, `autoComplete="off"`, and no value in
status copy. Footer: `Connection details stay in this browser. Atlas stores app
data and plaintext provider keys while connected.` Cloud copy states environment
owns target.

- [ ] **Step 4: Run component tests and commit**

```powershell
npm run test -- --run \
  src/features/settings/StorageSettingsPanel.test.tsx
```

Expected: local/cloud/action tests PASS.

```bash
git add client/src/features/settings/StorageSettingsPanel.tsx \
  client/src/features/settings/StorageSettingsPanel.test.tsx
git commit -m "feat(storage): add Atlas storage settings panel"
```

## Task 5: Mount Settings Section And Refresh Hydrated State

**Files:**
- Modify: `client/src/features/settings/SettingsPage.tsx`
- Modify: `client/src/features/settings/SettingsPage.test.tsx`

- [ ] **Step 1: Write failing section test**

Mock `StorageSettingsPanel` like sibling panels. Assert `Data Storage` disclosure
exists, starts collapsed, and renders panel after click.

```ts
expect(screen.getByRole('button', { name: /Data Storage/ }))
  .toHaveAttribute('aria-expanded', 'false');
await user.click(screen.getByRole('button', { name: /Data Storage/ }));
expect(screen.getByTestId('storage-settings-panel')).toBeInTheDocument();
```

- [ ] **Step 2: Run test and verify RED**

```powershell
npm run test -- --run src/features/settings/SettingsPage.test.tsx
```

Expected: FAIL because section is absent.

- [ ] **Step 3: Mount section and hydration listener**

Add `"data-storage"` to `SettingsSectionKey`, default false state, `Database`
icon, and section before provider credentials. Wrap panel in existing
`bg-card border border-border p-6 rounded-xl shadow-sm` class.

Listen for cloud hydration so SettingsPage's cached provider state updates after
an in-page connect:

```ts
useEffect(() => {
  const refresh = () => setSettings(getProviderSettings());
  window.addEventListener(APP_SETTINGS_HYDRATED_EVENT, refresh);
  return () => {
    window.removeEventListener(APP_SETTINGS_HYDRATED_EVENT, refresh);
  };
}, []);
```

Update imports to include `useEffect`; preserve current file style.

- [ ] **Step 4: Run tests and commit**

```powershell
npm run test -- --run src/features/settings/SettingsPage.test.tsx \
  src/features/settings/StorageSettingsPanel.test.tsx
```

Expected: PASS.

```bash
git add client/src/features/settings/SettingsPage.tsx \
  client/src/features/settings/SettingsPage.test.tsx
git commit -m "feat(storage): mount storage settings section"
```

## Task 6: Await Storage Boot Before App Render

**Files:**
- Create: `client/src/lib/startApplication.ts`
- Create: `client/src/lib/startApplication.test.ts`
- Modify: `client/src/main.tsx`

- [ ] **Step 1: Add render-after-boot test seam**

Create `client/src/lib/startApplication.test.ts` with mandatory header and test:

```ts
it('renders only after bounded storage boot settles', async () => {
  const render = vi.fn();
  bootstrapStorageMock.mockResolvedValue({ status: null, error: 'offline' });
  await startApplication(render);
  expect(bootstrapStorageMock).toHaveBeenCalledTimes(1);
  expect(render).toHaveBeenCalledTimes(1);
});
```

- [ ] **Step 2: Run test and verify RED**

```powershell
npm run test -- --run src/lib/startApplication.test.ts
```

Expected: FAIL because start module does not exist.

- [ ] **Step 3: Implement isolated start helper**

Create `client/src/lib/startApplication.ts` with mandatory header:

```ts
import { bootstrapStorage } from '@/lib/storageBoot';

export async function startApplication(render: () => void): Promise<void> {
  await bootstrapStorage();
  render();
}
```

- [ ] **Step 4: Refactor entrypoint without changing provider order**

Keep current `ThemeProvider -> QueryProvider -> App` tree. Replace immediate
render with:

```ts
void startApplication(renderApplication);
```

`storageApi` 10-second timeout bounds failure; `bootstrapStorage` catches it, so
app always renders. Boot happens before learning queries, preventing SQLite/Mongo
race. StrictMode cannot duplicate connect because singleton promise is outside
React.

- [ ] **Step 5: Run client quality gates**

```powershell
npm run test -- --run
npm run lint
npm run build
```

Expected: all Vitest tests PASS, ESLint PASS, TypeScript/Vite build PASS.

- [ ] **Step 6: Commit**

```bash
git add client/src/main.tsx client/src/lib/startApplication.ts \
  client/src/lib/startApplication.test.ts
git commit -m "feat(storage): complete storage boot before render"
```

## Phase 6 Exit Checkpoint

- [ ] URI/database stay only in `a2ui_mongo_storage` browser key.
- [ ] Boot POSTs connect once and never in cloud deployment mode.
- [ ] Mongo app settings hydrate before render and after in-page connect.
- [ ] Provider/search changes serialize complete PUT snapshots while on Mongo.
- [ ] Local UI offers save/connect/disconnect/migrate; cloud UI is read-only.
- [ ] Theme and concept-chat caches are untouched and never migrated.
- [ ] Desktop/mobile layouts, keyboard focus, and reduced motion match existing UI.
- [ ] Add phase note:

```bash
git notes add -m "Phase 6 complete: storage UI, boot connect, and hydration"
```
