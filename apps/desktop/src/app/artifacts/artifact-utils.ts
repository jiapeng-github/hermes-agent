import { readDesktopFileDataUrl } from '@/lib/desktop-fs'
import { filePathFromMediaPath, isRemoteGateway, mediaExternalUrl } from '@/lib/media'
import type { AppActivityArtifact, SessionInfo, SessionMessage } from '@/types/hermes'

export type ArtifactKind = 'image' | 'file' | 'link'
export type ArtifactFilter = 'all' | ArtifactKind
export const ARTIFACT_FILTERS: readonly ArtifactFilter[] = ['all', 'image', 'file', 'link']

export interface ArtifactRecord {
  id: string
  kind: ArtifactKind
  value: string
  href: string
  label: string
  profile: string
  sessionId: string
  sessionTitle: string
  timestamp: number
  appActivityArtifactId?: string
}

export interface ArtifactLoadFailure {
  error: unknown
  session: SessionInfo
}

export interface ArtifactLoadResult {
  artifacts: ArtifactRecord[]
  failures: ArtifactLoadFailure[]
}

const MARKDOWN_IMAGE_RE = /!\[([^\]]*)\]\(([^)\s]+)\)/g
const MARKDOWN_LINK_RE = /\[([^\]]+)\]\(([^)\s]+)\)/g
const URL_RE = /https?:\/\/[^\s<>"')]+/g
const PATH_RE = /(^|[\s("'`])((?:(?:[a-z]:[\\/])|\/|~\/|\.\.?\/)[^\s"'`<>]+(?:\.[a-z0-9]{1,8})?)/gi
const IMAGE_EXT_RE = /\.(?:png|jpe?g|gif|webp|svg|bmp)(?:\?.*)?$/i
const FILE_EXT_RE =
  /\.(?:png|jpe?g|gif|webp|svg|bmp|html?|pdf|docx?|xlsx?|pptx?|txt|json|md|csv|zip|tar|gz|mp3|wav|mp4|mov)(?:\?.*)?$/i

function artifactSessionTitle(session: SessionInfo): string {
  return session.title?.trim() || session.preview?.trim() || 'Untitled session'
}

function normalizeValue(value: string): string {
  return value.trim().replace(/[),.;]+$/, '')
}

function parseMaybeJson(value: string): unknown {
  if (!value.trim()) {
    return null
  }

  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

function looksLikePathOrUrl(value: string): boolean {
  return (
    value.startsWith('http://') ||
    value.startsWith('https://') ||
    value.startsWith('file://') ||
    value.startsWith('data:image/') ||
    value.startsWith('/') ||
    value.startsWith('./') ||
    value.startsWith('../') ||
    value.startsWith('~/') ||
    /^[a-z]:[\\/]/i.test(value)
  )
}

function looksLikeArtifact(value: string): boolean {
  if (/^(?:https?:\/\/|data:image\/)/.test(value)) {
    return true
  }

  if (looksLikePathOrUrl(value) && (IMAGE_EXT_RE.test(value) || FILE_EXT_RE.test(value))) {
    return true
  }

  return (value.startsWith('/') || /^[a-z]:[\\/]/i.test(value)) && value.includes('.')
}

function artifactKind(value: string): ArtifactKind {
  if (value.startsWith('data:image/') || IMAGE_EXT_RE.test(value)) {
    return 'image'
  }

  if (
    value.startsWith('/') ||
    value.startsWith('./') ||
    value.startsWith('../') ||
    value.startsWith('~/') ||
    value.startsWith('file://') ||
    /^[a-z]:[\\/]/i.test(value)
  ) {
    return 'file'
  }

  return 'link'
}

function artifactHref(value: string): string {
  if (value.startsWith('http://') || value.startsWith('https://') || value.startsWith('data:')) {
    return value
  }

  if (value.startsWith('file://') || value.startsWith('/') || /^[a-z]:[\\/]/i.test(value)) {
    return mediaExternalUrl(value)
  }

  return value
}

export async function artifactImageSrc(value: string, href = artifactHref(value)): Promise<string> {
  if (/^(?:https?|data):/i.test(value)) {
    return href
  }

  if (typeof window !== 'undefined' && window.hermesDesktop && isRemoteGateway()) {
    return readDesktopFileDataUrl(filePathFromMediaPath(value))
  }

  return href
}

function artifactLabel(value: string): string {
  try {
    const url = new URL(value)
    const item = url.pathname.split('/').filter(Boolean).pop()

    return item || value
  } catch {
    const parts = value.split(/[\\/]/).filter(Boolean)

    return parts.pop() || value
  }
}

function messageText(message: SessionMessage): string {
  if (typeof message.content === 'string' && message.content.trim()) {
    return message.content
  }

  if (typeof message.text === 'string' && message.text.trim()) {
    return message.text
  }

  if (typeof message.context === 'string' && message.context.trim()) {
    return message.context
  }

  return ''
}

function collectArtifactsFromText(text: string, pushValue: (value: string) => void): void {
  for (const match of text.matchAll(MARKDOWN_IMAGE_RE)) {
    pushValue(match[2] || '')
  }

  for (const match of text.matchAll(MARKDOWN_LINK_RE)) {
    const start = match.index ?? 0

    if (start > 0 && text[start - 1] === '!') {
      continue
    }

    const value = match[2] || ''

    if (looksLikeArtifact(value)) {
      pushValue(value)
    }
  }

  for (const match of text.matchAll(URL_RE)) {
    const value = match[0] || ''

    if (looksLikeArtifact(value)) {
      pushValue(value)
    }
  }

  for (const match of text.matchAll(PATH_RE)) {
    pushValue(match[2] || '')
  }
}

function collectArtifactsFromMessage(message: SessionMessage, pushValue: (value: string) => void): void {
  const text = messageText(message)

  if (message.role === 'assistant' && text) {
    collectArtifactsFromText(text, pushValue)
  }

  if (message.role !== 'tool' || (message.tool_name || message.name) !== 'image_generate') {
    return
  }

  const parsed = parseMaybeJson(text)

  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return
  }

  const result = parsed as Record<string, unknown>

  if (result.success === false || result.status === 'error') {
    return
  }

  for (const key of ['host_image', 'image', 'agent_visible_image'] as const) {
    if (typeof result[key] === 'string') {
      pushValue(result[key])
      return
    }
  }
}

export function collectArtifactsForSession(session: SessionInfo, messages: SessionMessage[]): ArtifactRecord[] {
  const found = new Map<string, ArtifactRecord>()
  const title = artifactSessionTitle(session)
  const profile = session.profile || 'default'

  for (const message of messages) {
    if (message.role !== 'assistant' && message.role !== 'tool') {
      continue
    }

    collectArtifactsFromMessage(message, candidate => {
      const value = normalizeValue(candidate)

      if (!value || !looksLikeArtifact(value)) {
        return
      }

      const key = `${profile}:${session.id}:${value}`

      if (found.has(key)) {
        return
      }

      found.set(key, {
        id: key,
        kind: artifactKind(value),
        value,
        href: artifactHref(value),
        label: artifactLabel(value),
        profile,
        sessionId: session.id,
        sessionTitle: title,
        timestamp: message.timestamp || session.last_active || session.started_at || Date.now()
      })
    })
  }

  return Array.from(found.values())
}

export function artifactFromAppActivity(session: SessionInfo, artifact: AppActivityArtifact): ArtifactRecord {
  const profile = session.profile || 'default'
  const value = artifact.file_path

  return {
    id: `app:${profile}:${artifact.id}`,
    kind: 'file',
    value,
    href: artifactHref(value),
    label: artifact.title?.trim() || artifactLabel(value),
    profile,
    sessionId: session.id,
    sessionTitle: artifactSessionTitle(session),
    timestamp: artifact.created_at || session.last_active || session.started_at || Date.now(),
    appActivityArtifactId: artifact.id
  }
}

function canonicalArtifactValue(artifact: ArtifactRecord): string {
  if (artifact.kind === 'link') {
    try {
      const url = new URL(artifact.value)
      url.hash = ''

      return url.toString()
    } catch {
      return artifact.value
    }
  }

  const normalized = artifact.value
    .replace(/^file:\/\//i, '')
    .replace(/\\/g, '/')
    .replace(/\/+$/, '')

  return /^[a-z]:\//i.test(normalized) ? normalized.toLowerCase() : normalized
}

export function mergeArtifacts(records: readonly ArtifactRecord[]): ArtifactRecord[] {
  const found = new Map<string, ArtifactRecord>()

  for (const artifact of [...records].sort((left, right) => right.timestamp - left.timestamp)) {
    const key = `${artifact.profile}:${artifact.kind}:${canonicalArtifactValue(artifact)}`

    if (!found.has(key)) {
      found.set(key, artifact)
    }
  }

  return Array.from(found.values()).sort((left, right) => right.timestamp - left.timestamp)
}

export async function loadArtifactsForSessions(
  sessions: SessionInfo[],
  loadMessages: (session: SessionInfo) => Promise<SessionMessage[]>
): Promise<ArtifactLoadResult> {
  const artifacts: ArtifactRecord[] = []
  const failures: ArtifactLoadFailure[] = []

  // Keep only one transcript resident at a time. Recent sessions can each be
  // tens of megabytes, so loading the whole page concurrently can exhaust both
  // the Desktop renderer and a remote dashboard backend.
  for (const session of sessions) {
    try {
      const messages = await loadMessages(session)
      artifacts.push(...collectArtifactsForSession(session, messages))
    } catch (error) {
      failures.push({ error, session })
    }
  }

  return { artifacts, failures }
}
