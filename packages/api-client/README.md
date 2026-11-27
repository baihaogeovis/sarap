# @sarap/api-client

TypeScript types generated from the platform OpenAPI schema. The web app imports `MapRasterOut` and the rest of `components` from here.

Regenerate after an HTTP API change, from a machine that can import the API:

```bash
cd apps/api
python -c "import json; from app.main import app; json.dump(app.openapi(), open('/tmp/sarap-openapi.json','w'))"
npx --yes openapi-typescript /tmp/sarap-openapi.json -o ../../packages/api-client/index.ts
```

`index.ts` is generated. Do not edit it by hand.
