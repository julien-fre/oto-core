// Les cas communs du fichier rendu (`src/file-cases.ts`, sortis par la fabrique de `connectors/_cases/file.yaml`) : des
// données que le paquet de l'hôte joue contre son moteur, avec un faux `fetch`. Ici, leur forme : chaque cas appelle une
// fonction du connecteur des cas qui rend un fichier, et attend un fichier ou l'un des six refus nommés.
import { Ajv2020 } from "ajv/dist/2020.js"
import { describe, expect, it } from "vitest"
import { connector, fileCases, fileRefusals } from "../src/file-cases"
import { connectors } from "../src"

const ajv = new Ajv2020({ strictTypes: false, strictTuples: false, validateFormats: false })

describe("file cases", () => {
  it("should stay out of the index: test data, not a connector a host declares", () => {
    expect(connectors.map((c) => c.name)).not.toContain(connector.name)
  })

  it("should name the six refusals common to both sides", () => {
    expect([...fileRefusals].sort()).toEqual([
      "file_download_refused", "file_foreign_origin", "file_missing", "file_too_large", "file_type_refused", "file_unreadable",
    ])
  })

  it.each(connector.functions.map((fn) => [fn.name, fn] as const))("%s: schema compiles, holds its examples, renders a file", (_name, fn) => {
    const validate = ajv.compile(fn.schema)
    for (const example of fn.examples) expect(validate(example.input), example.title).toBe(true)
    expect(fn.output?.file?.maxBytes).toBeGreaterThan(0)
  })

  it.each(fileCases.map((c) => [c.name, c] as const))("%s: a function of the case connector, one outcome", (_name, c) => {
    expect(connector.functions).toContain(c.function)
    expect((c.file === undefined) !== (c.refusal === undefined)).toBe(true)
    if (c.refusal !== undefined) expect(fileRefusals).toContain(c.refusal)
    if (c.download !== undefined) expect(c.function.output?.file?.from).toBe("url")
  })
})
