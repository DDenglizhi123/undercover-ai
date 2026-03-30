# Undercover AI - Dev Log

## Session: 2026-03-30

### Mobile UI Fix
- Fixed issue where "End My Turn" button was not visible on mobile phones
- Added `min-height: 0` to `.chat-box` to allow proper flex shrinking
- Added `overflow: hidden` to `.screen` for proper overflow handling
- Reduced spacing on timer, mini-word-display, and eliminated-display to be more compact
- Made bottom buttons always visible on small screens
- ✅ Verified on mobile (192.168.1.106)

### Game End on Disconnect Fix
- Changed minimum player threshold from 2 to 3 throughout the codebase
- When a player disconnects during a 3-player game, the game now ends immediately
- Added player count check in `handle_end_turn` before starting voting
- All disconnect handlers now check for `< 3` instead of `< 2`
- All voting triggers now check for `>= 3` instead of `>= 2`

### Files Modified
- `chat/consumers.py` - Player count threshold changes
- `chat/templates/chat/room.html` - CSS and layout adjustments (mobile fix)

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

### Game End on Disconnect Fix
- Changed minimum player threshold from 2 to 3 throughout the codebase
- When a player disconnects during a 3-player game, the game now ends immediately
- Added player count check in `handle_end_turn` before starting voting
- All disconnect handlers now check for `< 3` instead of `< 2`
- All voting triggers now check for `>= 3` instead of `>= 2`

### Files Modified
- `chat/consumers.py` - Player count threshold changes
- `chat/templates/chat/room.html` - CSS and layout adjustments (mobile fix)

## Session: 2026-03-29
