// Adaptateur du port `hostedLinks` pour Unipile, écrit à la main (pas généré par la fabrique).
// Un tiers qui héberge les comptes de ses utilisateurs (ici, la session LinkedIn d'un membre) les connecte par un lien
// hébergé : l'hôte demande un lien, la personne s'y connecte, l'hôte retrouve le compte créé dans la liste des comptes,
// puis sonde sa session. La clé est celle de l'hôte : la lib ne la lit jamais, l'hôte la passe par `apiKey`, appelée à
// chaque requête. Base fixe, délai fixe, aucune redirection suivie ; une erreur ne porte ni la clé ni le corps reçu.

/** Le port `hostedLinks`, tel qu'oto-core le définit (recopié comme type structurel : la lib n'importe pas oto-core). */
export interface HostedLinkProvider {
  createLink(input: {
    requestId: string
    kind: "create" | "reconnect"
    linkedId?: string
    returnUrl: string
    expiresAt: Date
  }): Promise<{ url: string }>
  listAccounts(): Promise<Array<{ id: string; createdAt: string | null }>>
  probe(id: string): Promise<{ state: "alive"; label: string } | { state: "dead" } | { state: "unavailable" }>
}

export type UnipileHostedLinksOptions = {
  /** La clé `X-API-KEY` de l'hôte, lue à chaque appel ; jamais gardée ni lue ailleurs par la lib. */
  readonly apiKey: () => string
  readonly provider: "linkedin"
  /** Le `fetch` à employer ; celui de l'environnement par défaut. */
  readonly fetch?: typeof fetch
}

export type UnipileHostedLinkErrorCode =
  | "invalid_input"
  | "missing_api_key"
  | "http_error"
  | "redirect_refused"
  | "network_error"
  | "empty_link"
  | "invalid_response"

/** Une erreur de `createLink`, de `listAccounts`, ou un id refusé par `probe` : un code, l'opération, le statut HTTP s'il y en a un ; ni la clé, ni le corps. */
export class UnipileHostedLinkError extends Error {
  readonly code: UnipileHostedLinkErrorCode
  readonly operation: string
  readonly status?: number

  constructor(operation: string, code: UnipileHostedLinkErrorCode, detail: string, status?: number) {
    super(`Unipile ${operation}: ${detail}`)
    this.name = "UnipileHostedLinkError"
    this.code = code
    this.operation = operation
    if (status !== undefined) this.status = status
  }
}

const API_ROOT = "https://api.unipile.com"
const BASE_URL = `${API_ROOT}/v2`
const TIMEOUT_MS = 30_000
const ACCOUNT_ID = /^[A-Za-z0-9_-]{1,128}$/
/** Borne de la lecture des comptes : au-delà, l'amont annonce des pages sans fin. */
const MAX_PAGES = 500

type Fetch = typeof fetch

function key(operation: string, apiKey: () => string): string {
  const value = apiKey()
  if (typeof value !== "string" || value === "") throw new UnipileHostedLinkError(operation, "missing_api_key", "no API key supplied by the host")
  return value
}

async function call(fetcher: Fetch, operation: string, apiKey: () => string, path: string, init: { method: string; body?: unknown }): Promise<Response> {
  const headers: Record<string, string> = { "X-API-KEY": key(operation, apiKey), accept: "application/json" }
  if (init.body !== undefined) headers["content-type"] = "application/json"
  try {
    return await fetcher(`${BASE_URL}${path}`, {
      method: init.method,
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      redirect: "manual",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    })
  } catch (error) {
    const kind = error instanceof Error && (error.name === "TimeoutError" || error.name === "AbortError") ? "timeout" : "network failure"
    throw new UnipileHostedLinkError(operation, "network_error", kind)
  }
}

async function json(response: Response, operation: string): Promise<unknown> {
  if (response.type === "opaqueredirect" || (response.status >= 300 && response.status < 400)) {
    throw new UnipileHostedLinkError(operation, "redirect_refused", "redirect refused", response.status || undefined)
  }
  if (!response.ok) throw new UnipileHostedLinkError(operation, "http_error", `HTTP ${response.status}`, response.status)
  try {
    return await response.json()
  } catch {
    throw new UnipileHostedLinkError(operation, "invalid_response", "response is not JSON", response.status)
  }
}

const record = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null

/**
 * Une date de compte en ISO 8601 (UTC, millisecondes), ou `null` si elle manque ou est illisible. Formes lues : ISO 8601
 * avec `Z` ou un décalage, fraction de seconde de 1 à 9 chiffres, forme à espace (`2026-07-16 11:00:49.019235+00`),
 * horodatage Unix en secondes ou en millisecondes.
 */
export function normalizeCreatedAt(value: unknown): string | null {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null
    const date = new Date(value > 1e11 ? value : value * 1000)
    return Number.isNaN(date.getTime()) ? null : date.toISOString()
  }
  if (typeof value !== "string") return null
  const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|z|[+-]\d{2}(?::?\d{2})?)?$/.exec(value.trim())
  if (!match) return null
  const [, day, time, fraction = "", zone = "Z"] = match
  let offset = "Z"
  if (zone !== "Z" && zone !== "z") {
    const digits = zone.slice(1).replace(":", "")
    offset = `${zone[0]}${digits.slice(0, 2)}:${digits.slice(2, 4) || "00"}`
  }
  const date = new Date(`${day}T${time}.${(fraction + "000").slice(0, 3)}${offset}`)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

function holderName(profile: Record<string, unknown>): string | null {
  const parts = [profile.first_name, profile.last_name].filter((p): p is string => typeof p === "string" && p.trim() !== "")
  if (parts.length) return parts.map((p) => p.trim()).join(" ")
  const fallback = [profile.name, profile.public_identifier].find((p): p is string => typeof p === "string" && p.trim() !== "")
  return fallback?.trim() ?? null
}

/** L'adaptateur Unipile du port `hostedLinks`, pour un fournisseur. */
export function unipileHostedLinks(options: UnipileHostedLinksOptions): HostedLinkProvider {
  const { apiKey, provider } = options
  const fetcher: Fetch = options.fetch ?? ((...args) => globalThis.fetch(...args))

  return {
    async createLink(input) {
      const operation = "createLink"
      if (input.kind === "reconnect" && !input.linkedId) {
        throw new UnipileHostedLinkError(operation, "invalid_input", "a reconnect link needs linkedId")
      }
      if (input.kind === "create" && input.linkedId !== undefined) {
        throw new UnipileHostedLinkError(operation, "invalid_input", "linkedId is only for a reconnect link")
      }
      if (Number.isNaN(input.expiresAt.getTime())) throw new UnipileHostedLinkError(operation, "invalid_input", "expiresAt is not a valid date")
      const body: Record<string, unknown> = {
        type: input.kind,
        providers: [provider],
        api_url: API_ROOT,
        expires_on: input.expiresAt.toISOString(),
        redirect_uri: input.returnUrl,
        name: input.requestId,
      }
      if (input.kind === "reconnect") body.reconnect_account = input.linkedId
      const data = record(await json(await call(fetcher, operation, apiKey, "/auth/link", { method: "POST", body }), operation))
      const url = data?.link ?? data?.url
      if (typeof url !== "string" || url === "") throw new UnipileHostedLinkError(operation, "empty_link", "no link in the response")
      return { url }
    },

    async listAccounts() {
      const operation = "listAccounts"
      const out: Array<{ id: string; createdAt: string | null }> = []
      const seen = new Set<string>()
      let offset = 0
      let previous: string | null = null
      for (let page = 0; page < MAX_PAGES; page++) {
        const path = offset ? `/accounts?offset=${offset}` : "/accounts"
        const data = await json(await call(fetcher, operation, apiKey, path, { method: "GET" }), operation)
        const envelope = record(data)
        const items = Array.isArray(data) ? data : Array.isArray(envelope?.data) ? envelope.data : Array.isArray(envelope?.items) ? envelope.items : null
        if (items === null) throw new UnipileHostedLinkError(operation, "invalid_response", "no account list in the response")
        if (!items.length) break
        const ids = JSON.stringify(items.map((item) => record(item)?.id ?? item))
        if (ids === previous) break // l'amont ressert la même page : `offset` n'avance plus
        previous = ids
        for (const item of items) {
          const account = record(item)
          const id = account?.id
          if (!account || typeof id !== "string" || seen.has(id)) continue
          seen.add(id)
          const kind = String(account.provider ?? account.type ?? "").trim().toLowerCase()
          if (kind !== provider) continue
          out.push({ id, createdAt: normalizeCreatedAt(account.created_at) })
        }
        if (Array.isArray(data) || envelope?.has_more !== true) break
        offset += items.length
      }
      return out
    },

    async probe(id) {
      if (typeof id !== "string" || !ACCOUNT_ID.test(id)) throw new UnipileHostedLinkError("probe", "invalid_input", "the account id does not match ^[A-Za-z0-9_-]{1,128}$")
      let response: Response
      try {
        response = await call(fetcher, "probe", apiKey, `/${encodeURIComponent(id)}/users/me`, { method: "GET" })
      } catch {
        return { state: "unavailable" }
      }
      if (response.status === 401) return { state: "dead" }
      if (response.status !== 200 || response.type === "opaqueredirect") return { state: "unavailable" }
      let profile: Record<string, unknown> | null
      try {
        profile = record(await response.json())
      } catch {
        return { state: "unavailable" }
      }
      return { state: "alive", label: (profile && holderName(profile)) ?? id }
    },
  }
}
