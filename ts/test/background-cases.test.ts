// Les cas communs de la fonction longue (`src/background-cases.ts`, sortis par la fabrique de
// `connectors/_cases/background.yaml`) : des données que le paquet de l'hôte joue contre `registerConnectors`. Ici, leur
// forme : chaque fonction acceptée porte `background` et son propre délai, sans `async` ni pagination ; chaque fonction
// refusée est hors du connecteur, porte `background` seule parmi ses voisines et nomme l'un des quatre refus.
import { Ajv2020 } from "ajv/dist/2020.js"
import { describe, expect, it } from "vitest"
import { backgroundAcceptedFunctions, backgroundRefusals, backgroundRefusedFunctions, connector } from "../src/background-cases"
import { connectors } from "../src"
import type { ConnectorFunction } from "../src/types"

/** Les fonctions du connecteur des cas, sous le type du contrat (leurs clés facultatives lisibles). */
const caseFunctions: readonly ConnectorFunction[] = connector.functions

const ajv = new Ajv2020({ strictTypes: false, strictTuples: false, validateFormats: false })
ajv.addKeyword({ keyword: "personal", schemaType: "boolean" })

describe("background cases", () => {
  it("should stay out of the index: test data, not a connector a host declares", () => {
    expect(connectors.map((c) => c.name)).not.toContain(connector.name)
  })

  it("should name the four refusals of rule 21, each with a refused function", () => {
    expect([...backgroundRefusals]).toEqual(["background_no_timeout", "background_async", "background_collect", "background_paginated"])
    expect(new Set(backgroundRefusedFunctions.map((r) => r.refusal))).toEqual(new Set(backgroundRefusals))
  })

  it("should list each function of the case connector once, as accepted", () => {
    expect(backgroundAcceptedFunctions.map((a) => a.function)).toEqual([...connector.functions])
  })

  it.each(caseFunctions.map((fn) => [fn.name, fn] as const))("%s: long, with its own delay, neither asynchronous nor paginated", (_name, fn) => {
    const validate = ajv.compile(fn.schema)
    for (const example of fn.examples) expect(validate(example.input), example.title).toBe(true)
    expect(fn.background).toBe(true)
    expect(fn.timeoutMs).toBeGreaterThan(0)
    expect(fn.timeoutMs).not.toBe(connector.timeoutMs)
    expect(fn.async).toBeUndefined()
    expect(fn.pagination).toBeUndefined()
    for (const other of caseFunctions) expect(other.async?.collect).not.toBe(fn.name)
  })

  it.each(backgroundRefusedFunctions.map((r) => [r.name, r] as const))("%s: outside the connector, long alone among its neighbours", (_name, r) => {
    expect(connector.functions).not.toContain(r.function)
    expect(r.function.background).toBe(true)
    for (const beside of r.beside) {
      expect(connector.functions).not.toContain(beside)
      expect(beside.background).toBeUndefined()
    }
    expect(backgroundRefusals).toContain(r.refusal)
    if (r.refusal === "background_collect") expect(r.beside.map((b) => b.async?.collect)).toContain(r.function.name)
    if (r.refusal === "background_async") expect(r.beside.map((b) => b.name)).toContain(r.function.async?.collect)
  })
})
