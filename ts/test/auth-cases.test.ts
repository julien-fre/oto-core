// Les cas communs de l'authentification (`src/auth-cases.ts`, sortis par la fabrique de `connectors/_cases/auth.yaml`) :
// des données que le paquet de l'hôte joue contre son moteur. Ici, leur forme, et une référence qui les rejoue : `basic`
// sans `username` signe d'un identifiant vide.
import { describe, expect, it } from "vitest"
import { authCases } from "../src/auth-cases"
import type { Auth } from "../src/types"

function base64Utf8(text: string): string {
  return btoa(String.fromCharCode(...new TextEncoder().encode(text)))
}

/** La référence : les en-têtes (noms en minuscules) et la query qu'ajoute l'authentification. */
function signed(auth: Auth, values: { readonly [field: string]: string }): [Record<string, string>, Record<string, string>] {
  const value = (field: string): string => {
    const found = values[field]
    if (found === undefined) throw new Error(`no value for ${field}`)
    return found
  }
  switch (auth.kind) {
    case "basic": {
      const username = auth.username === undefined ? "" : value(auth.username)
      return [{ authorization: `Basic ${base64Utf8(`${username}:${value(auth.password)}`)}` }, {}]
    }
    case "bearer":
      return [{ authorization: `Bearer ${value(auth.token)}` }, {}]
    case "api_key":
      return auth.in === "query"
        ? [{}, { [auth.name]: value(auth.key) }]
        : [{ [auth.name.toLowerCase()]: (auth.prefix ?? "") + value(auth.key) }, {}]
    default:
      throw new Error(`not a case kind: ${auth.kind}`)
  }
}

describe("auth cases", () => {
  it("should carry a basic auth without username", () => {
    const without = authCases.filter((c) => c.auth.kind === "basic" && !("username" in c.auth))
    expect(without.length).toBeGreaterThan(0)
  })

  it.each(authCases.map((c) => [c.name, c] as const))("%s: a value per credential field, the headers it adds", (_name, c) => {
    expect(Object.keys(c.values).sort()).toEqual(c.credential.map((f) => f.name).sort())
    expect(signed(c.auth, c.values)).toEqual([c.headers, c.query])
  })
})
