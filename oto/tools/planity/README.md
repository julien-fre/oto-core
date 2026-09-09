# Planity — reverse-engineering notes

There is **no public Planity API**. Everything in this package was extracted from the
`pro.planity.com` JS bundle and validated against a live pro account. Read-only: no
write operation is implemented here (no appointment creation, update or cancellation).

## Public constants

`config.py` keeps the three the code actually uses:

- `FIREBASE_API_KEY` — Firebase Auth API key of the `planity-production` project.
- `FIREBASE_APP_ID` — Firebase app ID, sent as `p=` in the RTDB WebSocket handshake.
- `PLANITY_REST_API` — `https://product.api.euwest1.prod.planityapp.com`, the REST lambdas.

Two more were read in the bundle and are **deliberately absent**, because nothing here
consumes them: the Firebase project id (`planity-production`, already carried by the
host names in `firebase_ws.py`) and the shard lookup endpoint
(`https://dffgcccimeiln.cloudfront.net?businessOrCalendarId=<id>` → `{shardName}` — we
read `businesses/<bid>/db` on master instead).

## Auth chain (3 steps)

1. **Firebase email/password login** → basic idToken.
   - `POST https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=<API_KEY>`
   - Body: `{email, password, returnSecureToken: true}`
2. **Planity custom token exchange** → adds per-business claims.
   - `POST {PLANITY_REST_API}/getProAuthToken`
   - Body: `{uid, token, isBusinessSharded: true, isUserSharded: true, source: "web"}`
   - Header: `Origin: https://pro.planity.com`
3. **Firebase custom-token sign-in** → enriched idToken.
   - `POST https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key=<API_KEY>`

Enriched idToken claims include `{plPro: true, isBusinessSharded: true, isUserSharded:
true, source: "web", <bid_1>: 1, <bid_2>: 1, …}`. Firebase security rules check
`auth.token[$bid] === 1` on business-scoped paths — which is also how `PlanityAuth`
discovers **which salons an account can reach** (the non-reserved claim keys).

TTL: 1 h. On expiry we do a full re-login rather than a refresh-token dance — simpler,
and the WebSockets have to be reopened on the new token anyway
(`PlanityClient._ensure_master` / `_ensure_shard`, ~500 ms, transparent to callers).

## Firebase RTDB WebSocket protocol

REST on the Realtime Database returns `permission_denied` on nearly every path, even
with the enriched token. **The WebSocket is not an optimisation — it is the only path
that works.**

- URI: `wss://<host>/.ws?v=5&p=<APP_ID>&ns=<namespace>`
- Server handshake frame: `{t:"c",d:{t:"h",d:{ts,v,h,s}}}` — ignored (the server accepts
  traffic on the initial host).
- Auth frame: `{t:"d",d:{r:1,a:"auth",b:{cred:"<idToken>"}}}`
- Query (listen + immediate read): `{t:"d",d:{r:N,a:"q",b:{p:"<path>",h:""}}}`
- Pagination: add `q: {i: ".key", l: 3, vf: "r"}` — `l` = limit, `vf` = `r`|`l` direction.
- Data push: `{t:"d",d:{a:"d",b:{p:<path>,d:<value>}}}`
- Reply ack: `{t:"d",d:{r:N,b:{s:"ok"|"permission_denied"|…,d:<value>}}}`
- Unlisten: `{t:"d",d:{r:N,a:"n",b:{p:"<path>"}}}`

**Multi-frame format, 2 variants** (both seen in production, both handled by
`firebase_ws._recv_raw`):

- `<count>\n<first_part>`, then `count-1` follow-up frames;
- `<count>` alone in its own frame, then `count` follow-up frames.

## Sharding map

| DB | Host | Namespace | Contents |
|---|---|---|---|
| master | `planity-production.firebaseio.com` | `planity-production` | `businesses/<bid>/*` — metadata, services, calendars, opening hours |
| business data | `planity-production-<shard>.europe-west1.firebasedatabase.app` | `planity-production-<shard>` | `business_customers/`, `business_receipts/`, `business_products/`, `business_access_codes/` |
| calendars | `planity-production-calendars-<N>.firebaseio.com` | `planity-production-calendars-<N>` | `calendars/<cid>/vevents/` (appointments) |

- The **business shard name** of a salon is read from `businesses/<bid>/db` on master
  (e.g. `"fr-18"`).
- The **calendar shard index** is computed, not looked up:
  `sum(ord(c) for c in calendar_id) % 4 + 1` (`firebase_ws.calendar_shard_index`).

## Where each Planity concept lives

| Concept | Layer | Path |
|---|---|---|
| Salon metadata (name, phone, slug, hours) | Firebase master | `businesses/<bid>/{name,slug,phoneNumber,openingHours,db}` |
| Employees (= calendar children) | Firebase master | `businesses/<bid>/calendars/<cid>/children/<childId>` |
| Service catalog (grouped) | Firebase master | `businesses/<bid>/services/<groupId>/children/<serviceId>` |
| Product catalog | Firebase business shard | `business_products/<bid>/<categoryId>/children/<productId>` |
| Customer profile | Firebase business shard | `business_customers/<bid>/<customerId>` |
| Customer listing / search | Algolia | index `business_customers` |
| Appointments (vevents) | Firebase calendars shard | `calendars/<cid>/vevents/<veventId>` |
| Receipts / revenue per customer | Planity REST | `getCustomerReceipts`, `getCustomerStats` |
| Business revenue KPIs | Planity REST | `getBusinessKeyIndicators`, `getBusinessRevenues` |
| Per-employee stats, occupancy, reviews | Planity REST | `getCalendarStats`, `getOccupancyRateStats`, `getReviewsStats` |
| Multi-dimensional revenue split | Planity REST | `getBusinessRevenuesBySeller` |

## REST endpoint catalog

### Auth / misc

| Endpoint | Payload | Response |
|---|---|---|
| `getProAuthToken` | `{uid, token, isBusinessSharded, isUserSharded, source}` | `{token: <customToken>}` |
| `getCustomerSearchCredentials` | `{token, businessId, businessCountryCode, withMainAppCredentials}` | `{body: {appId, apiKey, …}}` — Algolia creds, the businessId filter is baked into the key |

### Customer-level — payload `{businessId, customerId, token[, hasPOS]}`

| Endpoint | Response shape |
|---|---|
| `getCustomerStats` | `{appointments:{total,byWeb,byPro,frequency}, revenue:{total,average,totalByService,totalByProduct,rateByService,rateByProduct}}` — cents |
| `getCustomerReceipts` | `[{receiptId, createdAt, lines:[{price, serviceId, productId, cureId, giftVoucherId}]}]` |

### Business-level, simple — payload `{businessId, userToken, gte, lte}`

| Endpoint | Response |
|---|---|
| `getBusinessKeyIndicators` | `{revenueWithVAT, revenueWithoutVAT, amountOfReceipts, VATValue, averageBasket}` |
| `getBusinessRevenues` | `{all: {<ts_ms>: {revenueWithVAT, revenueWithoutVAT, quantity}}}` — daily buckets |
| `getBestCustomers` | top customers over the period |
| `getNewCustomers` | customers first seen in the period |
| `getOverallFrequencies` | visit frequency distribution |

### Business-level, statistics ⚠️

Payload `{businessId, userToken, token, gte, lte, start, end, sellers, calendars}` —
these endpoints require **duplicated keys**: both `userToken` AND `token`, both
`gte`/`lte` AND `start`/`end`. Miss one and the answer is `UNAUTHORIZED_USER_ERROR` or
`MISSING_TOKEN_ERROR`, which reads like a credential problem and is not one. Single
home of that payload: `rest_api.PlanityREST._stats_payload`.

| Endpoint | Response highlights |
|---|---|
| `getBusinessRevenuesBySeller` | `{totals, bySeller, byProduct:{totals,data:{<cat>:{categoryTotals,children}}}, byService, byOther, byGiftVoucherAtSale}` |
| `getCalendarStats` | `{data: [[sellerId, _, services_count, _, totalRevenue_cents, avgBasket_eur, …]], bySeller:{data:{<sellerId>:{onlineAppointments, offlineAppointments}}}}` |
| `getOccupancyRateStats` | `{matrix: [[…weekly occupancy rates…]]}` — 0..1+ |
| `getReviewsStats` | `{byCalendar: [[cid, nb, avg, …]], byService: [[sid, …]]}` |

⚠️ `getBusinessRevenuesBySeller` returns `bySeller: []` even when sellers are passed —
unresolved. `getCalendarStats` is the reliable per-employee breakdown, and that is what
`PlanityClient.get_calendar_stats` is for.

## Algolia customer search

- Index: `business_customers` — a single global index; the per-business `secureApiKey`
  returned by `getCustomerSearchCredentials` carries the businessId filter, so a query
  cannot reach another salon's customers.
- `POST https://{appId.lower()}-dsn.algolia.net/1/indexes/business_customers/query` with
  `{query, hitsPerPage, page}`.
- Hit shape: `{id, businessId, createdAt, deletedAt, email, gender, name, phone,
  postalCode, skipMarketingSMS, objectID, …}`.

## ⚠️ The admin PIN is checked client-side only

Planity's admin PIN triggers **zero network call**. Its policy is stored at
`business_access_codes/<bid>/adminSettings` (readable over Firebase with the enriched
token) and lists `allowedActions` / `restrictedRoutes`, but nothing enforces it server
side.

**Implication, and it must be said to whoever connects an account**: anyone holding the
email and password of a Planity pro account has the same read access as someone who
knows the PIN. The PIN protects the Planity UI, not the data.

## What does not work

- Firebase RTDB reads over REST — `permission_denied` on non-trivial paths, enriched
  token or not. WebSocket only.
- `getAppointmentStats` — needs an `interval` parameter that has not been reversed.
- Capturing browser XHR on Planity's *Caisse* / *Statistiques* pages teaches nothing:
  those pages aggregate client-side from WebSocket subscriptions and never call the REST
  stats endpoints. The payloads above came from the mobile app and from trial and error.
