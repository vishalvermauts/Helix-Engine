param (
    [Parameter(Mandatory=$true, HelpMessage="Your Digital Ocean Personal Access Token")]
    [string]$ApiToken,

    [Parameter(Mandatory=$true, HelpMessage="Your SSH Key Fingerprint (e.g. 3b:16:bf:e4:8b:00...)")]
    [string]$SshKeyFingerprint,

    [string]$Region = "nyc3",
    [string]$Size = "s-1vcpu-2gb"
)

$ErrorActionPreference = 'Stop'

$headers = @{
    "Authorization" = "Bearer $ApiToken"
    "Content-Type"  = "application/json"
}

# Read the cloud-init file we generated earlier
$userDataPath = Join-Path -Path $PSScriptRoot -ChildPath "cloud-init.yaml"
if (-not (Test-Path $userDataPath)) {
    Write-Error "cloud-init.yaml not found in $PSScriptRoot"
    exit
}

$userData = Get-Content $userDataPath -Raw
$escapedUserData = $userData.Replace('\', '\\').Replace('"', '\"').Replace("`n", '\n').Replace("`r", '')

$body = @"
{
    "name": "helix-engine-v2",
    "region": "$Region",
    "size": "$Size",
    "image": "ubuntu-24-04-x64",
    "ssh_keys": ["$SshKeyFingerprint"],
    "user_data": "$escapedUserData",
    "tags": ["helix-engine"]
}
"@

Write-Host "🚀 Provisioning Helix Engine Droplet in Digital Ocean ($Region)..." -ForegroundColor Cyan

try {
    $response = Invoke-RestMethod -Uri "https://api.digitalocean.com/v2/droplets" -Method Post -Headers $headers -Body $body
    
    $dropletId = $response.droplet.id
    Write-Host "✅ Droplet created successfully! ID: $dropletId" -ForegroundColor Green
    Write-Host "⏳ Waiting for IP address assignment (this takes ~30 seconds)..." -ForegroundColor Yellow
    
    # Poll for the IP address
    $ipAssigned = $false
    while (-not $ipAssigned) {
        Start-Sleep -Seconds 10
        $statusResp = Invoke-RestMethod -Uri "https://api.digitalocean.com/v2/droplets/$dropletId" -Method Get -Headers $headers
        
        $networks = $statusResp.droplet.networks.v4
        if ($networks -and $networks.Count -gt 0) {
            foreach ($net in $networks) {
                if ($net.type -eq "public") {
                    $ipAddress = $net.ip_address
                    $ipAssigned = $true
                    Write-Host "🌐 Droplet Public IP: $ipAddress" -ForegroundColor Green
                    Write-Host "You can SSH into it in a few minutes using: ssh helix@$ipAddress" -ForegroundColor Cyan
                    break
                }
            }
        }
    }
}
catch {
    Write-Error "Failed to create droplet: $_"
}
