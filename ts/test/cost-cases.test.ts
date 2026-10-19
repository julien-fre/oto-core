// Les cas communs du coût (`src/cost-cases.ts`, sortis par la fabrique de `connectors/_cases/cost.yaml`) : des données
// que le paquet de l'hôte joue contre ses fonctions pures du coût. Ici, leur forme : chaque cas appelle une fonction du
// connecteur des cas, dont le schéma compile et tient ses exemples, et sa relève attendue nomme une fonction déclarée.
import { Ajv2020 } from "ajv/dist/2020.js"
import { describe, expect, it } from "vitest"
import { connector, costCases } from "../src/cost-cases"
import { connectors } from "../src"

const ajv = new Ajv2020({ strictTypes: false, strictTuples: false, validateFormats: false })

describe("cost cases", () => {
  it("should stay out of the index: test data, not a connector a host declares", () => {
    expect(connectors.map((c) => c.name)).not.toContain(connector.name)
  })

  it.each(connector.functions.map((fn) => [fn.name, fn] as const))("%s: schema compiles and holds its examples", (_name, fn) => {
    const validate = ajv.compile(fn.schema)
    for (const example of fn.examples) expect(validate(example.input), example.title).toBe(true)
  })

  it.each(costCases.map((c) => [c.name, c] as const))("%s: a function of the case connector", (_name, c) => {
    expect(connector.functions).toContain(c.function)
    if (c.collection !== null && c.collection !== "error") {
      expect(connector.functions.map((fn) => fn.name)).toContain(c.collection.function)
    }
  })
})
