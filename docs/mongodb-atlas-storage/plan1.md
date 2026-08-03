# MongoDB Atlas Storage Phase 1: Storage Mode Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deployment/storage mode contracts, safe synchronous MongoDB
connection lifecycle, and local-only status/connect/disconnect APIs without
changing application repositories yet.

**Architecture:** Approach A repository swap foundation. `StorageContext` owns
one process-wide PyMongo `MongoClient`, validates it with `ping`, and exposes
status while SQLite remains default. Phase 2 adds repository ports; Phase 3
turns successful Mongo connections into complete repository swaps.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, PyMongo sync
`MongoClient`, stdlib `unittest`, `unittest.mock`.

**Source references:** `docs/mongodb-atlas-storage/goal.md` and
`docs/mongodb-atlas-storage/research.md`. Research overrides goal's Motor
reference: use PyMongo sync for app data. Also follow root `AGENTS.md`; its
referenced `.planning/codebase/*` files were absent when this plan was written.

**Command note:** For multiline `powershell` blocks, join wrapped lines into one
line and omit display-only trailing `\` characters. `bash` blocks use `\` as
normal shell continuation.

---

## Scope And File Map

This phase may report `activeBackend=mongo` after connect, but application
stores still remain SQLite until Phase 3. Do not release or demo partial Phase 1
as complete cloud storage.

| File | Responsibility |
|------|----------------|
| `server/database/storage_mode.py` | Enums, `StorageContext`, local-data probe |
| `server/database/mongo_client.py` | Client factory, ping, close, URI redaction |
| `server/schemas/storage.py` | Camel-case REST request/response contracts |
| `server/routers/storage.py` | Status/connect/disconnect endpoints and guards |
| `server/config.py` | `DEPLOYMENT_MODE`, `MONGO_URI`, `MONGO_DB` parsing |
| `server/routers/__init__.py` | Export storage router |
| `server/main.py` | Create context and include router |
| `server/requirements.txt` | Add compatible PyMongo range |
| `server/tests/test_storage_mode.py` | Config, context, and local-data tests |
| `server/tests/test_mongo_client.py` | Ping, cleanup, and redaction tests |
| `server/tests/test_storage_router.py` | API payloads and cloud guards |

Every new `.py` file must begin with exact mandatory header from `AGENTS.md`,
including 76-character separators. Keep shown Python lines within 80 columns.

## Task 1: Deployment And Storage Enums

**Files:**
- Create: `server/database/storage_mode.py`
- Modify: `server/config.py`
- Create: `server/tests/test_storage_mode.py`

- [ ] **Step 1: Write failing environment parsing tests**

Create `server/tests/test_storage_mode.py` with mandatory Python header, then:

```python
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from server.config import Settings
from server.database.storage_mode import DeploymentMode, StorageBackend


class StorageModeConfigTests(unittest.TestCase):
    def test_defaults_to_local_without_mongo_config(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Settings()

        self.assertEqual(settings.deployment_mode, DeploymentMode.LOCAL)
        self.assertIsNone(settings.mongo_uri)
        self.assertIsNone(settings.mongo_db)

    def test_reads_cloud_environment(self) -> None:
        env = {
            "DEPLOYMENT_MODE": "cloud",
            "MONGO_URI": "mongodb://user:secret@db.example/a2ui",
            "MONGO_DB": "a2ui",
        }
        with patch.dict(os.environ, env, clear=True):
            settings = Settings()

        self.assertEqual(settings.deployment_mode, DeploymentMode.CLOUD)
        self.assertEqual(settings.mongo_uri, env["MONGO_URI"])
        self.assertEqual(settings.mongo_db, "a2ui")

    def test_rejects_unknown_deployment_mode(self) -> None:
        with patch.dict(
            os.environ,
            {"DEPLOYMENT_MODE": "shared"},
            clear=True,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "DEPLOYMENT_MODE must be local or cloud",
            ):
                Settings()

    def test_storage_backend_values_match_api(self) -> None:
        self.assertEqual(StorageBackend.SQLITE.value, "sqlite")
        self.assertEqual(StorageBackend.MONGO.value, "mongo")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify RED**

Run from repository root:

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_storage_mode.StorageModeConfigTests -v
```

Expected: FAIL because `storage_mode` and instance config fields do not exist.

- [ ] **Step 3: Add enums and instance-based config**

Start `server/database/storage_mode.py` with mandatory header, then add:

```python
from __future__ import annotations

from enum import Enum


class DeploymentMode(str, Enum):
    """Server deployment policy controlling mutable storage endpoints."""

    LOCAL = "local"
    CLOUD = "cloud"


class StorageBackend(str, Enum):
    """Active application persistence backend."""

    SQLITE = "sqlite"
    MONGO = "mongo"
```

Refactor `server/config.py` so environment is read in `Settings.__init__` and
existing lowercase and uppercase consumers both remain valid:

```python
from server.database.storage_mode import DeploymentMode


class Settings:
    """Environment-backed server settings."""

    def __init__(self) -> None:
        raw_mode = os.getenv("DEPLOYMENT_MODE", "local").strip().lower()
        try:
            self.deployment_mode = DeploymentMode(raw_mode)
        except ValueError as exc:
            raise RuntimeError(
                "DEPLOYMENT_MODE must be local or cloud"
            ) from exc
        self.mongo_uri = os.getenv("MONGO_URI") or None
        self.mongo_db = os.getenv("MONGO_DB") or None
        self.OPENROUTER_BASE_URL = os.getenv(
            "OPENROUTER_BASE_URL",
            "https://openrouter.ai/api/v1",
        )
        self.OPENROUTER_TIMEOUT_SECONDS = float(
            os.getenv("OPENROUTER_TIMEOUT_SECONDS", "60.0")
        )
        self.GENERALCOMPUTE_BASE_URL = os.getenv(
            "GENERALCOMPUTE_BASE_URL",
            "https://api.generalcompute.com/v1",
        )
        self.GENERALCOMPUTE_TIMEOUT_SECONDS = float(
            os.getenv("GENERALCOMPUTE_TIMEOUT_SECONDS", "60.0")
        )
```

- [ ] **Step 4: Run test and verify GREEN**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_storage_mode.StorageModeConfigTests -v
```

Expected: four tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/config.py server/database/storage_mode.py \
  server/tests/test_storage_mode.py
git commit -m "feat(storage): add deployment and backend modes"
```

## Task 2: Safe Sync Mongo Client

**Files:**
- Create: `server/database/mongo_client.py`
- Create: `server/tests/test_mongo_client.py`
- Modify: `server/requirements.txt`

- [ ] **Step 1: Add dependency needed by test imports**

Append this line to `server/requirements.txt`:

```text
pymongo[srv]>=4.13,<4.17
```

Install in server virtual environment:

```powershell
server\.venv\Scripts\python.exe -m pip install -r server\requirements.txt
```

Expected: compatible PyMongo installs; Motor is not installed.

- [ ] **Step 2: Write failing client and redaction tests**

Create `server/tests/test_mongo_client.py` with mandatory header, then:

```python
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pymongo.errors import (
    ConfigurationError,
    OperationFailure,
    ServerSelectionTimeoutError,
)

from server.database.mongo_client import (
    MongoConfigurationError,
    MongoUnavailableError,
    connect_mongo,
    redact_mongo_uri,
)


class MongoClientTests(unittest.TestCase):
    def test_redacts_standard_and_srv_passwords(self) -> None:
        cases = {
            "mongodb://alice:secret@host/db":
                "mongodb://alice:***@host/db",
            "mongodb+srv://bob:p%40ss@cluster/db":
                "mongodb+srv://bob:***@cluster/db",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(redact_mongo_uri(raw), expected)

    def test_returns_client_and_database_after_ping(self) -> None:
        client = MagicMock()
        database = client.__getitem__.return_value
        with patch(
            "server.database.mongo_client.MongoClient",
            return_value=client,
        ):
            connection = connect_mongo("mongodb://host", "a2ui")

        client.admin.command.assert_called_once_with("ping")
        self.assertIs(connection.client, client)
        self.assertIs(connection.database, database)
        self.assertEqual(connection.db_name, "a2ui")

    def test_closes_client_on_configuration_failure(self) -> None:
        client = MagicMock()
        client.admin.command.side_effect = ConfigurationError("bad URI")
        with patch(
            "server.database.mongo_client.MongoClient",
            return_value=client,
        ):
            with self.assertRaises(MongoConfigurationError):
                connect_mongo("mongodb://user:secret@host", "a2ui")
        client.close.assert_called_once_with()

    def test_maps_auth_failure_without_exposing_driver_detail(self) -> None:
        client = MagicMock()
        client.admin.command.side_effect = OperationFailure(
            "Authentication failed for user:secret"
        )
        with patch(
            "server.database.mongo_client.MongoClient",
            return_value=client,
        ):
            with self.assertRaises(MongoConfigurationError) as caught:
                connect_mongo("mongodb://user:secret@host", "a2ui")
        self.assertNotIn("secret", str(caught.exception))
        client.close.assert_called_once_with()

    def test_maps_timeout_without_leaking_uri(self) -> None:
        client = MagicMock()
        client.admin.command.side_effect = ServerSelectionTimeoutError(
            "mongodb://user:secret@host timed out"
        )
        with patch(
            "server.database.mongo_client.MongoClient",
            return_value=client,
        ):
            with self.assertRaises(MongoUnavailableError) as caught:
                connect_mongo("mongodb://user:secret@host", "a2ui")
        self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_client -v
```

Expected: FAIL because `mongo_client.py` does not exist.

- [ ] **Step 4: Implement connection lifecycle**

Create `server/database/mongo_client.py` with mandatory header and this core:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import (
    ConfigurationError,
    ConnectionFailure,
    InvalidURI,
    OperationFailure,
    ServerSelectionTimeoutError,
)

_CREDENTIALS = re.compile(
    r"(mongodb(?:\+srv)?://)([^:/?#]+):([^@]+)@",
    re.IGNORECASE,
)


class MongoConfigurationError(ValueError):
    """Mongo connection request is malformed or rejected by auth."""


class MongoUnavailableError(ConnectionError):
    """Mongo target cannot be reached within configured timeout."""


@dataclass(frozen=True)
class MongoConnection:
    """Validated process-wide client and selected database."""

    client: MongoClient[Any]
    database: Database[Any]
    db_name: str


def redact_mongo_uri(uri: str) -> str:
    """Mask Mongo password while retaining target context for diagnostics."""

    return _CREDENTIALS.sub(r"\1\2:***@", uri)


def connect_mongo(
    uri: str,
    db_name: str,
    *,
    timeout_ms: int = 5000,
) -> MongoConnection:
    """Create one sync client, ping it, and return selected database."""

    try:
        client = MongoClient(
            uri,
            serverSelectionTimeoutMS=timeout_ms,
            maxPoolSize=50,
            minPoolSize=0,
            maxConnecting=2,
            retryWrites=True,
            w="majority",
        )
    except (ConfigurationError, InvalidURI) as exc:
        raise MongoConfigurationError("Invalid MongoDB connection") from exc
    try:
        client.admin.command("ping")
    except (ConfigurationError, InvalidURI, OperationFailure) as exc:
        client.close()
        raise MongoConfigurationError("MongoDB rejected connection") from exc
    except (ConnectionFailure, ServerSelectionTimeoutError) as exc:
        client.close()
        raise MongoUnavailableError("MongoDB is unreachable") from exc
    return MongoConnection(client, client[db_name], db_name)
```

Never log `str(exc)` from PyMongo because it may echo URI credentials. Log only
exception class and `redact_mongo_uri(uri)`.

- [ ] **Step 5: Run test and verify GREEN**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_mongo_client -v
```

Expected: four tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/database/mongo_client.py server/requirements.txt \
  server/tests/test_mongo_client.py
git commit -m "feat(storage): add safe Mongo client lifecycle"
```

## Task 3: Storage REST Schemas

**Files:**
- Create: `server/schemas/storage.py`
- Create: `server/tests/test_storage_schemas.py`

- [ ] **Step 1: Write failing alias and validation tests**

Create test file with mandatory header and:

```python
from __future__ import annotations

import unittest

from pydantic import ValidationError

from server.schemas.storage import (
    StorageConnectRequest,
    StorageStatusResponse,
)


class StorageSchemaTests(unittest.TestCase):
    def test_status_serializes_camel_case_contract(self) -> None:
        status = StorageStatusResponse(
            deployment_mode="local",
            active_backend="sqlite",
            connected=False,
            mongo_db_name=None,
            can_connect=True,
            can_disconnect=False,
            can_migrate=False,
            local_data_present=True,
        )
        payload = status.model_dump(mode="json", by_alias=True)
        self.assertEqual(payload["deploymentMode"], "local")
        self.assertEqual(payload["activeBackend"], "sqlite")
        self.assertTrue(payload["localDataPresent"])

    def test_connect_accepts_camel_case_database_name(self) -> None:
        request = StorageConnectRequest.model_validate(
            {"uri": "mongodb://host", "dbName": "a2ui"}
        )
        self.assertEqual(request.db_name, "a2ui")

    def test_connect_rejects_non_mongo_uri(self) -> None:
        with self.assertRaises(ValidationError):
            StorageConnectRequest.model_validate(
                {"uri": "https://host", "dbName": "a2ui"}
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_storage_schemas -v
```

Expected: FAIL because storage schemas do not exist.

- [ ] **Step 3: Implement contracts**

Create `server/schemas/storage.py` with mandatory header and:

```python
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from server.database.storage_mode import DeploymentMode, StorageBackend


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.title() for part in tail)


class StorageSchema(BaseModel):
    """Base contract using camel-case JSON and snake-case Python."""

    model_config = ConfigDict(
        alias_generator=_to_camel,
        populate_by_name=True,
    )


class StorageConnectRequest(StorageSchema):
    uri: str = Field(min_length=10, max_length=2048, repr=False)
    db_name: str = Field(min_length=1, max_length=63)

    @field_validator("uri")
    @classmethod
    def validate_uri_scheme(cls, value: str) -> str:
        if not value.startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError("URI must use mongodb or mongodb+srv")
        return value

    @field_validator("db_name")
    @classmethod
    def validate_database_name(cls, value: str) -> str:
        forbidden = set('/\\."$\x00')
        if any(character in forbidden for character in value):
            raise ValueError("Mongo database name contains invalid characters")
        return value


class StorageStatusResponse(StorageSchema):
    deployment_mode: DeploymentMode
    active_backend: StorageBackend
    connected: bool
    mongo_db_name: Optional[str] = None
    can_connect: bool
    can_disconnect: bool
    can_migrate: bool
    local_data_present: bool
```

- [ ] **Step 4: Run test and verify GREEN**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_storage_schemas -v
```

Expected: three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/schemas/storage.py server/tests/test_storage_schemas.py
git commit -m "feat(storage): define storage API contracts"
```

## Task 4: StorageContext Connect And Disconnect

**Files:**
- Modify: `server/database/storage_mode.py`
- Modify: `server/tests/test_storage_mode.py`

- [ ] **Step 1: Add failing context swap tests**

Append:

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from server.database.mongo_client import MongoConnection
from server.database.storage_mode import StorageContext


class StorageContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "a2ui.db"
        self.client = MagicMock()
        self.connection = MongoConnection(
            client=self.client,
            database=MagicMock(),
            db_name="atlas_db",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_connect_sets_validated_client_in_process_memory(self) -> None:
        factory = MagicMock(return_value=self.connection)
        context = StorageContext(
            deployment_mode=DeploymentMode.LOCAL,
            sqlite_path=self.db_path,
            mongo_factory=factory,
        )
        context.connect("mongodb://host", "atlas_db")

        self.assertEqual(context.active_backend, StorageBackend.MONGO)
        self.assertTrue(context.connected)
        self.assertEqual(context.mongo_db_name, "atlas_db")
        factory.assert_called_once_with("mongodb://host", "atlas_db")

    def test_failed_reconnect_keeps_previous_connection(self) -> None:
        factory = MagicMock(
            side_effect=[self.connection, RuntimeError("failed")]
        )
        context = StorageContext(
            deployment_mode=DeploymentMode.LOCAL,
            sqlite_path=self.db_path,
            mongo_factory=factory,
        )
        context.connect("mongodb://one", "atlas_db")
        with self.assertRaises(RuntimeError):
            context.connect("mongodb://two", "other")

        self.assertEqual(context.mongo_db_name, "atlas_db")
        self.client.close.assert_not_called()

    def test_disconnect_closes_client_and_reverts_to_sqlite(self) -> None:
        context = StorageContext(
            deployment_mode=DeploymentMode.LOCAL,
            sqlite_path=self.db_path,
            mongo_factory=MagicMock(return_value=self.connection),
        )
        context.connect("mongodb://host", "atlas_db")
        context.disconnect()

        self.client.close.assert_called_once_with()
        self.assertEqual(context.active_backend, StorageBackend.SQLITE)
        self.assertFalse(context.connected)
```

- [ ] **Step 2: Run context tests and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_storage_mode.StorageContextTests -v
```

Expected: FAIL because `StorageContext` does not exist.

- [ ] **Step 3: Implement minimal context**

Add to `server/database/storage_mode.py`:

```python
import sqlite3
import threading
from pathlib import Path
from typing import Callable, Optional

from server.database.mongo_client import MongoConnection, connect_mongo

MongoFactory = Callable[[str, str], MongoConnection]


class StorageContext:
    """Own active storage mode and process-wide Mongo connection."""

    def __init__(
        self,
        *,
        deployment_mode: DeploymentMode,
        sqlite_path: Path,
        mongo_factory: MongoFactory = connect_mongo,
    ) -> None:
        self.deployment_mode = deployment_mode
        self.sqlite_path = sqlite_path
        self.active_backend = StorageBackend.SQLITE
        self._mongo_factory = mongo_factory
        self._mongo: Optional[MongoConnection] = None
        self._lock = threading.RLock()

    @property
    def connected(self) -> bool:
        return self._mongo is not None

    @property
    def mongo_db_name(self) -> Optional[str]:
        return self._mongo.db_name if self._mongo is not None else None

    @property
    def mongo_connection(self) -> Optional[MongoConnection]:
        return self._mongo

    def connect(self, uri: str, db_name: str) -> None:
        candidate = self._mongo_factory(uri, db_name)
        with self._lock:
            previous = self._mongo
            self._mongo = candidate
            self.active_backend = StorageBackend.MONGO
        if previous is not None:
            previous.client.close()

    def disconnect(self) -> None:
        with self._lock:
            previous = self._mongo
            self._mongo = None
            self.active_backend = StorageBackend.SQLITE
        if previous is not None:
            previous.client.close()

    def local_data_present(self) -> bool:
        if not self.sqlite_path.exists():
            return False
        try:
            with sqlite3.connect(self.sqlite_path) as connection:
                row = connection.execute(
                    "SELECT 1 FROM learning_sessions LIMIT 1"
                ).fetchone()
        except sqlite3.Error:
            return False
        return row is not None
```

Candidate connection is built before acquiring lock. Failed reconnect therefore
cannot destroy current working connection. Phase 3 expands locked section to swap
all repositories atomically.

- [ ] **Step 4: Run context tests and verify GREEN**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_storage_mode -v
```

Expected: all storage mode tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/database/storage_mode.py server/tests/test_storage_mode.py
git commit -m "feat(storage): add process storage context"
```

## Task 5: Status, Connect, And Disconnect Router

**Files:**
- Create: `server/routers/storage.py`
- Create: `server/tests/test_storage_router.py`
- Modify: `server/routers/__init__.py`
- Modify: `server/main.py`

- [ ] **Step 1: Write failing router tests with fresh FastAPI app**

Create test file with mandatory header and:

```python
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.database.mongo_client import (
    MongoConfigurationError,
    MongoUnavailableError,
)
from server.database.storage_mode import DeploymentMode, StorageBackend
from server.routers.storage import router


def make_storage(mode: DeploymentMode) -> SimpleNamespace:
    return SimpleNamespace(
        deployment_mode=mode,
        active_backend=StorageBackend.SQLITE,
        connected=False,
        mongo_db_name=None,
        connect=MagicMock(),
        disconnect=MagicMock(),
        local_data_present=MagicMock(return_value=True),
    )


def make_client(storage: SimpleNamespace) -> TestClient:
    app = FastAPI()
    app.state.storage = storage
    app.include_router(router)
    return TestClient(app)


class StorageRouterTests(unittest.TestCase):
    def test_status_uses_camel_case_contract(self) -> None:
        response = make_client(
            make_storage(DeploymentMode.LOCAL)
        ).get("/settings/storage/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["activeBackend"], "sqlite")
        self.assertTrue(response.json()["canConnect"])

    def test_connect_passes_credentials_once(self) -> None:
        storage = make_storage(DeploymentMode.LOCAL)

        def connect(uri: str, db_name: str) -> None:
            storage.connected = True
            storage.active_backend = StorageBackend.MONGO
            storage.mongo_db_name = db_name

        storage.connect.side_effect = connect
        response = make_client(storage).post(
            "/settings/storage/connect",
            json={"uri": "mongodb://host", "dbName": "a2ui"},
        )

        self.assertEqual(response.status_code, 200)
        storage.connect.assert_called_once_with("mongodb://host", "a2ui")
        self.assertNotIn("uri", response.json())

    def test_cloud_rejects_mutable_endpoints(self) -> None:
        client = make_client(make_storage(DeploymentMode.CLOUD))
        connect = client.post(
            "/settings/storage/connect",
            json={"uri": "mongodb://host", "dbName": "a2ui"},
        )
        disconnect = client.post("/settings/storage/disconnect")
        self.assertEqual(connect.status_code, 403)
        self.assertEqual(disconnect.status_code, 403)

    def test_connect_maps_configuration_and_network_errors(self) -> None:
        storage = make_storage(DeploymentMode.LOCAL)
        storage.connect.side_effect = MongoConfigurationError("bad")
        bad = make_client(storage).post(
            "/settings/storage/connect",
            json={"uri": "mongodb://host", "dbName": "a2ui"},
        )
        self.assertEqual(bad.status_code, 400)

        storage.connect.side_effect = MongoUnavailableError("down")
        down = make_client(storage).post(
            "/settings/storage/connect",
            json={"uri": "mongodb://host", "dbName": "a2ui"},
        )
        self.assertEqual(down.status_code, 503)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify RED**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_storage_router -v
```

Expected: FAIL because storage router does not exist.

- [ ] **Step 3: Implement router with thread-pool ping**

Create `server/routers/storage.py` with mandatory header. Core code:

```python
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool

from server.database.mongo_client import (
    MongoConfigurationError,
    MongoUnavailableError,
)
from server.database.storage_mode import DeploymentMode, StorageContext
from server.schemas.storage import (
    StorageConnectRequest,
    StorageStatusResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/settings/storage", tags=["storage"])


def _storage(request: Request) -> StorageContext:
    return request.app.state.storage


def _status(context: StorageContext) -> StorageStatusResponse:
    local_mode = context.deployment_mode == DeploymentMode.LOCAL
    return StorageStatusResponse(
        deployment_mode=context.deployment_mode,
        active_backend=context.active_backend,
        connected=context.connected,
        mongo_db_name=context.mongo_db_name,
        can_connect=local_mode,
        can_disconnect=local_mode and context.connected,
        can_migrate=(
            local_mode
            and context.connected
            and context.local_data_present()
        ),
        local_data_present=context.local_data_present(),
    )


def _require_local(context: StorageContext) -> None:
    if context.deployment_mode == DeploymentMode.CLOUD:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Storage is managed by deployment environment",
        )


@router.get(
    "/status",
    response_model=StorageStatusResponse,
    summary="Get active storage status",
)
async def get_storage_status(request: Request) -> StorageStatusResponse:
    return _status(_storage(request))


@router.post(
    "/connect",
    response_model=StorageStatusResponse,
    summary="Connect local server to MongoDB",
)
async def connect_storage(
    payload: StorageConnectRequest,
    request: Request,
) -> StorageStatusResponse:
    context = _storage(request)
    _require_local(context)
    try:
        await run_in_threadpool(
            context.connect,
            payload.uri,
            payload.db_name,
        )
    except MongoConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MongoDB connection is invalid or unauthorized",
        ) from exc
    except MongoUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MongoDB is unreachable",
        ) from exc
    return _status(context)


@router.post(
    "/disconnect",
    response_model=StorageStatusResponse,
    summary="Return local server to SQLite",
)
async def disconnect_storage(request: Request) -> StorageStatusResponse:
    context = _storage(request)
    _require_local(context)
    await run_in_threadpool(context.disconnect)
    return _status(context)
```

- [ ] **Step 4: Wire export, context creation, and router registration**

In `server/routers/__init__.py` import and export `storage_router`:

```python
from server.routers.storage import router as storage_router
```

Add `"storage_router"` to `__all__`.

In `server/main.py`, import `settings`, `DB_PATH`, `StorageContext`, and
`storage_router`. During lifespan, before `yield`, assign:

```python
storage = StorageContext(
    deployment_mode=settings.deployment_mode,
    sqlite_path=DB_PATH,
)
app.state.storage = storage
```

During shutdown call `storage.disconnect()` only in local mode; Phase 7 replaces
this with cloud-aware lifecycle. Register router at module bottom:

```python
app.include_router(storage_router)
```

- [ ] **Step 5: Run targeted tests and verify GREEN**

```powershell
server\.venv\Scripts\python.exe -m unittest \
  server.tests.test_storage_mode \
  server.tests.test_mongo_client \
  server.tests.test_storage_schemas \
  server.tests.test_storage_router -v
```

Expected: all Phase 1 tests PASS.

- [ ] **Step 6: Run server regression suite**

```powershell
server\.venv\Scripts\python.exe -m unittest
```

Expected: PASS. No test contacts Atlas.

- [ ] **Step 7: Commit**

```bash
git add server/main.py server/routers/__init__.py \
  server/routers/storage.py server/tests/test_storage_router.py
git commit -m "feat(storage): expose local storage lifecycle API"
```

## Phase 1 Exit Checkpoint

- [ ] Confirm no Motor dependency or import exists.
- [ ] Confirm no response or log contains Mongo URI.
- [ ] Confirm cloud mode returns 403 for connect/disconnect.
- [ ] Confirm failed reconnect leaves current client untouched.
- [ ] Confirm no existing application repository has been swapped yet.
- [ ] Add phase note after final implementation commit:

```bash
git notes add -m "Phase 1 complete: storage mode, PyMongo lifecycle, and API"
```
