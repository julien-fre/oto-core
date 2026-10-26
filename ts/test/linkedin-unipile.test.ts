// Le compte de l'hôte et le compte rattaché, lus dans la définition générée de `linkedin_unipile` : la clé est celle de
// l'application hôte (`holder: "host"`), le compte est l'identifiant du membre chez Unipile, cité par l'adresse de base
// seulement. L'hôte assemble à l'appel sa clé et l'identité du compte ; l'agent ne fournit jamais l'identité.
import { describe, expect, it } from "vitest"
import { linkedinUnipile } from "../src"

describe("linkedin_unipile definitions", () => {
  it("should hold the API key at the host and cite the account identity in the base URL", () => {
    const connector = linkedinUnipile.connector
    expect(connector.credential).toEqual([{ name: "api_key", label: "Unipile API key", secret: true, holder: "host" }])
    expect(connector.accountIdentity).toEqual({ name: "account_id", label: "LinkedIn account", pattern: "^[A-Za-z0-9_-]{1,64}$" })
    expect(connector.baseUrl).toBe("https://api.unipile.com/v2/{account_id}")
    expect(connector.auth).toEqual({ kind: "api_key", in: "header", name: "X-API-KEY", key: "api_key" })
    expect(connector.probe?.function).toBe("linkedin_unipile.get_me")
  })

  it("should serve the reads outside the act side", () => {
    for (const fn of [linkedinUnipile.getMe, linkedinUnipile.getProfile, linkedinUnipile.listRelations]) expect(fn.act).toBe(false)
  })

  it("should accept an identifier the pattern allows and refuse one it does not", () => {
    const pattern = new RegExp(linkedinUnipile.connector.accountIdentity.pattern)
    expect(pattern.test("aB3_x-9")).toBe(true)
    expect(pattern.test("../users")).toBe(false)
    expect(pattern.test("")).toBe(false)
  })

  it("should give the company page its own shorter timeout and leave the others on the connector's", () => {
    expect(linkedinUnipile.connector.timeoutMs).toBe(120_000)
    expect(linkedinUnipile.getCompany.timeoutMs).toBe(60_000)
    expect("timeoutMs" in linkedinUnipile.getProfile).toBe(false)
  })

  it("should confirm the sensitive functions before running them", () => {
    for (const fn of [linkedinUnipile.sendInvitation, linkedinUnipile.sendMessage]) {
      expect(fn.class).toBe("sensitive")
      expect(fn.act).toBe(true)
      expect(fn.confirm?.summary.length).toBeGreaterThan(0)
    }
  })

  it("should confirm a skill endorsement, which the member sees at once", () => {
    expect(linkedinUnipile.endorseProfile.class).toBe("sensitive")
    expect(linkedinUnipile.endorseProfile.act).toBe(true)
    expect(linkedinUnipile.endorseProfile.confirm?.summary).toContain("{profile_id}")
  })

  it("should serve the search parameters, the contracts and the Recruiter reads on the read side", () => {
    for (const fn of [
      linkedinUnipile.resolveFacet, linkedinUnipile.listContracts, linkedinUnipile.inmailBalance,
      linkedinUnipile.listJobPostings, linkedinUnipile.getJobPosting, linkedinUnipile.listJobApplicants,
      linkedinUnipile.getJobApplicant, linkedinUnipile.listHiringProjects,
    ]) expect(fn.act).toBe(false)
    expect(linkedinUnipile.selectContract.class).toBe("write")
    expect(linkedinUnipile.selectContract.act).toBe(false)
  })

  it("should strip the pictures and the tracking pixel, which open without a login, and keep the profile addresses", () => {
    const pictures = ["profile.public_picture_url", "profile.work_experience.company.picture_url", "profile.educations.school.picture_url"]
    expect(linkedinUnipile.getJobPosting.output?.strip).toEqual(["company.public_picture_url", "tracking_pixel_url"])
    expect(linkedinUnipile.listJobApplicants.output?.strip).toEqual(pictures)
    expect(linkedinUnipile.getJobApplicant.output?.strip).toEqual(pictures)
    expect(linkedinUnipile.listHiringProjects.output?.strip).toEqual(["owner.public_picture_url"])
    for (const fn of [linkedinUnipile.getJobPosting, linkedinUnipile.listJobApplicants, linkedinUnipile.getJobApplicant, linkedinUnipile.listHiringProjects])
      for (const path of fn.output?.strip ?? []) expect(path.endsWith("profile_url")).toBe(false)
  })

  it("should serve the eight searches on the read side, with the client's timeouts", () => {
    const structured = [
      linkedinUnipile.searchPeople, linkedinUnipile.searchCompanies, linkedinUnipile.searchSalesNavigatorPeople,
      linkedinUnipile.searchSalesNavigatorCompanies, linkedinUnipile.searchRecruiterPeople,
    ]
    const byUrl = [linkedinUnipile.searchByUrl, linkedinUnipile.searchSalesNavigatorByUrl, linkedinUnipile.searchRecruiterByUrl]
    for (const fn of [...structured, ...byUrl]) {
      expect(fn.class).toBe("read")
      expect(fn.act).toBe(false)
      expect("pagination" in fn).toBe(false)
    }
    for (const fn of structured) {
      expect(fn.timeoutMs).toBe(60_000)
      expect(fn.description).toContain("call resolve_facet first")
      expect(fn.schema.dependentSchemas).toEqual({ cursor: { maxProperties: 1 } })
    }
    for (const fn of byUrl) expect(fn.timeoutMs).toBe(75_000)
    expect(linkedinUnipile.searchRecruiterPeople.schema.properties.skills.items.properties.name.pattern).toBe("^[0-9]+$")
  })

  it("should strip the pictures of members, companies and conversations from the earlier reads", () => {
    for (const fn of [linkedinUnipile.getMe, linkedinUnipile.getProfile]) {
      expect(fn.output?.strip).toContain("public_picture_url")
      expect(fn.output?.strip).toContain("specifics.experience.company.picture_url")
    }
    expect(linkedinUnipile.listRelations.output?.strip).toEqual(["user.public_picture_url"])
    expect(linkedinUnipile.listChats.output?.strip).toContain("image_url")
    expect(linkedinUnipile.listChatMessages.output?.strip).toEqual([
      "sender.public_picture_url", "quoted.sender.public_picture_url", "forwarded.sender.public_picture_url",
    ])
    for (const fn of [linkedinUnipile.getMe, linkedinUnipile.getCompany, linkedinUnipile.listChats, linkedinUnipile.getPost, linkedinUnipile.searchPeople])
      for (const path of fn.output?.strip ?? []) expect(path.endsWith("profile_url")).toBe(false)
  })

  it("should mark what names a person as personal", () => {
    expect(linkedinUnipile.resolveFacet.schema.properties.keywords).toMatchObject({ personal: true })
    expect(linkedinUnipile.endorseProfile.schema.properties.profile_id).toMatchObject({ personal: true })
    expect(linkedinUnipile.getJobApplicant.schema.properties.applicant_id).toMatchObject({ personal: true })
    expect(linkedinUnipile.searchPeople.schema.properties.keywords).toMatchObject({ personal: true })
    expect(linkedinUnipile.searchPeople.schema.properties.advanced_keywords).toMatchObject({ personal: true })
    expect(linkedinUnipile.searchByUrl.schema.properties.url).toMatchObject({ personal: true })
  })
})
