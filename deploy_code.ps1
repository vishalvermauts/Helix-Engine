param (
    [Parameter(Mandatory=$true, HelpMessage="Path to your private SSH key file (e.g. C:\Users\mcmur\.ssh\id_rsa)")]
    [string]$PrivateKeyPath,
    
    [string]$IpAddress = "165.227.185.117"
)

$ErrorActionPreference = 'Stop'

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "🚀 INITIALIZING HELIX DEPLOYMENT ROUTINE TO $IpAddress" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Test SSH Connection
Write-Host "Checking SSH connection..." -ForegroundColor Yellow
$connectionTest = ssh -i $PrivateKeyPath -o StrictHostKeyChecking=no -o ConnectTimeout=5 helix@$IpAddress "echo 'Connection Successful'"
if ($connectionTest -ne "Connection Successful") {
    Write-Error "Could not connect to the droplet. Please verify the Private Key Path or Droplet IP."
    exit
}
Write-Host "✅ SSH Connection Verified!" -ForegroundColor Green

# 2. Setup Opt Directory Ownership
Write-Host "Preparing target directories on Droplet..." -ForegroundColor Yellow
ssh -i $PrivateKeyPath helix@$IpAddress "sudo mkdir -p /opt/helix-engine /opt/helixflow-gateway && sudo chown -R helix:helix /opt/helix-engine /opt/helixflow-gateway"

# 3. Compress files locally using tar
Write-Host "Compressing Helix Engine locally..." -ForegroundColor Yellow
if (Test-Path "helix-engine.tar.gz") { Remove-Item "helix-engine.tar.gz" }
tar -czf helix-engine.tar.gz --exclude="venv" --exclude="__pycache__" --exclude=".git" -C "C:\Users\mcmur\Desktop\Helix Upgrade\Helix-Engine" .

Write-Host "Compressing HelixFlow Gateway locally..." -ForegroundColor Yellow
if (Test-Path "helixflow-gateway.tar.gz") { Remove-Item "helixflow-gateway.tar.gz" }
tar -czf helixflow-gateway.tar.gz --exclude="venv" --exclude="__pycache__" --exclude=".git" -C "C:\Users\mcmur\Desktop\Router\HelixFlow" .

# 4. Upload archives to Droplet via SCP
Write-Host "Uploading archives..." -ForegroundColor Yellow
scp -i $PrivateKeyPath -o StrictHostKeyChecking=no "helix-engine.tar.gz" "helix@${IpAddress}:/tmp/helix-engine.tar.gz"
scp -i $PrivateKeyPath -o StrictHostKeyChecking=no "helixflow-gateway.tar.gz" "helix@${IpAddress}:/tmp/helixflow-gateway.tar.gz"

# 5. Extract files on Droplet
Write-Host "Extracting archives on Droplet..." -ForegroundColor Yellow
ssh -i $PrivateKeyPath helix@$IpAddress "tar -xzf /tmp/helix-engine.tar.gz -C /opt/helix-engine/ && tar -xzf /tmp/helixflow-gateway.tar.gz -C /opt/helixflow-gateway/"

# Clean up local archives
Remove-Item "helix-engine.tar.gz"
Remove-Item "helixflow-gateway.tar.gz"

# 6. Run setup commands on droplet (Install Redis, create virtual environments, configure systemd)
Write-Host "Running remote installation commands on Droplet..." -ForegroundColor Yellow

$remoteCommand = @"
set -e
echo 'Installing Redis Server...'
sudo apt-get update && sudo apt-get install -y redis-server
sudo systemctl enable redis-server
sudo systemctl start redis-server

echo 'Building Helix Engine Virtual Environment...'
cd /opt/helix-engine
python3 -m venv venv
./venv/bin/pip install --upgrade pip setuptools wheel
./venv/bin/pip install aider-chat
./venv/bin/pip install -r requirements.txt

echo 'Building HelixFlow Gateway Virtual Environment...'
cd /opt/helixflow-gateway
python3 -m venv venv
./venv/bin/pip install --upgrade pip setuptools wheel
./venv/bin/pip install -r helixflow_gateway/requirements.txt

echo 'Configuring HelixFlow Gateway systemd service...'
cat << 'EOF' | sudo tee /etc/systemd/system/helixflow-gateway.service > /dev/null
[Unit]
Description=HelixFlow Gateway Router
After=network.target redis-server.service

[Service]
User=helix
WorkingDirectory=/opt/helixflow-gateway
Environment="PATH=/opt/helixflow-gateway/venv/bin"
ExecStart=/opt/helixflow-gateway/venv/bin/uvicorn helixflow_gateway.bootstrap:create_app --host 0.0.0.0 --port 8005 --factory --loop uvloop --workers 2
Restart=always

[Install]
WantedBy=multi-user.target
EOF

echo 'Reloading Systemd & Starting Services...'
sudo systemctl daemon-reload
sudo systemctl enable helix-engine helixflow-gateway
sudo systemctl start helix-engine helixflow-gateway

# Clean up remote archives
rm -f /tmp/helix-engine.tar.gz /tmp/helixflow-gateway.tar.gz

echo '=== Setup Completed Successfully! ==='
"@

ssh -i $PrivateKeyPath helix@$IpAddress $remoteCommand

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "🎉 ALL SERVICES SUCCESSFULLY DEPLOYED AND RUNNING!" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "Helix Engine Dashboard:  http://$IpAddress:8000" -ForegroundColor Cyan
Write-Host "HelixFlow Gateway Stream: http://$IpAddress:8005/stream" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Green
