#!/usr/bin/env bash
# Deploy the demo backend to Azure Container Apps (Consumption plan, scale to zero; deploy/README.md):
#   hems-api  public HTTPS: the demo API image built by .github/workflows/demo-api-image.yml
#   emhass    internal only: EMHASS 0.18.4 with default settings, reachable from hems-api as http://emhass
# Safe to run again: it creates what is missing and updates the apps otherwise.
#
# Needs: az login (Azure for Students subscription selected), and in the environment:
#   OPENAI_API_KEY, ENTSOE_API_KEY  stored as Container Apps secrets, never printed
#   CORS_ORIGINS                    the demo site's address, e.g. https://hems-demo.<you>.workers.dev
# Optional: GHCR_USER and GHCR_TOKEN (a GitHub token with read:packages) if the image is private.
set -euo pipefail

: "${OPENAI_API_KEY:?set OPENAI_API_KEY}"
: "${ENTSOE_API_KEY:?set ENTSOE_API_KEY}"
: "${CORS_ORIGINS:?set CORS_ORIGINS to the demo site address}"

RG=${RG:-hems-demo}
LOCATION=${LOCATION:-northeurope}            # Azure for Students may allow only some regions; try swedencentral
ENV_NAME=${ENV_NAME:-hems-demo-env}
API_IMAGE=${API_IMAGE:-ghcr.io/hoanlenguyen/hems-demo-api:latest}
EMHASS_IMAGE=${EMHASS_IMAGE:-ghcr.io/davidusb-geek/emhass:v0.18.4}
LLM_DAILY_LIMIT=${LLM_DAILY_LIMIT:-300}     # language-model runs per day for all visitors (one click = 3 runs)
LLM_HOURLY_PER_IP=${LLM_HOURLY_PER_IP:-30}  # runs per visitor and hour

az extension add --name containerapp --upgrade --only-show-errors
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait

az group create --name "$RG" --location "$LOCATION" --output none

# Consumption environment without a virtual network and without Log Analytics (both would add costs)
if ! az containerapp env show --name "$ENV_NAME" --resource-group "$RG" --output none 2>/dev/null; then
  az containerapp env create --name "$ENV_NAME" --resource-group "$RG" --location "$LOCATION" \
    --logs-destination none --output none
fi

registry=()
if [[ -n "${GHCR_USER:-}" && -n "${GHCR_TOKEN:-}" ]]; then
  registry=(--registry-server ghcr.io --registry-username "$GHCR_USER" --registry-password "$GHCR_TOKEN")
fi

# EMHASS: internal ingress only, configured exactly as the local container on localhost:5000. SUPERVISOR_TOKEN must
# be set and EMPTY: unset, EMHASS assumes it runs as a Home Assistant add-on, asks http://supervisor/ for its
# configuration and returns no plan. Time zone and location as locally (the time zone sets how the day is read).
emhass_args=(--image "$EMHASS_IMAGE" --cpu 1.0 --memory 2.0Gi --min-replicas 0 --max-replicas 1)
emhass_env=("SUPERVISOR_TOKEN=" EMHASS_URL=empty TIME_ZONE=Europe/Helsinki LAT=65.01 LON=25.47 ALT=15)
if az containerapp show --name emhass --resource-group "$RG" --output none 2>/dev/null; then
  az containerapp update --name emhass --resource-group "$RG" "${emhass_args[@]}" \
    --set-env-vars "${emhass_env[@]}" --output none
else
  az containerapp create --name emhass --resource-group "$RG" --environment "$ENV_NAME" \
    --ingress internal --target-port 5000 "${emhass_args[@]}" --env-vars "${emhass_env[@]}" --output none
fi

# The API: one replica at most, so the spending guard's in-memory counts hold
# EMHASS_WAIT_S: EMHASS scales to zero and needs about half a minute to start, so the API waits for it
api_env=(OPENAI_API_KEY=secretref:openai-key ENTSOE_API_KEY=secretref:entsoe-key EMHASS_URL_DEMO=http://emhass
         EMHASS_WAIT_S=90 "CORS_ORIGINS=$CORS_ORIGINS" "LLM_DAILY_LIMIT=$LLM_DAILY_LIMIT" "LLM_HOURLY_PER_IP=$LLM_HOURLY_PER_IP"
         LANGSMITH_TRACING=false)
if az containerapp show --name hems-api --resource-group "$RG" --output none 2>/dev/null; then
  az containerapp secret set --name hems-api --resource-group "$RG" \
    --secrets "openai-key=$OPENAI_API_KEY" "entsoe-key=$ENTSOE_API_KEY" --output none
  az containerapp update --name hems-api --resource-group "$RG" --image "$API_IMAGE" \
    --set-env-vars "${api_env[@]}" --output none
else
  az containerapp create --name hems-api --resource-group "$RG" --environment "$ENV_NAME" \
    --image "$API_IMAGE" "${registry[@]}" --ingress external --target-port 8000 \
    --cpu 0.5 --memory 1.0Gi --min-replicas 0 --max-replicas 1 \
    --secrets "openai-key=$OPENAI_API_KEY" "entsoe-key=$ENTSOE_API_KEY" \
    --env-vars "${api_env[@]}" --output none
fi

fqdn=$(az containerapp show --name hems-api --resource-group "$RG" --query properties.configuration.ingress.fqdn -o tsv)
echo "API: https://$fqdn"
echo "Build the site with NUXT_PUBLIC_API_BASE=https://$fqdn (deploy/README.md, step 4)."
