# Implementation Plan: Fix LearningSessionSummary Status Validation Error

## Problem Statement

When accessing the course dashboard via `GET /learning/sessions?status=all&sort_by=updated_at&limit=4&offset=0`, the API responds with an **HTTP 500 Internal Server Error**:

```text
ERROR:server.routers.learning:Error listing learning sessions: 1 validation error for LearningSessionSummary
status
  Input should be 'in_progress' or 'completed' [type=literal_error, input_value='active', input_type=str]
    For further information visit https://errors.pydantic.dev/2.13/v/literal_error
INFO:     127.0.0.1:57420 - "GET /learning/sessions?status=all&sort_by=updated_at&limit=4&offset=0 HTTP/1.1" 500 Internal Server Error
```

---

## Root Cause Analysis

1. **Schema Definition**:
   - In [`server/schemas/learning.py`](file:///c:/Users/Admin/Desktop/peter/server/schemas/learning.py#L827), `LearningSessionSummary` defines:
     ```python
     status: Literal["in_progress", "completed"] = Field(
         default="in_progress", description="Session status"
     )
     ```
   - In [`client/src/types/learning.ts`](file:///c:/Users/Admin/Desktop/peter/client/src/types/learning.ts#L252), the client contract is:
     ```typescript
     status: "in_progress" | "completed";
     ```

2. **MongoDB Repositories Writing `'active'`**:
   - In [`server/database/repositories/mongo_learning.py`](file:///c:/Users/Admin/Desktop/peter/server/database/repositories/mongo_learning.py#L120):
     ```python
     document = {
         ...
         "status": "active",
         ...
     }
     ```
   - In [`server/database/repositories/mongo_jobs.py`](file:///c:/Users/Admin/Desktop/peter/server/database/repositories/mongo_jobs.py#L122):
     ```python
     session_document = {
         ...
         "status": "active",
         ...
     }
     ```

3. **Session Querying & Listing**:
   - In [`server/database/repositories/mongo_learning.py`](file:///c:/Users/Admin/Desktop/peter/server/database/repositories/mongo_learning.py#L262-L265):
     ```python
     if total > 0 and completed == total:
         row["status"] = "completed"
     elif "status" not in row or not row["status"]:
         row["status"] = "in_progress"
     ```
     Because `"status"` is already present in MongoDB as `"active"`, it does not enter the `elif` branch and remains `"active"`.

4. **Router Model Validation**:
   - In [`server/routers/learning.py`](file:///c:/Users/Admin/Desktop/peter/server/routers/learning.py#L428-L439):
     ```python
     row.setdefault("status", "in_progress")
     typed_sessions.append(LearningSessionSummary.model_validate(row))
     ```
     Since `row["status"]` is already `"active"`, `setdefault` does not overwrite it. Pydantic throws a `ValidationError` when attempting to validate against `Literal["in_progress", "completed"]`.

---

## Step-by-Step Implementation Plan

### Step 1: Fix Default Status on Insertion in MongoDB Repositories
- **File**: [`server/database/repositories/mongo_learning.py`](file:///c:/Users/Admin/Desktop/peter/server/database/repositories/mongo_learning.py)
  - In `create_learning_session()` (line 120), change `"status": "active"` to `"status": "in_progress"`.
- **File**: [`server/database/repositories/mongo_jobs.py`](file:///c:/Users/Admin/Desktop/peter/server/database/repositories/mongo_jobs.py)
  - In `create_job()` (line 122), change `"status": "active"` to `"status": "in_progress"`.

### Step 2: Backward Compatibility & Normalization in MongoDB Queries
- **File**: [`server/database/repositories/mongo_learning.py`](file:///c:/Users/Admin/Desktop/peter/server/database/repositories/mongo_learning.py)
  - In `get_sessions_list()`:
    - Support filtering when `status == "in_progress"` to also include existing legacy documents stored with `"active"`:
      ```python
      if status == "in_progress":
          query["status"] = {"$in": ["in_progress", "active"]}
      elif status != "all":
          query["status"] = status
      ```
    - In the row-formatting loop, safely normalize any `'active'`, empty, or missing status to `'in_progress'`:
      ```python
      if total > 0 and completed == total:
          row["status"] = "completed"
      elif row.get("status") in ("active", "in_progress", None, ""):
          row["status"] = "in_progress"
      ```
  - In `get_session_progress()` (line 183):
    - Normalize `"active"` to `"in_progress"`:
      ```python
      current_status = session.get("status")
      "status": "in_progress" if current_status in ("active", None, "") else current_status,
      ```

### Step 3: Defense-in-Depth in Learning API Router
- **File**: [`server/routers/learning.py`](file:///c:/Users/Admin/Desktop/peter/server/routers/learning.py)
  - In `list_sessions()` (around line 428):
    - Ensure any raw row with `"status": "active"` is explicitly normalized before calling `LearningSessionSummary.model_validate(row)`:
      ```python
      if row.get("status") in ("active", None, ""):
          row["status"] = "in_progress"
      ```

### Step 4: Unit Testing & Verification
- **File**: [`server/tests/test_mongo_learning.py`](file:///c:/Users/Admin/Desktop/peter/server/tests/test_mongo_learning.py)
  - Update `test_create_learning_session_persists_expected_fields` to assert `inserted["status"] == "in_progress"`.
  - Add test case verifying that `get_sessions_list()` handles legacy documents with `"status": "active"` without error and parses into `LearningSessionSummary`.
- Run tests:
  ```bash
  python -m unittest server.tests.test_mongo_learning
  python -m unittest server.tests.test_generation_router
  ```

---

## Impact Assessment
- **Zero Breaking Changes**: The frontend already expects `"in_progress" | "completed"`.
- **Legacy Records Supported**: Existing sessions in MongoDB with `"status": "active"` will transparently be read and returned as `"in_progress"`.
- **Eliminates 500 Error**: The session listing endpoint will return HTTP 200 OK.
