// Les cas communs du corps emboîté (`src/nested-body-cases.ts`, sortis par la fabrique de
// `connectors/_cases/nested_body.yaml`) : des données que le paquet de l'hôte joue contre son moteur et
// `registerConnectors`. Ici, leur forme : chaque fonction des cas a un corps en table, emboîtée ; chaque cas valide
// l'entrée et attend pour corps la constante du corps, chaque argument donné à son chemin ; chaque entrée rejetée est
// refusée par le schéma ; chaque fonction refusée nomme l'un des trois refus de la règle 22.
import { Ajv2020 } from "ajv/dist/2020.js"
import { describe, expect, it } from "vitest"
import { connectors } from "../src"
import { connector, nestedBodyCases, nestedBodyRefusals, nestedBodyRefusedFunctions, nestedBodyRejectedInputs } from "../src/nested-body-cases"
import type { BodyMap, ConnectorFunction, JsonValue } from "../src/types"

/** Les fonctions du connecteur des cas, sous le type du contrat (leurs clés facultatives lisibles). */
const caseFunctions: readonly ConnectorFunction[] = connector.functions

const ajv = new Ajv2020({ strictTypes: false, strictTuples: false, validateFormats: false })
ajv.addKeyword({ keyword: "personal", schemaType: "boolean" })

/** La référence : la constante du corps, puis chaque argument donné à son chemin, les objets parents créés au besoin. */
function sent(fn: ConnectorFunction, input: { readonly [argument: string]: unknown }): unknown {
  const body = structuredClone(fn.request.constants?.body ?? {}) as Record<string, unknown>
  const place = (table: BodyMap, parent: () => Record<string, unknown>) => {
    for (const [key, value] of Object.entries(table)) {
      if (typeof value !== "string") {
        place(value, () => {
          const at = parent()
          at[key] ??= {}
          return at[key] as Record<string, unknown>
        })
      } else if (Object.hasOwn(input, value)) parent()[key] = input[value] as JsonValue
    }
  }
  place(fn.request.body as BodyMap, () => body)
  return body
}

describe("nested body cases", () => {
  it("should stay out of the index: test data, not a connector a host declares", () => {
    expect(connectors.map((c) => c.name)).not.toContain(connector.name)
  })

  it("should name the three refusals of rule 22, each with a refused function", () => {
    expect([...nestedBodyRefusals]).toEqual(["body_nested_empty", "body_key_twice", "body_nested_multipart"])
    expect(new Set(nestedBodyRefusedFunctions.map((r) => r.refusal))).toEqual(new Set(nestedBodyRefusals))
  })

  it.each(caseFunctions.map((fn) => [fn.name, fn] as const))("%s: a body map with a nested table", (_name, fn) => {
    const validate = ajv.compile(fn.schema)
    for (const example of fn.examples) expect(validate(example.input), example.title).toBe(true)
    expect(typeof fn.request.body).toBe("object")
    expect(Object.values(fn.request.body).some((value) => typeof value === "object")).toBe(true)
  })

  it("should carry a paginated function whose cursor is under a nested key", () => {
    const paginated = caseFunctions.filter((fn) => fn.pagination)
    expect(paginated.map((fn) => [fn.name, fn.pagination?.requestParam])).toEqual([["nested_body_cases.list_issues", "after"]])
    expect(paginated[0]?.request.body).toEqual({ variables: { first: "first", after: "after" } })
  })

  it.each(nestedBodyCases.map((c) => [c.name, c] as const))("%s: a valid input, the constant and the given arguments for body", (_name, c) => {
    expect(connector.functions).toContain(c.function)
    expect(ajv.compile(c.function.schema)(c.input)).toBe(true)
    expect(c.request.body).toEqual(sent(c.function, c.input))
  })

  it.each(nestedBodyRejectedInputs.map((r) => [r.name, r] as const))("%s: refused by the input schema", (_name, r) => {
    expect(connector.functions).toContain(r.function)
    expect(ajv.compile(r.function.schema)(r.input)).toBe(false)
  })

  it.each(nestedBodyRefusedFunctions.map((r) => [r.name, r] as const))("%s: outside the connector, its body is a map", (_name, r) => {
    expect(connector.functions).not.toContain(r.function)
    expect(typeof r.function.request.body).toBe("object")
    expect(nestedBodyRefusals).toContain(r.refusal)
  })
})
