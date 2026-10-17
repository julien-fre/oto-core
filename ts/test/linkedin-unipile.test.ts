// Le compte de l'hôte et le compte rattaché, lus dans la définition générée de `linkedin_unipile` : la clé est celle de
// l'application hôte (`holder: "host"`), le compte est l'identifiant du membre chez Unipile, cité par l'adresse de base
// seulement. L'hôte assemble à l'appel sa clé et l'identité du compte ; l'agent ne fournit jamais l'identité.
import { describe, expect, it } from "vitest"
import { linkedinUnipile } from "../src"

describe("linkedin_unipile definitions", () => {
  it("should hold the API key at the host and cite the account identity in the base URL", () => {
    const connector = linkedinUnipile.connector
    expect(connector.credential).toEqual([{ name: "api_key", label: "Unipile API key", secret: true, holder: "host" }])
    expect(connector.accountIdentity).toEqual({ name: "account_id", label: "LinkedIn account", pattern: "^[A-Za-z0-9_-]{1,64}$" })
    expect(connector.baseUrl).toBe("https://api.unipile.com/v2/{account_id}")
    expect(connector.auth).toEqual({ kind: "api_key", in: "header", name: "X-API-KEY", key: "api_key" })
    expect(connector.probe?.function).toBe("linkedin_unipile.get_me")
  })

  it("should serve the reads outside the act side", () => {
    for (const fn of [linkedinUnipile.getMe, linkedinUnipile.getProfile, linkedinUnipile.listRelations]) expect(fn.act).toBe(false)
  })

  it("should accept an identifier the pattern allows and refuse one it does not", () => {
    const pattern = new RegExp(linkedinUnipile.connector.accountIdentity.pattern)
    expect(pattern.test("aB3_x-9")).toBe(true)
    expect(pattern.test("../users")).toBe(false)
    expect(pattern.test("")).toBe(false)
  })

  it("should confirm the sensitive functions before running them", () => {
    for (const fn of [linkedinUnipile.sendInvitation, linkedinUnipile.sendMessage]) {
      expect(fn.class).toBe("sensitive")
      expect(fn.act).toBe(true)
      expect(fn.confirm?.summary.length).toBeGreaterThan(0)
    }
  })
})
