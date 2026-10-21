// Les cas communs de `output.strip` (`src/strip-cases.ts`, sortis par la fabrique de `connectors/_cases/strip.yaml`) : des
// données que le paquet de l'hôte joue contre son moteur. Ici, leur forme : chaque cas appelle une fonction du connecteur
// des cas qui retire des clés, et attend la sortie taillée ; chaque sortie refusée nomme l'un des trois refus.
import { Ajv2020 } from "ajv/dist/2020.js"
import { describe, expect, it } from "vitest"
import { connector, stripCases, stripRefusals, stripRefusedOutputs } from "../src/strip-cases"
import { connectors } from "../src"
import type { Output } from "../src/types"

const ajv = new Ajv2020({ strictTypes: false, strictTuples: false, validateFormats: false })

describe("strip cases", () => {
  it("should stay out of the index: test data, not a connector a host declares", () => {
    expect(connectors.map((c) => c.name)).not.toContain(connector.name)
  })

  it("should name the three refusals common to both sides", () => {
    expect([...stripRefusals].sort()).toEqual(["strip_path_malformed", "strip_path_overlaps", "strip_path_twice"])
  })

  it.each(connector.functions.map((fn) => [fn.name, fn] as const))("%s: schema compiles, holds its examples, strips", (_name, fn) => {
    const validate = ajv.compile(fn.schema)
    for (const example of fn.examples) expect(validate(example.input), example.title).toBe(true)
    expect(fn.output?.strip?.length).toBeGreaterThan(0)
  })

  it.each(stripCases.map((c) => [c.name, c] as const))("%s: a function of the case connector, a shaped output", (_name, c) => {
    expect(connector.functions).toContain(c.function)
    expect("shaped" in c).toBe(true)
    const output: Output | undefined = c.function.output
    if (output?.items !== undefined) expect(Array.isArray(c.shaped)).toBe(true)
  })

  it("should carry dotted paths as declared", () => {
    const getCall = connector.functions.find((fn) => fn.name === "strip_cases.get_call")
    expect(getCall?.output?.strip).toEqual(["call.recording", "call.voicemail"])
  })

  it.each(stripRefusedOutputs.map((r) => [r.name, r] as const))("%s: one refusal, on a path it declares", (_name, r) => {
    expect(stripRefusals).toContain(r.refusal)
    expect(r.output.strip).toContain(r.path)
  })
})
