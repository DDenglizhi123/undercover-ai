# Update VPS Docker from Git

## 1. SSH to VPS
```bash
ssh your_vps_ip
```

## 2. Navigate to project directory
```bash
cd /path/to/undercover-ai
```

## 3. Pull latest code
```bash
git pull origin main
```

## 4. Rebuild and restart containers
```bash
docker compose build web
docker compose up -d
```

## Optional: View logs
```bash
docker compose logs -f web
```