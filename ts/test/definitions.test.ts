// Chaque définition générée porte un nom qualifié et un JSON Schema d'entrée que valide un validateur JSON Schema 2020-12
// standard (Ajv) : ses exemples passent, une clé inconnue est refusée. `format` reste une annotation, comme dans le test
// des descriptions côté Python ; le mode strict d'Ajv signale tout mot-clé inconnu ou mal placé.
import { Ajv2020 } from "ajv/dist/2020.js"
import { describe, expect, it } from "vitest"
import { connectors } from "../src"

const ajv = new Ajv2020({ strictTypes: false, strictTuples: false, validateFormats: false, allErrors: true })
const functions = connectors.flatMap((connector) => connector.functions.map((fn) => [fn.name, connector, fn] as const))

describe("generated definitions", () => {
  it("should generate at least one function per connector", () => {
    for (const connector of connectors) expect(connector.functions.length, connector.name).toBeGreaterThan(0)
  })

  it.each(functions)("%s: qualified name, strict root, examples accepted, unknown key refused", (name, connector, fn) => {
    expect(name).toBe(`${connector.name}.${name.slice(connector.name.length + 1)}`)
    expect(fn.connector).toBe(connector.name)
    expect(fn.schema.type).toBe("object")
    expect(fn.schema.additionalProperties).toBe(false)
    const validate = ajv.compile(fn.schema)
    expect(fn.examples.length).toBeGreaterThan(0)
    for (const example of fn.examples) {
      expect(validate(example.input), `${example.title}: ${ajv.errorsText(validate.errors)}`).toBe(true)
    }
    const first = fn.examples[0]
    expect(validate({ ...first?.input, __unknown__: 1 })).toBe(false)
  })

  it.each(functions)("%s: every path parameter and mapped argument names a schema key", (_name, _connector, fn) => {
    const keys = Object.keys(fn.schema.properties as object)
    for (const param of fn.request.pathParams) expect(keys).toContain(param)
    for (const argument of [...Object.values(fn.request.query), ...Object.values(fn.request.body), ...Object.values(fn.request.headers)]) {
      expect(keys).toContain(argument)
    }
    for (const argument of Object.keys(fn.request.encode ?? {})) expect(keys).toContain(argument)
  })

  it.each(connectors.filter((c) => c.probe).map((c) => [c.name, c] as const))("%s: the probe is a read function callable with {}", (_name, connector) => {
    const probe = connector.functions.find((fn) => fn.name === connector.probe?.function)
    expect(probe?.class).toBe("read")
    expect(ajv.validate(probe?.schema as object, {})).toBe(true)
  })

  const consents = connectors.flatMap((c) => (c.auth.kind === "oauth2_user" ? [[c.name, c, c.auth] as const] : []))
  it.each(consents)("%s: the identity of a consent is a read function callable with {} or an https address, and no credential", (_name, connector, auth) => {
    if (auth.identity.url !== undefined) {
      expect(auth.identity.url).toMatch(/^https:\/\/[^\s{}?#]+$/)
      expect(auth.identity.scopes.length).toBeGreaterThan(0)
    } else {
      const identity = connector.functions.find((fn) => fn.name === auth.identity.function)
      expect(identity?.class).toBe("read")
      expect(ajv.validate(identity?.schema as object, {})).toBe(true)
    }
    expect(connector.credential).toEqual([])
  })

  // Niveaux d'accès : une fonction est servie à un niveau quand chacun de ses droits est un droit du niveau ou impliqué par
  // l'un d'eux. `full` sert tout ; l'identité du consentement est servie à chaque niveau ; sans niveaux, aucun droit.
  const covered = (scopes: readonly string[], implies: { readonly [scope: string]: readonly string[] }) =>
    new Set(scopes.flatMap((scope) => [scope, ...(implies[scope] ?? [])]))
  const leveled = consents.flatMap(([name, connector, auth]) => (auth.accessLevels ? [[name, connector, auth.accessLevels, auth.scopeImplies ?? {}, auth.identity] as const] : []))
  it.each(leveled)("%s: full serves every function, and every level serves the identity", (_name, connector, levels, implies, identity) => {
    const full = covered(levels.full.scopes, implies)
    for (const fn of connector.functions) {
      expect(fn.scopes?.length, fn.name).toBeGreaterThan(0)
      for (const scope of fn.scopes ?? []) expect(full.has(scope), `${fn.name}: ${scope}`).toBe(true)
    }
    const who = identity.url !== undefined ? identity.scopes : connector.functions.find((fn) => fn.name === identity.function)?.scopes
    expect(Object.keys(levels).length).toBeGreaterThan(1)
    for (const [level, { scopes }] of Object.entries(levels)) {
      const granted = covered(scopes, implies)
      for (const scope of who ?? ["(none)"]) expect(granted.has(scope), `${level}: ${scope}`).toBe(true)
    }
  })

  it.each(connectors.filter((c) => !(c.auth.kind === "oauth2_user" && c.auth.accessLevels)).map((c) => [c.name, c] as const))(
    "%s: without access levels, no function declares scopes",
    (_name, connector) => {
      for (const fn of connector.functions) expect(fn.scopes, fn.name).toBeUndefined()
    },
  )

  it.each(functions)("%s: act is resolved, never false when sensitive nor true when read", (_name, _connector, fn) => {
    expect(typeof fn.act).toBe("boolean")
    if (fn.class === "sensitive") expect(fn.act).toBe(true)
    if (fn.class === "read") expect(fn.act).toBe(false)
  })

  it.each(connectors.map((c) => [c.name, c] as const))("%s: every credential field says who holds it", (_name, connector) => {
    for (const field of connector.credential) expect(["account", "host"], field.name).toContain(field.holder)
  })

  // Compte rattaché : l'identité n'est citée que par l'adresse de base, après l'hôte, et aucune fonction ne la prend.
  it.each(connectors.flatMap((c) => (c.accountIdentity ? [[c.name, c, c.accountIdentity] as const] : [])))(
    "%s: the account identity is cited after the host only, and by no function",
    (_name, connector, identity) => {
      expect(identity.pattern).toMatch(/^\^.+\$$/)
      const cited = `{${identity.name}}`
      const urls = connector.baseUrl !== undefined ? [connector.baseUrl] : Object.values(connector.baseUrls?.values ?? {})
      expect(urls.length).toBeGreaterThan(0)
      for (const url of urls) expect(url).toMatch(new RegExp(`^(https://[^/{}]+|\\{[a-z][a-z0-9_]*\\})/.*\\{${identity.name}\\}`))
      for (const fn of connector.functions) {
        expect(Object.keys(fn.schema.properties as object), fn.name).not.toContain(identity.name)
        expect(fn.request.path, fn.name).not.toContain(cited)
        for (const names of [fn.request.query, fn.request.body, fn.request.headers]) expect(Object.keys(names)).not.toContain(identity.name)
      }
    },
  )

  it.each(connectors.filter((c) => c.baseUrls).map((c) => [c.name, c] as const))("%s: base URLs give one address per choice", (_name, connector) => {
    const setting = connector.settings?.find((s) => s.name === connector.baseUrls?.setting)
    expect(setting?.type).toBe("choice")
    if (setting?.type !== "choice") return
    expect(Object.keys(connector.baseUrls?.values ?? {}).sort()).toEqual([...setting.choices].sort())
    if (setting.default !== undefined) expect(setting.choices).toContain(setting.default)
    expect(connector.baseUrl).toBeUndefined()
  })
})
