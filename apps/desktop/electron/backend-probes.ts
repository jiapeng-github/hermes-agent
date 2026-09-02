/**
 * backend-probes.ts
 *
 * Cheap "does this candidate backend actually work" checks used by
 * resolveHermesBackend (main.ts). The resolver walks a ladder of
 * candidates -- bootstrap marker, `hermes` on PATH, system Python with
 * hermes_cli installed -- and historically returned the first candidate
 * whose binary existed on disk. That assumption breaks when a user has
 * a pre-installed Python 3.11-3.13 (so findSystemPython() returns a
 * path) but no hermes_cli in its site-packages: the resolver hands back
 * a backend the spawn step can't actually run, and the user gets a
 * dead-on-arrival "ModuleNotFoundError: No module named 'hermes_cli'"
 * instead of the first-launch installer.
 *
 * These probes give the resolver a way to verify a candidate before
 * trusting it. Failure (non-zero exit, exception, timeout) means "skip
 * this rung, try the next one"; success means "spawn this for real."
 * Falling off the bottom of the ladder lands on the bootstrap-needed
 * sentinel, which is exactly what we want when nothing pre-existing
 * actually works.
 *
 * Both probes are deliberately fast and forgiving:
 *   - default 15s timeout (5s was too short on cold Windows disks / AV;
 *     issue #61764 death-loop) with HERMES_PROBE_TIMEOUT_MS override
 *   - one automatic retry after a timeout before declaring the runtime dead
 *   - stdio ignored (we only care about exit code; stdout/stderr are
 *     not surfaced to the user, just to recentHermesLog for forensics
 *     via the caller's catch block if it chooses)
 *   - any throw -> false (never propagate -- resolver wants a boolean)
 *
 * Kept in a standalone ts module so it can be unit-tested with
 * `node --test` without dragging in the electron runtime (same pattern
 * as bootstrap-platform.ts and hardening.ts).
 */

import { execFileSync } from 'node:child_process'

/** Default probe budget. 5s false-negativeed healthy Windows cold starts (#61764). */
const DEFAULT_PROBE_TIMEOUT_MS = 15_000

/**
 * Resolve the backend probe timeout (ms).
 * Honours HERMES_PROBE_TIMEOUT_MS when it parses as a positive integer.
 */
function resolveProbeTimeoutMs(env: NodeJS.ProcessEnv = process.env): number {
  const raw = env.HERMES_PROBE_TIMEOUT_MS

  if (raw == null || raw === '') {
    return DEFAULT_PROBE_TIMEOUT_MS
  }

  const n = Number.parseInt(String(raw), 10)

  if (!Number.isFinite(n) || n <= 0) {
    return DEFAULT_PROBE_TIMEOUT_MS
  }

  // Clamp absurd values (ms) so a typo can't hang startup forever.
  return Math.min(n, 120_000)
}

const PROBE_TIMEOUT_MS = resolveProbeTimeoutMs()

function isTimeoutError(err: unknown): boolean {
  if (!err || typeof err !== 'object') {
    return false
  }

  const e = err as { code?: string; killed?: boolean; signal?: string }

  if (e.killed === true) {
    return true
  }

  if (e.code === 'ETIMEDOUT') {
    return true
  }

  // Node marks timed-out execFileSync with SIGTERM on some platforms.
  if (e.signal === 'SIGTERM') {
    return true
  }

  return false
}

/**
 * Run execFileSync; on timeout only, retry once before failing.
 * Non-timeout failures (ENOENT, non-zero exit) fail immediately.
 */
function execProbeSync(
  command: string,
  args: string[],
  options: {
    cwd?: string
    env?: NodeJS.ProcessEnv
    stdio: 'ignore'
    timeout: number
    shell?: boolean
    windowsHide?: boolean
  }
): void {
  try {
    execFileSync(command, args, options)
  } catch (err) {
    if (!isTimeoutError(err)) {
      throw err
    }

    // One cold-cache / AV miss should not force hermes-setup --update (#61764).
    execFileSync(command, args, options)
  }
}

/**
 * Return the Python snippet used to verify Hermes can import far enough to
 * launch the CLI. Kept exported for tests so dependency regressions are
 * caught without needing a real broken venv fixture.
 *
 * Two layers:
 *   1. `hermes_cli.config` + its third-party deps (yaml, dotenv) — the CLI
 *      boot path; a mid-update venv missing python-dotenv used to pass a
 *      shallower probe and produced an unrecoverable boot loop.
 *   2. `hermes_cli.apps.catalog` — the deepest eagerly-imported apps-module
 *      chain (apps/__init__ -> manager -> catalog -> siblings). A TORN
 *      install (e.g. catalog.py from a newer tree referencing a sibling
 *      module that was never written, observed as "ModuleNotFoundError:
 *      hermes_cli.apps.activity") passes layer 1 but dies at backend
 *      lifespan. Failing the probe here routes the resolver to bootstrap
 *      instead of spawning a backend that can only crash.
 *
 * Layer 2 is deliberately tolerant of OLDER installs: if
 * hermes_cli/apps/catalog.py does not exist as a file (the module postdates
 * that install), the tree is self-consistent for its era and the exception
 * is swallowed. Only a catalog.py that EXISTS but cannot be imported counts
 * as torn.
 *
 * @returns {string}
 */
// Kept as a named module constant (not an inline return) so the Python-side
// behavioral test (tests/test_desktop_runtime_probe.py) can extract these
// lines verbatim from this file's source text and execute the REAL probe
// against synthetic fixtures — the snippet can never drift from its tests.
const HERMES_RUNTIME_IMPORT_PROBE_LINES = [
  'import yaml; import dotenv; import hermes_cli.config',
  'try:',
  '    import hermes_cli.apps.catalog',
  'except BaseException:',
  '    import os, hermes_cli',
  '    if os.path.exists(os.path.join(os.path.dirname(hermes_cli.__file__), "apps", "catalog.py")):',
  '        raise'
]

function hermesRuntimeImportProbe() {
  return HERMES_RUNTIME_IMPORT_PROBE_LINES.join('\n')
}

/**
 * Return true iff the Hermes runtime import probe exits 0.
 *
 * Used to gate the "fallback to system Python with hermes_cli installed"
 * rung of resolveHermesBackend. Without this, a system Python 3.11-3.13
 * registered in PEP 514 makes findSystemPython() succeed regardless of
 * whether hermes_cli has actually been pip-installed into its
 * site-packages -- and the resolver returns a backend that immediately
 * dies on spawn.
 *
 * The probe intentionally imports hermes_cli.config, not just the top-level
 * package: a broken/empty Windows launcher venv can still see the source tree
 * through PYTHONPATH but lack PyYAML, then die on the first real CLI import.
 *
 * @param {string} pythonPath - Absolute path to a python.exe / python.
 * @param {object} [opts.env] - Additional environment for the probe.
 * @returns {boolean}
 */
function canImportHermesCli(pythonPath: string, opts: { env?: Record<string, string> } = {}) {
  if (!pythonPath) {
    return false
  }

  try {
    execProbeSync(pythonPath, ['-c', hermesRuntimeImportProbe()], {
      env: { ...process.env, ...(opts.env || {}) },
      stdio: 'ignore',
      timeout: PROBE_TIMEOUT_MS,
      windowsHide: true
    })

    return true
  } catch {
    return false
  }
}

/**
 * Return true iff `<hermesCommand> --version` exits 0.
 *
 * Used to gate the "existing `hermes` on PATH" rung. Without this, a
 * stale hermes.cmd shim left behind by an uninstalled pip install (or
 * a half-built venv whose `hermes` entry-point points at a deleted
 * Python) survives findOnPath() and gets selected as the backend.
 *
 * We intentionally avoid invoking the command with the dashboard args
 * here -- `--version` is the cheapest "is this binary alive" smoke
 * test that every hermes_cli entry-point has supported since 0.1.
 *
 * @param {string} hermesCommand - Resolved absolute path to a hermes
 *   executable (or an interpreter+script wrapper).
 * @param {boolean} [opts.shell] - Whether to run through a shell. For
 *   .cmd/.bat shims on Windows execFileSync needs shell:true to find
 *   the cmd interpreter; mirrors the same flag isCommandScript() drives
 *   in resolveHermesBackend.
 * @returns {boolean}
 */
/**
 * An explicit desktop backend command is a deployment contract, not a PATH
 * discovery candidate. In particular, the Nix desktop wrapper points this at
 * its immutable, matching Hermes package; it must never fall through to the
 * mutable install-script bootstrap path if a best-effort probe is slow.
 */
function shouldTrustHermesOverride(hermesOverride?: string) {
  return typeof hermesOverride === 'string' && hermesOverride.trim().length > 0
}

function verifyHermesCli(hermesCommand: string, opts?: { shell?: boolean }) {
  if (!hermesCommand) {
    return false
  }

  try {
    execProbeSync(hermesCommand, ['--version'], {
      stdio: 'ignore',
      timeout: PROBE_TIMEOUT_MS,
      shell: Boolean(opts?.shell),
      windowsHide: true
    })

    return true
  } catch {
    return false
  }
}

export {
  canImportHermesCli,
  DEFAULT_PROBE_TIMEOUT_MS,
  execProbeSync,
  hermesRuntimeImportProbe,
  PROBE_TIMEOUT_MS,
  resolveProbeTimeoutMs,
  shouldTrustHermesOverride,
  verifyHermesCli
}
