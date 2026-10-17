// L'adaptateur Unipile du port `hostedLinks`, contre un faux `fetch` : corps exact du lien hébergé, lecture de toutes les
// pages de comptes, filtre du fournisseur, dates normalisées, états de la sonde, et jamais la clé dans une erreur.
import { describe, expect, it } from "vitest"
import { normalizeCreatedAt, unipileHostedLinks, UnipileHostedLinkError } from "../src"

const KEY = "sk_test_DO_NOT_LEAK_42"

type Seen = { url: string; init: RequestInit }

function fake(reply: (url: string, init: RequestInit) => Response | Promise<Response>) {
  const seen: Seen[] = []
  const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    seen.push({ url, init: init ?? {} })
    return reply(url, init ?? {})
  }) as typeof fetch
  return { seen, links: unipileHostedLinks({ apiKey: () => KEY, provider: "linkedin", fetch: fetcher }) }
}

const ok = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } })
const expiresAt = new Date("2026-10-17T12:30:00.000Z")

describe("createLink", () => {
  it("should post the exact body of a create link", async () => {
    const { seen, links } = fake(() => ok({ object: "HostedAuthUrl", link: "https://account.unipile.com/abc" }))
    const out = await links.createLink({ requestId: "req-1", kind: "create", returnUrl: "https://app.example/back", expiresAt })
    expect(out).toEqual({ url: "https://account.unipile.com/abc" })
    expect(seen).toHaveLength(1)
    expect(seen[0]?.url).toBe("https://api.unipile.com/v2/auth/link")
    expect(seen[0]?.init.method).toBe("POST")
    expect(seen[0]?.init.redirect).toBe("manual")
    expect((seen[0]?.init.headers as Record<string, string>)["X-API-KEY"]).toBe(KEY)
    expect(JSON.parse(String(seen[0]?.init.body))).toEqual({
      type: "create",
      providers: ["linkedin"],
      api_url: "https://api.unipile.com",
      expires_on: "2026-10-17T12:30:00.000Z",
      redirect_uri: "https://app.example/back",
      name: "req-1",
    })
  })

  it("should post the exact body of a reconnect link", async () => {
    const { seen, links } = fake(() => ok({ link: "https://account.unipile.com/def" }))
    await links.createLink({ requestId: "req-2", kind: "reconnect", linkedId: "acc_9", returnUrl: "https://app.example/back", expiresAt })
    expect(JSON.parse(String(seen[0]?.init.body))).toEqual({
      type: "reconnect",
      providers: ["linkedin"],
      api_url: "https://api.unipile.com",
      expires_on: "2026-10-17T12:30:00.000Z",
      redirect_uri: "https://app.example/back",
      name: "req-2",
      reconnect_account: "acc_9",
    })
  })

  it("should refuse a reconnect without linkedId before any call", async () => {
    const { seen, links } = fake(() => ok({ link: "x" }))
    await expect(links.createLink({ requestId: "r", kind: "reconnect", returnUrl: "https://a.example", expiresAt })).rejects.toMatchObject({ code: "invalid_input" })
    expect(seen).toHaveLength(0)
  })

  it("should raise a named error without the key nor the body", async () => {
    const { links } = fake(() => new Response(`{"detail":"bad key ${KEY}"}`, { status: 401 }))
    const error = await links.createLink({ requestId: "r", kind: "create", returnUrl: "https://a.example", expiresAt }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(UnipileHostedLinkError)
    expect(error).toMatchObject({ code: "http_error", status: 401, operation: "createLink" })
    expect(String((error as Error).message)).not.toContain(KEY)
    expect(String((error as Error).message)).not.toContain("bad key")
    expect(JSON.stringify(error)).not.toContain(KEY)
  })

  it("should refuse a redirect and an empty link", async () => {
    const redirect = fake(() => new Response(null, { status: 302, headers: { location: "https://elsewhere.example" } }))
    await expect(redirect.links.createLink({ requestId: "r", kind: "create", returnUrl: "https://a.example", expiresAt })).rejects.toMatchObject({ code: "redirect_refused" })
    const empty = fake(() => ok({}))
    await expect(empty.links.createLink({ requestId: "r", kind: "create", returnUrl: "https://a.example", expiresAt })).rejects.toMatchObject({ code: "empty_link" })
  })
})

describe("listAccounts", () => {
  const account = (i: number, provider = "linkedin") => ({ id: `acc-${String(i).padStart(3, "0")}`, provider, created_at: "2026-07-16T11:00:49.019Z" })

  it("should read every page by offset and find the 25th account", async () => {
    const all = Array.from({ length: 25 }, (_, i) => account(i + 1))
    const { seen, links } = fake((url) => {
      const offset = Number(new URL(url).searchParams.get("offset") ?? 0)
      const page = all.slice(offset, offset + 20)
      return ok({ object: "AccountList", data: page, has_more: offset + page.length < all.length })
    })
    const accounts = await links.listAccounts()
    expect(accounts.map((a) => a.id)).toContain("acc-025")
    expect(accounts).toHaveLength(25)
    expect(seen.map((s) => s.url)).toEqual(["https://api.unipile.com/v2/accounts", "https://api.unipile.com/v2/accounts?offset=20"])
  })

  it("should deduplicate and stop when upstream serves the same page again", async () => {
    const page = [account(1), account(2)]
    const { seen, links } = fake(() => ok({ data: page, has_more: true }))
    expect((await links.listAccounts()).map((a) => a.id)).toEqual(["acc-001", "acc-002"])
    expect(seen).toHaveLength(2)
  })

  it("should keep the requested provider only, whatever its case", async () => {
    const { links } = fake(() => ok({ data: [account(1, "LINKEDIN"), account(2, "whatsapp"), account(3, "LinkedIn"), { id: "acc-004", type: "LINKEDIN" }], has_more: false }))
    expect((await links.listAccounts()).map((a) => a.id)).toEqual(["acc-001", "acc-003", "acc-004"])
  })

  it("should normalise created_at to ISO 8601, or null", async () => {
    const dates: unknown[] = ["2026-07-16T11:00:49.019Z", "2026-07-16T11:00:49.019235123Z", 1784199649019, undefined, "yesterday"]
    const { links } = fake(() => ok({ data: dates.map((created_at, i) => ({ id: `a${i}`, provider: "linkedin", created_at })), has_more: false }))
    expect((await links.listAccounts()).map((a) => a.createdAt)).toEqual([
      "2026-07-16T11:00:49.019Z",
      "2026-07-16T11:00:49.019Z",
      new Date(1784199649019).toISOString(),
      null,
      null,
    ])
  })

  it("should read the space form, an offset, and Unix seconds", () => {
    expect(normalizeCreatedAt("2026-07-16 11:00:49.019235+00")).toBe("2026-07-16T11:00:49.019Z")
    expect(normalizeCreatedAt("2026-07-16T13:00:49+02:00")).toBe("2026-07-16T11:00:49.000Z")
    expect(normalizeCreatedAt(1784199649)).toBe("2026-07-16T11:00:49.000Z")
    expect(normalizeCreatedAt(null)).toBeNull()
  })

  it("should raise a named error without the key", async () => {
    const { links } = fake(() => new Response(`oops ${KEY}`, { status: 500 }))
    const error = await links.listAccounts().catch((e: unknown) => e)
    expect(error).toMatchObject({ code: "http_error", status: 500, operation: "listAccounts" })
    expect(String((error as Error).message)).not.toContain(KEY)
  })
})

describe("probe", () => {
  it("should say alive with the holder's name on 200", async () => {
    const { seen, links } = fake(() => ok({ object: "AccountOwnerProfile", first_name: "Jane", last_name: "Doe", public_identifier: "jane-doe" }))
    expect(await links.probe("acc_1-x")).toEqual({ state: "alive", label: "Jane Doe" })
    expect(seen[0]?.url).toBe("https://api.unipile.com/v2/acc_1-x/users/me")
  })

  it("should say dead on 401 only", async () => {
    expect(await fake(() => new Response(null, { status: 401 })).links.probe("acc1")).toEqual({ state: "dead" })
    expect(await fake(() => new Response(null, { status: 500 })).links.probe("acc1")).toEqual({ state: "unavailable" })
    expect(await fake(() => new Response(null, { status: 403 })).links.probe("acc1")).toEqual({ state: "unavailable" })
  })

  it("should say unavailable on a timeout or a network failure, never dead", async () => {
    const timeout = fake(() => { throw new DOMException("The operation timed out.", "TimeoutError") })
    expect(await timeout.links.probe("acc1")).toEqual({ state: "unavailable" })
    const down = fake(() => { throw new TypeError("fetch failed") })
    expect(await down.links.probe("acc1")).toEqual({ state: "unavailable" })
  })

  it("should refuse an invalid id without any call", async () => {
    const { seen, links } = fake(() => ok({}))
    for (const id of ["", "../accounts", "a/b", "a".repeat(129), "acc 1"]) {
      await expect(links.probe(id)).rejects.toMatchObject({ code: "invalid_input" })
    }
    expect(seen).toHaveLength(0)
  })
})
