// Les cas communs de la table d'erreurs (`src/error-cases.ts`, sortis par la fabrique de `connectors/_cases/errors.yaml`) :
// des données que le paquet de l'hôte joue contre son moteur. Ici, leur forme, et une référence qui les rejoue : `equals`
// compare des valeurs exactes, `contains` cherche un texte, casse à part.
import { describe, expect, it } from "vitest"
import { connector, errorCases } from "../src/error-cases"
import { connectors } from "../src"
import type { ApiError, BodyCondition } from "../src/types"

const ABSENT = Symbol("absent")

function at(value: unknown, path: string): unknown {
  let current: unknown = value
  for (const key of path.split(".")) {
    if (Array.isArray(current) && /^[0-9]+$/.test(key) && Number(key) < current.length) current = current[Number(key)]
    else if (current !== null && typeof current === "object" && !Array.isArray(current) && Object.hasOwn(current, key)) {
      current = (current as Record<string, unknown>)[key]
    } else return ABSENT
  }
  return current
}

function holds(condition: BodyCondition, answer: { readonly json?: unknown; readonly text?: string }): boolean {
  if (!("json" in answer)) return false
  const value = at(answer.json, condition.path)
  if (condition.equals !== undefined) return condition.equals.some((expected) => value === expected)
  return typeof value === "string" && condition.contains.some((text) => value.toLowerCase().includes(text.toLowerCase()))
}

function selected(errors: readonly ApiError[], answer: (typeof errorCases)[number]["answer"]) {
  for (const entry of errors) {
    const statuses = typeof entry.status === "number" ? [entry.status] : entry.status
    if (statuses.includes(answer.status) && (entry.body === undefined || holds(entry.body, answer))) {
      return { code: entry.code, marksAccount: entry.marksAccount ?? null }
    }
  }
  return null
}

describe("error cases", () => {
  it("should stay out of the index: test data, not a connector a host declares", () => {
    expect(connectors.map((c) => c.name)).not.toContain(connector.name)
  })

  it("should carry both operators of a body condition", () => {
    const conditions = connector.errors.flatMap((e) => (e.body === undefined ? [] : [e.body]))
    expect(conditions.some((c) => c.equals !== undefined)).toBe(true)
    expect(conditions.some((c) => c.contains !== undefined)).toBe(true)
  })

  it.each(errorCases.map((c) => [c.name, c] as const))("%s: the entry it selects", (_name, c) => {
    expect(selected(connector.errors, c.answer)).toEqual(c.entry)
  })
})
