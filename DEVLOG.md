# Undercover AI - Dev Log

## Session: 2026-04-07

### UI Upgrades
- Mic button: moved to control bar, bigger size (40x36px), red background when recording
- Chat messages: added ":" after avatar (e.g., "😀: Hello")
- Added emoji picker button with common emojis (😀😂😊😍🤔😅👍👎❤️🔥🎉⚠️)
- Voice message: reduced size (height 24px, width 120px)

### Score System
- Added player scores stored per room
- Stars (🌟): 1 point = 1 star
- Suns (☀️): every 5 stars = 1 sun (clears stars)
- Win streak (🔥): shows after 3+ consecutive wins
- Scoring rules:
  - Civilians win: each civilian gets 1 star
  - Undercover wins: each undercover/blank gets 2 stars
  - Blank wins (correct guess): blank gets 3 stars
- Scores persist across games until room is cleared

### Role Distribution Announcement
- When game starts, system now announces role counts: "Civilians: X | Undercover: X | Blank: X"

### Game End Identity Reveal
- When game ends, system now reveals everyone's identity AND their word
- Format: "Avatar Name: Role → Word"

### Blank Player Speaking Order Fix
- Modified `start_speaking_round()` to ensure blank player never speaks first
- After shuffling, if blank is at position 0, swap with position 1
- This gives blank player context from at least one other player's description

### Blank Guess Feature
- When a blank player is voted out, they get a chance to guess the civilian word
- New game phase: `blank_guess` - allows eliminated blank to type guess in chat
- If guess is correct → blank wins the game 🏆
- If guess is wrong → game continues normally
- Added i18n support for guess prompts and results
- Updated frontend to handle blank_guess phase (enable input, change placeholder)

### Files Modified
- `chat/consumers.py` - Added speaking order logic, blank guess handling
- `chat/templates/chat/room.html` - Added blank_guess frontend support

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
