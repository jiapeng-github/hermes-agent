# Hermes App Package (`.happ`) Format v1

Status: **Frozen**
Contract version: `1.0.0`
Frozen on: `2026-07-12`

This document is normative. Keywords **MUST**, **MUST NOT**, **SHOULD**, and
**MAY** are interpreted as requirements. A `.happ` package is a portable local
Hermes web application; it never contains executable server-side code,
credentials, permission grants, logs, or application data.

## 1. Container

- The file extension MUST be `.happ` and the content MUST be a ZIP archive.
- Writers MUST use stored or DEFLATE entries and UTF-8 names. Encryption is
  forbidden. Readers MUST support ZIP64 but still enforce the limits below.
- Root files `happ.json`, `app.yaml`, and `checksums.json` are required.
- `signature.json` is optional and is present only when `happ.json.signature`
  equals `signature.json`.
- The package MAY contain `icon.*`, `dist/`, `prompts/`, `schemas/`, `assets/`,
  `tests/`, `screenshots/`, and `source/`. Files outside these roots are
  rejected. `source/` is optional; absence makes the installed version
  read-only in the application editor.
- `happ.json`, `checksums.json`, and `signature.json` MUST validate against
  their matching definitions in `happ-package.schema.json`. `app.yaml` MUST
  validate against `app-manifest.schema.json`.
- `happ.json.app_id` and `app_version` MUST exactly match `app.yaml.id` and
  `app.yaml.version`. `source_included` MUST exactly match whether at least one
  regular file is present under `source/`.

## 2. Path safety and portability

Every entry name MUST use `/`, be valid UTF-8 in Unicode NFC form, be at most
1024 UTF-8 bytes, and consist of components no longer than 255 UTF-8 bytes.
Readers MUST reject an archive containing any of the following:

- an absolute path, drive-qualified path, backslash, NUL, empty component,
  `.` component, or `..` component;
- a component ending in a space or period;
- a Windows device-name component (`CON`, `PRN`, `AUX`, `NUL`, `COM1` through
  `COM9`, or `LPT1` through `LPT9`, with or without an extension);
- duplicate names after NFC normalization or duplicate names under Unicode
  case folding;
- a symlink, hard link, socket, FIFO, block device, or character device.

Extraction MUST first validate all central-directory entries, then write only
regular files beneath a newly-created staging directory. Readers MUST NOT call
an unguarded archive-wide extraction operation.

## 3. Resource limits

- Compressed archive size: at most `52,428,800` bytes (50 MiB).
- Total uncompressed regular-file size: at most `209,715,200` bytes (200 MiB).
- Entries: at most `5,000`, including directory entries.
- One uncompressed regular file: at most `52,428,800` bytes (50 MiB).
- For any regular file of at least 1 MiB, the uncompressed-to-compressed ratio
  MUST NOT exceed `200:1`. A non-empty file with compressed size zero is
  rejected.

The reader MUST enforce limits from metadata before extraction and again while
streaming bytes, because ZIP metadata is untrusted.

## 4. Checksums and canonical form

`checksums.json.files` MUST contain exactly one entry for every regular file
except `checksums.json` and `signature.json`. It therefore includes at least
`happ.json`, `app.yaml`, and the manifest icon. Entries MUST be ordered by the
UTF-8 byte sequence of `path`. Each `size` and lowercase SHA-256 digest MUST
match the streamed file content. Directory entries are not listed.

Writers MUST serialize `checksums.json` as UTF-8 JSON with sorted object keys,
no insignificant whitespace, and one trailing LF. This canonical byte form is
the input to an optional package signature.

When present, `signature.json` MUST validate against the `signature` definition
and MUST contain an Ed25519 signature over the exact canonical bytes of
`checksums.json`. Phase 1 accepts unsigned packages as **untrusted local apps**.
A valid signature identifies a publisher; it does not grant runtime
permissions.

## 5. Export exclusions

Exports MUST exclude runtime data, caches, run history, logs, credentials,
cookies, launch codes, CSRF tokens, permission grants, and trust decisions.
The `source/` tree is included only when the caller explicitly requests source
and the active version has editable source.

## 6. Two-phase import

Import is always two-phase:

1. **Analyze** validates the archive, schemas, checksums, compatibility,
   requested capabilities, signature state, and ID/version conflicts. It
   returns an immutable import plan with a short expiry and makes no installed
   application changes.
2. **Confirm** accepts the plan ID plus the user's conflict decision and exact
   permission grants. It re-verifies the staged bytes before an atomic install.

An existing application ID requires either `update` or `copy`. `copy` assigns a
new reverse-DNS ID and rewrites the installed manifest. The same ID and version
with different checksums MUST NOT be silently overwritten. Failed or expired
plans MUST delete their staging data.

## 7. Compatibility

Readers MUST reject unknown `format_version` values. Any change to required
files, path rules, checksum canonicalization, signing input, security limits,
or import semantics requires `.happ` format version 2. Optional metadata can be
added only when v1 readers are already defined to ignore it; v1 metadata
schemas otherwise reject unknown properties.
