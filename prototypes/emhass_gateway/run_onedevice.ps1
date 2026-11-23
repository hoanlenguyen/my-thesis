# One-device test: two runs of the 14 development plans on 4 shared cores (see docker-compose.onedevice.yml).
#   unprioritised: the model may use all 4 cores at equal weight; prioritised: 3 cores at low weight.
# Each run: start EMHASS, Ollama and the probe; load the model; 2 min of probe samples with the model idle; the 14
# plans; 1 min idle; stop. Outputs in out/onedevice/ (plans_<run>.jsonl, probe_<run>.jsonl, app/).
#   powershell -File prototypes/emhass_gateway/run_onedevice.ps1 [-Only prioritised] [-Ids DS1,DS2,DS3,DS4]
# A plan takes about an hour on the 4 shared cores, so -Ids limits a run to a few plans (19 Nov 2026: DS1-DS4).
param([string]$Only = "", [string[]]$Ids = @())
$ErrorActionPreference = "Stop"
$compose = "prototypes/emhass_gateway/docker-compose.onedevice.yml"
$runs = @(
    @{ name = "unprioritised"; cpus = "4"; shares = "1024" },
    @{ name = "prioritised"; cpus = "3"; shares = "128" }
) | Where-Object { -not $Only -or $_.name -eq $Only }
$Ids = @($Ids | ForEach-Object { $_ -split "," } | Where-Object { $_ })  # -File passes "DS1,DS2" as one string
$idArgs = @(); if ($Ids.Count -gt 0) { $idArgs = @("--ids") + $Ids }
Write-Output "plans: $(if ($Ids.Count) { $Ids -join ' ' } else { 'all' })"
foreach ($r in $runs) {
    $env:RUN = $r.name; $env:MODEL_CPUS = $r.cpus; $env:MODEL_SHARES = $r.shares
    Write-Output "=== $($r.name): model cpus $($r.cpus), cpu_shares $($r.shares)  $(Get-Date -Format s)"
    docker compose -f $compose up -d --force-recreate emhass ollama probe
    Start-Sleep 20
    docker compose -f $compose exec -T ollama ollama run gemma4:e4b "Reply with OK." | Out-Null  # load the model
    Write-Output "model loaded $(Get-Date -Format s); idle samples for 120 s"
    Start-Sleep 120
    docker compose -f $compose run --rm assistant --out "/out/plans_$($r.name).jsonl" @idArgs
    Write-Output "plans done $(Get-Date -Format s); idle samples for 60 s"
    Start-Sleep 60
    docker compose -f $compose stop probe
}
docker compose -f $compose down
Write-Output "=== DONE $(Get-Date -Format s)"
