# Deploying the demo

| Part | Where | Cost |
|---|---|---|
| Site: replay pages and the Try-it page (static, `demo/`) | Cloudflare Workers static assets | free |
| API: agents, MILP, RAG (`src/hems/demo_api.py`, image from `Dockerfile`) | Azure Container Apps, public HTTPS, scales to zero | monthly free grant |
| EMHASS 0.18.4 | Azure Container Apps, internal only | monthly free grant |
| API image | GitHub Container Registry (`ghcr.io/<owner>/hems-demo-api`) | free |
| OpenAI and ENTSO-E keys | Container Apps secrets | free |

**Costs.** The Container Apps Consumption plan gives every subscription 180,000 vCPU-seconds,
360,000 GiB-seconds and 2 million requests per month for free; scaled to zero, the apps cost nothing. With the
sizes in `azure/deploy.sh` (API 0.5 vCPU / 1 GiB, EMHASS 1 vCPU / 2 GiB) that is about 33 hours of both running,
roughly 150 visits a month. Beyond it, Azure for Students takes the cost from its credit, and the subscription is
disabled, not billed, when the credit runs out. Not included: the OpenAI API (about USD 0.005 per click, three
language-model runs). The API refuses runs above `LLM_DAILY_LIMIT` (default 300 runs a day, about USD 0.50) and
`LLM_HOURLY_PER_IP` (default 30 an hour per visitor); also set a monthly budget on the OpenAI project.

**Cold start.** After a quiet period the containers start on the first request, which can take up to a minute;
the page then asks the visitor to try again.

## 1. Build the API image (GitHub Actions)

Push the repository, then run **Actions → Demo API image → Run workflow** (it also runs on a push to `main` that
changes the API). It builds `Dockerfile` and pushes `ghcr.io/<owner>/hems-demo-api:latest`.

If the repository is private, the package is private too: either make the package public (GitHub → Packages →
hems-demo-api → Package settings → Change visibility), or give Azure a token, step 3.

## 2. Deploy the site once, to get its address

```bash
cd demo && pnpm build && pnpm dlx wrangler deploy
```

The first `wrangler deploy` asks you to log in to Cloudflare and prints the address, e.g.
`https://hems-demo.<you>.workers.dev`. Without an API address the replay pages work and the Try-it page says
that the API is not running.

## 3. Deploy the backend (Azure)

```bash
az login
az account set --subscription "Azure for Students"
export OPENAI_API_KEY=... ENTSOE_API_KEY=...          # from .env; never commit or print them
export CORS_ORIGINS=https://hems-demo.<you>.workers.dev
bash deploy/azure/deploy.sh
```

It creates the resource group `hems-demo` (North Europe; set `LOCATION=swedencentral` if your subscription does
not allow it), a Container Apps environment without a virtual network or Log Analytics, the internal `emhass` app
and the public `hems-api` app, and prints the API address. For a private image, also export `GHCR_USER` and
`GHCR_TOKEN` (a GitHub token with `read:packages`). Run it again after a new image to update the apps.

Check it: `curl https://<api address>/api/catalog` returns the appliance catalogue (the first call may be slow).

## 4. Rebuild the site with the API address

```bash
cd demo
NUXT_PUBLIC_API_BASE=https://<api address> pnpm build
pnpm dlx wrangler deploy
```

## Turning it off

`az group delete --name hems-demo` removes the backend; `pnpm dlx wrangler delete` removes the site.
