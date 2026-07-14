# Hermes App Runtime Event Protocol v1

Status: **Frozen**
Protocol version: `1`
Contract version: `1.0.0`
Frozen on: `2026-07-12`

This protocol connects an application running in the user's browser to its
local Hermes AppHost. It is loopback-only in phase 1. Remote Gateway access is
explicitly out of scope.

## 1. AppHost and session binding

- Each launched app receives a dedicated random loopback origin. Origins are
  never shared between applications.
- A one-time launch code is exchanged by AppHost for an HttpOnly, SameSite=Strict
  runtime cookie, then immediately invalidated. Launch codes, cookies, and CSRF
  tokens MUST NOT be logged.
- `GET /__hermes/bootstrap` returns app metadata, runtime compatibility,
  granted permissions, action descriptors, and a CSRF token. The browser never
  supplies or selects an `app_id`; AppHost binds identity from its launch
  context.
- Mutating requests require the runtime cookie and `X-Hermes-CSRF`. Requests
  with an unexpected `Origin` or `Host` are rejected.

## 2. Runtime HTTP surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/__hermes/bootstrap` | Bootstrap the authenticated app session |
| `POST` | `/api/actions/{action_id}/runs` | Validate input and enqueue a run |
| `GET` | `/api/runs/{run_id}` | Read the latest run snapshot |
| `GET` | `/api/runs/{run_id}/events` | Subscribe or resume the SSE stream |
| `DELETE` | `/api/runs/{run_id}` | Request cancellation; idempotent |
| `GET` | `/api/storage/{key}` | Read app-scoped storage |
| `PUT` | `/api/storage/{key}` | Write app-scoped storage |
| `DELETE` | `/api/storage/{key}` | Delete app-scoped storage |

Storage routes are unavailable when storage mode is `none`. Keys are opaque to
the runtime except for UTF-8 length and reserved-prefix checks. An app cannot
address another app's storage namespace.

`POST /api/actions/{action_id}/runs` returns `202` with `{run_id, status,
events_url}`. A caller-supplied `Idempotency-Key` scopes to the app, action, and
authenticated launch session for 24 hours. Reuse with a different input is a
`409 RUN_IDEMPOTENCY_CONFLICT`.

## 3. SSE wire format

The events endpoint responds with `text/event-stream`, `Cache-Control:
no-store`, and buffering disabled. Each event is encoded as:

```text
id: <seq>
event: <type>
data: <one-line JSON event envelope>

```

The JSON envelope MUST validate against `runtime-event.schema.json`. The SSE
`id` MUST equal the envelope `seq`, and the SSE `event` MUST equal the envelope
`type`. JSON is UTF-8 without NaN or Infinity.

For one `run_id`, `seq` starts at 1 and increases by exactly 1. `run.accepted`
is first. `run.started` occurs at most once and precedes operation, text, data,
usage, and terminal events. `heartbeat` may occur while queued or running and
also consumes a sequence number.

## 4. Event semantics

- `status` is sanitized user-facing progress. It never exposes prompts,
  credentials, raw tool arguments, or hidden reasoning.
- `text.delta` is append-only UTF-8 text.
- `data.snapshot` replaces the client's materialized data value.
- `data.delta.patch` is an ordered RFC 6902-compatible subset containing only
  `add`, `remove`, and `replace`. It applies atomically to the latest snapshot.
- `operation.*` reports a sanitized unit of work. `operation_id` is unique
  within a run. Started operations have at most one completed event.
- `usage.updated` is cumulative and never decreases. `total_tokens` equals
  `input_tokens + output_tokens`.
- Exactly one of `run.completed`, `run.failed`, or `run.cancelled` MUST occur.
  It is the final persisted event. No event may be appended afterward.
- `run.completed.result` MUST validate against the action's output schema.
  Inputs are validated before `run.accepted`; invalid input receives an HTTP
  error and creates no run stream.

## 5. Resume and retention

Clients resume with the standard `Last-Event-ID` header. AppHost replays events
strictly after that sequence, then continues live delivery without gaps or
duplicates. A sequence greater than the latest event is `400
RUN_EVENT_SEQUENCE_INVALID`.

AppHost retains at least the newest 500 events and at least five minutes of
event history after terminal completion, whichever retains more. If the
requested sequence has expired, it returns `410 RUN_EVENT_HISTORY_EXPIRED`;
the client then fetches the run snapshot and may reconnect from its reported
`latest_seq`.

While no domain event is emitted, AppHost sends a `heartbeat` every 15 seconds.
The client reconnect delay is three seconds with exponential backoff capped at
30 seconds. A terminal event closes the stream after it is flushed.

## 6. Cancellation and failure

Cancellation is cooperative. `DELETE` returns `202` while cancellation is
pending and `200` once terminal. Repeated cancellation requests are safe. A
race that completes successfully before cancellation is observed ends with
`run.completed`; the runtime never emits two terminal events.

Errors use stable uppercase codes, a safe message, a retryable flag, and
optional sanitized details. Raw provider responses, stack traces, local paths,
secrets, prompts, and tool arguments MUST NOT cross the Runtime boundary.

## 7. Compatibility

Clients MUST reject an unsupported `protocol_version`. Adding an event type,
changing event order, changing terminal semantics, or changing the meaning of
an existing payload requires protocol version 2. Adding an optional property is
also breaking in v1 because event payload schemas reject unknown properties.
