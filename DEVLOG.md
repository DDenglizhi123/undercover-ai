# Undercover AI - Dev Log

## Session: 2026-03-29

### Docker & Deployment
- Created Dockerfile for Python/Django app with Daphne ASGI server
- Created docker-compose.yml with Redis service
- Successfully deployed to DigitalOcean VPS (159.223.75.154)
- Created docker-compose.prod.yml with production settings
- Documented deployment process

### Features Added

#### Help Guide Modal
- Added "?" button in top-right corner
- Modal with game instructions
- Bilingual support (Chinese/English)
- Instructions include: Objective, Roles, Game Flow, Win Conditions, Tips

#### Disconnection Handling
- Players who disconnect during game are properly removed from:
  - alive_players list
  - speaking_order queue
  - votes
- System announces when a player leaves
- Game continues automatically:
  - If current speaker disconnects → moves to next speaker
  - If voter disconnects → continues with remaining votes
  - If too few players → ends game gracefully

#### Restart Logic
- 5-second restart window after game starts
- Countdown displayed on restart button
- After 5 seconds, button becomes disabled (gray)
- Players can request new words during the window

### Files Modified
- `chat/consumers.py` - Disconnection handling, restart logic
- `chat/templates/chat/room.html` - Help modal, restart UI
- `docker-compose.prod.yml` - New production config

### Git Commits
- `244e301` - feat: add help guide, handle disconnections, improve restart logic

### Deployment Info
- VPS IP: 159.223.75.154
- Provider: DigitalOcean
- Region: Singapore
- Access: http://159.223.75.154/chat/{room_name}/

## How to Continue Development

### Local Testing
```bash
cd /Users/lz/Code/undercover-ai
docker-compose down
docker-compose up -d --build
# Visit http://localhost:8000/chat/test/
```

### Deploy to VPS
```bash
# On Mac
tar -czf ~/undercover-ai.tar.gz --exclude='venv' --exclude='__pycache__' --exclude='.git' .
scp ~/undercover-ai.tar.gz root@159.223.75.154:~/
scp docker-compose.prod.yml root@159.223.75.154:~/docker-compose.yml

# On VPS
ssh root@159.223.75.154
cd ~/undercover-ai
docker-compose down
tar -xzf ~/undercover-ai.tar.gz
docker-compose up -d --build
```

### Commit Changes
```bash
git add -A
git commit -m "feat: description of changes"
git push
```
