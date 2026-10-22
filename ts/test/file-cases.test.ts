// Les cas communs du fichier rendu (`src/file-cases.ts`, sortis par la fabrique de `connectors/_cases/file.yaml`) : des
// données que le paquet de l'hôte joue contre son moteur, avec un faux `fetch`. Ici, leur forme : chaque cas appelle une
// fonction du connecteur des cas qui rend un fichier, et attend un fichier ou l'un des six refus nommés ; chaque fonction
// refusée, hors du connecteur, porte l'un des cinq codes de la déclaration (règle 17).
import { Ajv2020 } from "ajv/dist/2020.js"
import { describe, expect, it } from "vitest"
import { connector, fileCases, fileDeclarationRefusals, fileRefusals, fileRefusedFunctions } from "../src/file-cases"
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
    if (c.function.output?.file?.from === "json" && c.file !== undefined) {
      expect(c.file.mime).toBe("application/json")
      expect(new TextEncoder().encode(c.file.text).length).toBe(c.file.size)
    }
  })

  it("should name the five codes of a refused declaration, in the order they are judged", () => {
    expect([...fileDeclarationRefusals]).toEqual([
      "file_output_not_alone", "file_auth_not_url", "file_json_types", "file_json_name", "file_json_max_bytes",
    ])
    expect(new Set(fileRefusedFunctions.map((r) => r.refusal))).toEqual(new Set(fileDeclarationRefusals))
  })

  it.each(fileRefusedFunctions.map((r) => [r.name, r] as const))("%s: refused, out of the connector", (_name, r) => {
    expect(connector.functions).not.toContain(r.function)
    expect(r.function.output?.file).toBeDefined()
  })

  it("should carry a JSON file without types, at 4 MB at most", () => {
    const json = connector.functions.flatMap((fn) => (fn.output?.file?.from === "json" ? [fn.output.file] : []))
    expect(json.length).toBeGreaterThan(0)
    for (const file of json) {
      expect("types" in file).toBe(false)
      expect(file.maxBytes).toBeLessThanOrEqual(4194304)
      expect(file.name.template.endsWith(".json")).toBe(true)
    }
  })
})
