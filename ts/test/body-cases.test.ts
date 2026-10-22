// Les cas communs du corps entier (`src/body-cases.ts`, sortis par la fabrique de `connectors/_cases/body.yaml`) : des
// données que le paquet de l'hôte joue contre son moteur et `registerConnectors`. Ici, leur forme : chaque fonction des
// cas forme son corps d'un argument, un objet strict et requis (fermé, ou à clés libres toutes donnée personnelle, en
// texte ou à valeur simple) ; chaque cas valide l'entrée et attend pour corps l'objet donné ; chaque entrée rejetée est refusée par le
// schéma ; chaque fonction refusée nomme l'un des huit refus.
import { Ajv2020 } from "ajv/dist/2020.js"
import { describe, expect, it } from "vitest"
import { bodyCases, bodyRefusals, bodyRefusedFunctions, bodyRejectedInputs, connector } from "../src/body-cases"
import { connectors } from "../src"
import type { ConnectorFunction } from "../src/types"

/** Les fonctions du connecteur des cas, sous le type du contrat (leurs clés facultatives lisibles). */
const caseFunctions: readonly ConnectorFunction[] = connector.functions

const ajv = new Ajv2020({ strictTypes: false, strictTuples: false, validateFormats: false })
ajv.addKeyword({ keyword: "personal", schemaType: "boolean" })

describe("body cases", () => {
  it("should stay out of the index: test data, not a connector a host declares", () => {
    expect(connectors.map((c) => c.name)).not.toContain(connector.name)
  })

  it("should name the eight refusals of rule 20, each with a refused function", () => {
    expect([...bodyRefusals]).toEqual([
      "body_argument_unknown",
      "body_argument_not_strict",
      "body_argument_optional",
      "body_argument_method",
      "body_argument_elsewhere",
      "body_argument_encoded",
      "body_argument_not_alone",
      "body_argument_paginated",
    ])
    expect(new Set(bodyRefusedFunctions.map((r) => r.refusal))).toEqual(new Set(bodyRefusals))
  })

  it.each(caseFunctions.map((fn) => [fn.name, fn] as const))("%s: one strict, required object argument is the whole body", (_name, fn) => {
    const validate = ajv.compile(fn.schema)
    for (const example of fn.examples) expect(validate(example.input), example.title).toBe(true)
    const argument = fn.request.body
    if (typeof argument !== "string") throw new Error(`${fn.name}: the body of a case function is one argument`)
    const property = (fn.schema.properties as Record<string, Record<string, unknown>>)[argument]
    expect(property?.type).toBe("object")
    // Fermé, ou des clés libres toutes donnée personnelle, en texte ou à valeur simple : exactement ces formes (décidé
    // le 2026-10-22).
    expect([false, { type: "string", personal: true }, { type: ["string", "number", "boolean"], personal: true }]).toContainEqual(
      property?.additionalProperties,
    )
    expect(Object.keys(property?.properties as object).length).toBeGreaterThan(0)
    expect(fn.schema.required).toContain(argument)
    expect(fn.request.constants?.body).toBeUndefined()
    expect(fn.request.files).toBeUndefined()
    expect(fn.pagination).toBeUndefined()
  })

  it("should carry a case function of each kind of free keys, and calls that send them", () => {
    const open = caseFunctions.filter((fn) => {
      const argument = fn.request.body as string
      return (fn.schema.properties as Record<string, Record<string, unknown>>)[argument]?.additionalProperties !== false
    })
    expect(open.map((fn) => fn.name)).toEqual(["body_cases.upsert_contact", "body_cases.update_account"])
    const sent = (fn: ConnectorFunction | undefined) => bodyCases.filter((c) => c.function === fn).map((c) => c.request.body)
    expect(sent(open[0]).some((body) => body.city === "Lyon")).toBe(true)
    const simple = sent(open[1]).flatMap((body) => Object.values(body).map((value) => typeof value))
    expect(new Set(simple)).toEqual(new Set(["string", "number", "boolean"]))
  })

  it.each(bodyCases.map((c) => [c.name, c] as const))("%s: a valid input, the object given for body", (_name, c) => {
    expect(connector.functions).toContain(c.function)
    expect(ajv.compile(c.function.schema)(c.input)).toBe(true)
    expect(c.request.body).toEqual(c.input[c.function.request.body as string])
  })

  it.each(bodyRejectedInputs.map((r) => [r.name, r] as const))("%s: refused by the input schema", (_name, r) => {
    expect(connector.functions).toContain(r.function)
    expect(ajv.compile(r.function.schema)(r.input)).toBe(false)
  })

  it.each(bodyRefusedFunctions.map((r) => [r.name, r] as const))("%s: outside the connector, its body names an argument", (_name, r) => {
    expect(connector.functions).not.toContain(r.function)
    expect(typeof r.function.request.body).toBe("string")
    expect(bodyRefusals).toContain(r.refusal)
  })
})
