# @otomata_tech/connectors

Shared connector definitions for [Oto](https://github.com/otomata-tech/connectors): one definition per connector and per
function (input JSON Schema, HTTP request, authentication, errors, pagination, cost), generated from
`connectors/*/connector.yaml` by the repository's generator (the *fabrique*).

The package is structural data only. It sends no request and reads no secret: **the host runs the requests**, with its
own HTTP client, credential vault and logs, and passes each account's secret at call time.

## Install

Pin an exact version:

```bash
npm i @otomata_tech/connectors@<version>
```

The version is the repository's: each tag `vX.Y.Z` publishes this package and the Python library
([`oto-core`](https://pypi.org/project/oto-core/)) at the same version.

## Use

```ts
import { connectors, type Connector } from "@otomata_tech/connectors"

const notion: Connector | undefined = connectors.find((c) => c.name === "notion")
```

`connectors` lists every generated connector; each one carries its functions. The contract of a definition is
`src/types.ts`, also exported as `@otomata_tech/connectors/types`.

The package ships its TypeScript sources (`src/*.ts`), not compiled JavaScript: the host transpiles them (with Next.js,
list the package in `transpilePackages`).

## License

MIT
