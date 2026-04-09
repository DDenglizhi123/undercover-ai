import json
import random
import os
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer

# In-memory room storage. Consider Redis for production scalability.
ROOMS = {}
WORD_CACHE = {"zh": None, "en": None}

EMOJI_POOL = [
    "😎",
    "😜",
    "😴",
    "🤓",
    "🥳",
    "😈",
    "🤖",
    "👻",
    "🦊",
    "🐸",
    "🐵",
    "🦁",
    "🐯",
    "🐻",
    "🐼",
    "🐨",
    "🐷",
    "🐮",
    "🐔",
    "🦄",
    "🧙",
    "🧛",
    "🧜",
    "🧚",
    "🦸",
    "🥷",
    "👽",
    "🎃",
    "🤡",
    "🤠",
]


def get_word_pairs(lang):
    if WORD_CACHE.get(lang):
        return WORD_CACHE[lang]
    filename = "words_zh.json" if lang == "zh" else "words_en.json"
    try:
        words_path = os.path.join(os.path.dirname(__file__), filename)
        with open(words_path, "r", encoding="utf-8") as f:
            WORD_CACHE[lang] = json.load(f)
    except Exception:
        WORD_CACHE[lang] = (
            [{"civilian": "苹果", "undercover": "鸭梨"}]
            if lang == "zh"
            else [{"civilian": "Apple", "undercover": "Pear"}]
        )
    return WORD_CACHE[lang]


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_name = self.scope["url_route"]["kwargs"]["room_name"]
        self.room_group_name = f"chat_{self.room_name}"

        if self.room_name not in ROOMS:
            ROOMS[self.room_name] = {
                "host": None,  # channel_name of host
                "players": {},  # channel_name -> username
                "username_to_channel": {},  # username -> channel_name
                "avatars": {},  # channel_name -> emoji
                "ready_players": set(),  # channel_names that clicked Ready
                "alive_players": [],  # list of channel_names
                "words": {},  # channel_name -> {role, word}
                "votes": {},  # voter_channel -> target_channel
                "status": "waiting",  # waiting | speaking | voting | blank_guess
                "speaking_order": [],
                "current_speaker_index": 0,
                "round_number": 0,
                "lang": "zh",
                "used_emojis": set(),  # track assigned emojis
                "vote_timer_task": None,  # asyncio task for vote countdown
                "eliminated_blank": None,  # stores info when blank is voted out
                "blank_guess_word": None,  # civilian word for blank to guess
                "player_scores": {},  # username -> score (for stars)
                "player_win_streak": {},  # username -> consecutive wins (for 🔥)
            }

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if self.room_name in ROOMS:
            room_data = ROOMS[self.room_name]
            if self.channel_name in room_data["players"]:
                username = room_data["players"][self.channel_name]
                avatar = room_data["avatars"].get(self.channel_name, "")
                lang = room_data.get("lang", "zh")

                # During an active game, bot takes over
                if room_data["status"] != "waiting":
                    if "disconnected" not in room_data:
                        room_data["disconnected"] = {}
                    if "bot_controlled" not in room_data:
                        room_data["bot_controlled"] = set()

                    room_data["disconnected"][username] = {
                        "old_channel": self.channel_name,
                        "avatar": avatar,
                    }
                    room_data["bot_controlled"].add(self.channel_name)

                    dc_msg = (
                        f"🤖 {avatar} 【{username}】断线了，机器人接管中..."
                        if lang == "zh"
                        else f"🤖 {avatar} [{username}] disconnected, bot taking over..."
                    )
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {
                            "type": "chat_message",
                            "data": {"action": "system_msg", "message": dc_msg},
                        },
                    )

                    # If this player is the current speaker, bot auto-skips after 2s
                    if (
                        room_data["status"] == "speaking"
                        and room_data["speaking_order"]
                    ):
                        idx = room_data["current_speaker_index"]
                        if (
                            idx < len(room_data["speaking_order"])
                            and room_data["speaking_order"][idx] == self.channel_name
                        ):
                            asyncio.create_task(self._bot_skip_turn())

                else:
                    # In waiting state: remove immediately
                    self._remove_player_data(room_data, self.channel_name, username)

                    leave_msg = (
                        f"🚪 {avatar} 【{username}】离开了游戏"
                        if lang == "zh"
                        else f"🚪 {avatar} [{username}] left the game"
                    )

                    if not room_data["players"] and not room_data.get("disconnected"):
                        del ROOMS[self.room_name]
                    else:
                        await self.channel_layer.group_send(
                            self.room_group_name,
                            {
                                "type": "chat_message",
                                "data": {"action": "system_msg", "message": leave_msg},
                            },
                        )
                        if self.channel_name == room_data.get("host"):
                            remaining = list(room_data["players"].keys())
                            room_data["host"] = remaining[0] if remaining else None
                        await self.broadcast_player_list()

        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def _bot_skip_turn(self):
        """Bot auto-skips the speaking turn after 2 seconds."""
        await asyncio.sleep(2)
        room_data = ROOMS.get(self.room_name)
        if not room_data or room_data["status"] != "speaking":
            return

        idx = room_data["current_speaker_index"]
        if idx >= len(room_data["speaking_order"]):
            return

        speaker_ch = room_data["speaking_order"][idx]
        if speaker_ch not in room_data.get("bot_controlled", set()):
            return  # Player reconnected before bot acted

        speaker_name = room_data["players"].get(speaker_ch, "?")
        speaker_avatar = room_data["avatars"].get(speaker_ch, "❓")
        lang = room_data.get("lang", "zh")

        skip_msg = (
            f"🤖 {speaker_avatar}【{speaker_name}】(机器人) 跳过发言"
            if lang == "zh"
            else f"🤖 {speaker_avatar}[{speaker_name}] (bot) skipped turn"
        )
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "data": {"action": "system_msg", "message": skip_msg},
            },
        )

        room_data["current_speaker_index"] += 1
        if room_data["current_speaker_index"] >= len(room_data["speaking_order"]):
            if len(room_data["alive_players"]) < 3:
                await self.end_game_inline()
                return
            await self.start_vote_phase()
        else:
            await self.broadcast_current_speaker()

    async def _bot_random_vote(self):
        """Bot votes randomly for alive players during voting phase."""
        await asyncio.sleep(3)  # Wait 3s before bot votes
        room_data = ROOMS.get(self.room_name)
        if not room_data or room_data["status"] != "voting":
            return

        bot_channels = room_data.get("bot_controlled", set())
        for bot_ch in list(bot_channels):
            if bot_ch not in room_data.get("alive_players", []):
                continue
            if bot_ch in room_data.get("votes", {}):
                continue  # Already voted somehow

            # Pick a random alive player that isn't this bot
            targets = [ch for ch in room_data["alive_players"] if ch != bot_ch]
            if targets:
                target = random.choice(targets)
                room_data["votes"][bot_ch] = target

                bot_name = room_data["players"].get(bot_ch, "?")
                bot_avatar = room_data["avatars"].get(bot_ch, "❓")
                lang = room_data.get("lang", "zh")

                vote_msg = (
                    f"🤖 {bot_avatar}【{bot_name}】(机器人) 投票了"
                    if lang == "zh"
                    else f"🤖 {bot_avatar}[{bot_name}] (bot) voted"
                )
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "chat_message",
                        "data": {"action": "system_msg", "message": vote_msg},
                    },
                )

        await self.broadcast_vote_counts()

    def _remove_player_data(self, room_data, channel, username):
        """Remove all traces of a player from room data."""
        room_data["players"].pop(channel, None)
        room_data["username_to_channel"].pop(username, None)
        avatar = room_data["avatars"].pop(channel, None)
        if avatar:
            room_data["used_emojis"].discard(avatar)
        room_data["ready_players"].discard(channel)
        if channel in room_data.get("alive_players", []):
            room_data["alive_players"].remove(channel)
        if channel in room_data.get("speaking_order", []):
            room_data["speaking_order"].remove(channel)
        room_data.get("votes", {}).pop(channel, None)

    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get("action")
        room_data = ROOMS.get(self.room_name)
        if not room_data:
            return

        if action == "join":
            await self.handle_join(data)
        elif action == "toggle_ready":
            await self.handle_toggle_ready()
        elif action == "start_game":
            await self.handle_start_game()
        elif action == "host_restart":
            await self.handle_host_restart()
        elif action == "chat_msg":
            await self.handle_chat_msg(data)
        elif action == "chat_audio":
            await self.handle_chat_audio(data)
        elif action == "end_turn":
            await self.handle_end_turn()
        elif action == "vote":
            await self.handle_vote(data)
        elif action == "cancel_vote":
            await self.handle_cancel_vote()
        elif action == "blank_guess":
            await self.handle_blank_guess(data)
        elif action == "emoji_reaction":
            await self.handle_emoji_reaction(data)
        elif action == "ping":
            pass # Keep-alive

    async def handle_join(self, data):
        room_data = ROOMS[self.room_name]
        username = data.get("username")
        lang = data.get("lang", "zh")
        room_data["lang"] = lang

        # Check for reconnection
        dc = room_data.get("disconnected", {})
        if username in dc:
            dc_info = dc.pop(username)
            old_channel = dc_info["old_channel"]
            avatar = dc_info["avatar"]

            # Cancel the grace period timer
            timer = room_data.get("dc_timers", {}).pop(username, None)
            if timer:
                timer.cancel()

            # Remove from bot control — player is back
            room_data.get("bot_controlled", set()).discard(old_channel)

            new_ch = self.channel_name

            # Migrate data from old_channel to new_channel
            room_data["players"].pop(old_channel, None)
            room_data["players"][new_ch] = username
            room_data["username_to_channel"][username] = new_ch

            room_data["avatars"].pop(old_channel, None)
            room_data["avatars"][new_ch] = avatar

            if old_channel in room_data["ready_players"]:
                room_data["ready_players"].discard(old_channel)
                room_data["ready_players"].add(new_ch)

            if old_channel in room_data["alive_players"]:
                idx = room_data["alive_players"].index(old_channel)
                room_data["alive_players"][idx] = new_ch

            if old_channel in room_data["speaking_order"]:
                idx = room_data["speaking_order"].index(old_channel)
                room_data["speaking_order"][idx] = new_ch

            if old_channel in room_data["words"]:
                room_data["words"][new_ch] = room_data["words"].pop(old_channel)

            if old_channel in room_data["votes"]:
                room_data["votes"][new_ch] = room_data["votes"].pop(old_channel)
            for voter_ch, target_ch in list(room_data["votes"].items()):
                if target_ch == old_channel:
                    room_data["votes"][voter_ch] = new_ch

            if room_data["host"] == old_channel:
                room_data["host"] = new_ch

            current_speaker = None
            if room_data["status"] == "speaking" and room_data["speaking_order"]:
                idx = room_data["current_speaker_index"]
                if idx < len(room_data["speaking_order"]):
                    speaker_ch = room_data["speaking_order"][idx]
                    current_speaker = room_data["players"].get(speaker_ch)

            word_info = room_data["words"].get(new_ch)
            host_name = room_data["players"].get(room_data["host"])

            await self.send(
                text_data=json.dumps(
                    {
                        "action": "join_success",
                        "is_spectator": False,
                        "is_reconnect": True,
                        "current_speaker": current_speaker,
                        "my_avatar": avatar,
                        "host": host_name,
                        "is_host": new_ch == room_data["host"],
                        "game_status": room_data["status"],
                        "word": word_info["word"] if word_info else None,
                        "role": word_info["role"] if word_info else None,
                    }
                )
            )

            rc_msg = (
                f"🔗 {avatar} 【{username}】重新连接了！"
                if lang == "zh"
                else f"🔗 {avatar} [{username}] reconnected!"
            )
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_message",
                    "data": {"action": "system_msg", "message": rc_msg},
                },
            )

            await self.broadcast_player_list()
            return

        # Normal new join
        if username in room_data["username_to_channel"]:
            error_msg = "Nickname already taken!" if lang == "en" else "昵称已被占用！"
            await self.send(
                text_data=json.dumps({"action": "join_error", "message": error_msg})
            )
            return

        # Assign a random emoji avatar
        available = [e for e in EMOJI_POOL if e not in room_data["used_emojis"]]
        if not available:
            available = EMOJI_POOL  # fallback: allow duplicates if pool exhausted
        avatar = random.choice(available)
        room_data["used_emojis"].add(avatar)

        room_data["players"][self.channel_name] = username
        room_data["username_to_channel"][username] = self.channel_name
        room_data["avatars"][self.channel_name] = avatar

        # Assign first player as host
        if room_data["host"] is None:
            room_data["host"] = self.channel_name

        is_spectator = room_data["status"] != "waiting"
        current_speaker = None
        if (
            is_spectator
            and room_data["status"] == "speaking"
            and room_data["speaking_order"]
        ):
            idx = room_data["current_speaker_index"]
            if idx < len(room_data["speaking_order"]):
                current_speaker_ch = room_data["speaking_order"][idx]
                current_speaker = room_data["players"].get(current_speaker_ch)

        host_name = room_data["players"].get(room_data["host"])

        await self.send(
            text_data=json.dumps(
                {
                    "action": "join_success",
                    "is_spectator": is_spectator,
                    "current_speaker": current_speaker,
                    "my_avatar": avatar,
                    "host": host_name,
                    "is_host": self.channel_name == room_data["host"],
                    "game_status": room_data["status"],
                }
            )
        )

        # Broadcast player list to everyone
        await self.broadcast_player_list()

        # Send join message
        join_msg = (
            f"{avatar} 【{username}】加入了游戏"
            if lang == "zh"
            else f"{avatar} [{username}] joined the game"
        )
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "data": {"action": "system_msg", "message": join_msg},
            },
        )

    async def handle_toggle_ready(self):
        room_data = ROOMS[self.room_name]
        if room_data["status"] != "waiting":
            return

        if self.channel_name in room_data["ready_players"]:
            room_data["ready_players"].discard(self.channel_name)
        else:
            room_data["ready_players"].add(self.channel_name)

        await self.broadcast_player_list()

    async def handle_start_game(self):
        room_data = ROOMS[self.room_name]

        # Only host can start
        if self.channel_name != room_data["host"]:
            return

        if room_data["status"] != "waiting":
            return

        channel_names = [
            ch for ch in room_data["ready_players"] if ch in room_data["players"]
        ]
        lang = room_data["lang"]

        if len(channel_names) < 3:
            error_msg = (
                "At least 3 ready players required! 👥"
                if lang == "en"
                else "至少需要3名准备好的玩家！ 👥"
            )
            await self.send(
                text_data=json.dumps({"action": "error", "message": error_msg})
            )
            return

        word_pairs = get_word_pairs(lang)
        random.shuffle(word_pairs)  # Shuffle first for more randomness
        chosen_pair = word_pairs[0]
        undercover_channel = random.choice(channel_names)
        blank_channel = (
            random.choice([ch for ch in channel_names if ch != undercover_channel])
            if len(channel_names) >= 4
            else None
        )

        room_data["alive_players"] = list(channel_names)
        room_data["words"] = {}
        room_data["round_number"] = 0

        for ch in channel_names:
            if ch == undercover_channel:
                role = "卧底 (Undercover)" if lang == "zh" else "Undercover"
                word = chosen_pair["undercover"]
            elif ch == blank_channel:
                role = "白板 (Blank)" if lang == "zh" else "Blank"
                word = (
                    "你是白板！(无词卡) 🤫"
                    if lang == "zh"
                    else "You are Blank! (No Word) 🤫"
                )
            else:
                role = "平民 (Civilian)" if lang == "zh" else "Civilian"
                word = chosen_pair["civilian"]

            room_data["words"][ch] = {"role": role, "word": word}
            await self.channel_layer.send(
                ch,
                {
                    "type": "chat_message",
                    "data": {
                        "action": "game_started",
                        "role": role,
                        "word": word,
                    },
                },
            )

        # Announce role distribution
        civilian_count = sum(
            1
            for ch in channel_names
            if ch != undercover_channel and ch != blank_channel
        )
        undercover_count = 1
        blank_count = 1 if blank_channel else 0

        if lang == "zh":
            role_msg = f"🎭 游戏开始！平民: {civilian_count}人 | 卧底: {undercover_count}人 | 白板: {blank_count}人"
        else:
            role_msg = f"🎭 Game started! Civilians: {civilian_count} | Undercover: {undercover_count} | Blank: {blank_count}"

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "data": {"action": "system_msg", "message": role_msg},
            },
        )

        # Notify all players of game status change
        await self.broadcast_player_list()

        await self.start_speaking_round()

    async def handle_host_restart(self):
        room_data = ROOMS[self.room_name]

        # Only host can restart
        if self.channel_name != room_data["host"]:
            return

        # Cancel vote timer if active
        if room_data.get("vote_timer_task"):
            room_data["vote_timer_task"].cancel()
            room_data["vote_timer_task"] = None

        lang = room_data["lang"]
        room_data["status"] = "waiting"
        room_data["ready_players"] = set()
        room_data["alive_players"] = []
        room_data["words"] = {}
        room_data["votes"] = {}
        room_data["speaking_order"] = []
        room_data["current_speaker_index"] = 0
        room_data["round_number"] = 0
        room_data["eliminated_blank"] = None
        room_data["blank_guess_word"] = None

        restart_msg = (
            "🔄 房主重置了游戏，请重新准备！"
            if lang == "zh"
            else "🔄 Host reset the game. Please ready up!"
        )
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "data": {"action": "system_msg", "message": restart_msg},
            },
        )

        # Remove bot-controlled players
        bot_channels = list(room_data.get("bot_controlled", set()))
        for bot_ch in bot_channels:
            bot_name = room_data["players"].get(bot_ch)
            if bot_name:
                self._remove_player_data(room_data, bot_ch, bot_name)
                room_data.get("disconnected", {}).pop(bot_name, None)
        room_data["bot_controlled"] = set()

        if room_data.get("host") not in room_data["players"]:
            remaining = list(room_data["players"].keys())
            room_data["host"] = remaining[0] if remaining else None

        await self.channel_layer.group_send(
            self.room_group_name,
            {"type": "chat_message", "data": {"action": "game_reset"}},
        )

        await self.broadcast_player_list()

    async def handle_chat_msg(self, data):
        room_data = ROOMS[self.room_name]
        msg = data.get("msg", "").strip()
        if not msg:
            return

        # Before game starts: anyone can chat. During game: only current speaker.
        if room_data["status"] == "waiting":
            avatar = room_data["avatars"].get(self.channel_name, "❓")
            sender = room_data["players"].get(self.channel_name, "Unknown")
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_message",
                    "data": {
                        "action": "new_chat_msg",
                        "sender": sender,
                        "avatar": avatar,
                        "msg": msg,
                    },
                },
            )
        elif self.is_current_speaker():
            avatar = room_data["avatars"].get(self.channel_name, "❓")
            sender = room_data["players"].get(self.channel_name, "Unknown")
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_message",
                    "data": {
                        "action": "new_chat_msg",
                        "sender": sender,
                        "avatar": avatar,
                        "msg": msg,
                    },
                },
            )

    async def handle_chat_audio(self, data):
        room_data = ROOMS[self.room_name]

        if room_data["status"] == "waiting":
            avatar = room_data["avatars"].get(self.channel_name, "❓")
            sender = room_data["players"].get(self.channel_name, "Unknown")
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_message",
                    "data": {
                        "action": "new_chat_audio",
                        "sender": sender,
                        "avatar": avatar,
                        "audio_data": data.get("audio_data"),
                    },
                },
            )
        elif self.is_current_speaker():
            avatar = room_data["avatars"].get(self.channel_name, "❓")
            sender = room_data["players"].get(self.channel_name, "Unknown")
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_message",
                    "data": {
                        "action": "new_chat_audio",
                        "sender": sender,
                        "avatar": avatar,
                        "audio_data": data.get("audio_data"),
                    },
                },
            )

    async def handle_end_turn(self):
        if self.is_current_speaker():
            room_data = ROOMS[self.room_name]
            room_data["current_speaker_index"] += 1
            if room_data["current_speaker_index"] >= len(room_data["speaking_order"]):
                if len(room_data["alive_players"]) < 3:
                    await self.end_game_inline()
                    return
                await self.start_vote_phase()
            else:
                await self.broadcast_current_speaker()

    async def handle_vote(self, data):
        room_data = ROOMS[self.room_name]
        if room_data["status"] != "voting":
            return
        if self.channel_name not in room_data["alive_players"]:
            return

        target_username = data.get("target")
        target_channel = room_data["username_to_channel"].get(target_username)

        if not target_channel or target_channel not in room_data["alive_players"]:
            return

        # Don't allow voting for yourself
        if target_channel == self.channel_name:
            return

        room_data["votes"][self.channel_name] = target_channel

        # Broadcast vote update (timer handles completion)
        await self.broadcast_vote_counts()

    async def handle_cancel_vote(self):
        room_data = ROOMS[self.room_name]
        if room_data["status"] != "voting":
            return
        if self.channel_name not in room_data["alive_players"]:
            return

        if self.channel_name in room_data["votes"]:
            del room_data["votes"][self.channel_name]
            await self.broadcast_vote_counts()

    async def handle_blank_guess(self, data):
        room_data = ROOMS[self.room_name]
        if room_data.get("status") != "blank_guess":
            return

        # Only the eliminated blank can make a guess
        eliminated_blank = room_data.get("eliminated_blank", {})
        if self.channel_name != eliminated_blank.get("channel"):
            return

        guess = data.get("guess", "").strip()
        if not guess:
            return

        civilian_word = room_data.get("blank_guess_word", "")
        lang = room_data["lang"]

        # Normalize for comparison (case insensitive, strip spaces)
        guess_normalized = guess.lower().strip()
        word_normalized = civilian_word.lower().strip() if civilian_word else ""

        # Check if guess matches
        is_correct = guess_normalized == word_normalized

        if is_correct:
            # Blank wins!
            if lang == "zh":
                win_msg = f"🎉 白板【{eliminated_blank.get('name', '?')}】猜对了！平民词语是「{civilian_word}」，白板获胜！🏆"
            else:
                win_msg = f'🎉 Blank [{eliminated_blank.get("name", "?")}] guessed correctly! The civilian word was "{civilian_word}", Blank wins! 🏆'

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_message",
                    "data": {"action": "system_msg", "message": win_msg},
                },
            )

            # Blank wins: gets 3 stars
            blank_username = eliminated_blank.get("name")
            if blank_username:
                current = room_data["player_scores"].get(blank_username, 0)
                room_data["player_scores"][blank_username] = current + 3
                room_data["player_win_streak"][blank_username] = (
                    room_data["player_win_streak"].get(blank_username, 0) + 1
                )

            # Reset win streaks for others
            for username in room_data["players"].values():
                if username != blank_username:
                    room_data["player_win_streak"][username] = 0

            # End game with blank as winner
            room_data["status"] = "waiting"
            room_data["ready_players"] = set()
            room_data["alive_players"] = []
            room_data["words"] = {}
            room_data["votes"] = {}
            room_data["speaking_order"] = []
            room_data["current_speaker_index"] = 0
            room_data["eliminated_blank"] = None
            room_data["blank_guess_word"] = None

            await self.broadcast_player_list()
        else:
            # Wrong guess - game continues
            if lang == "zh":
                wrong_msg = f"❌ 白板【{eliminated_blank.get('name', '?')}】猜测错误！游戏继续..."
            else:
                wrong_msg = f"❌ Blank [{eliminated_blank.get('name', '?')}] guessed wrong! Game continues..."

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_message",
                    "data": {"action": "system_msg", "message": wrong_msg},
                },
            )

            # Clear eliminated blank and continue game
            blank_channel = eliminated_blank.get("channel")
            if blank_channel and blank_channel in room_data["alive_players"]:
                room_data["alive_players"].remove(blank_channel)

            room_data["eliminated_blank"] = None
            room_data["blank_guess_word"] = None
            room_data["status"] = "waiting"

            await self.broadcast_player_list()

            # Continue game - check if enough players to continue
            if len(room_data["alive_players"]) >= 3:
                await self.start_speaking_round()
            else:
                # Not enough players, end game
                await self.end_game_inline()

    async def handle_emoji_reaction(self, data):
        emoji = data.get("emoji", "")
        target_name = data.get("target", "")

        if not emoji or not target_name:
            return

        room_data = ROOMS.get(self.room_name)
        if not room_data:
            return

        target_channel = room_data["username_to_channel"].get(target_name)
        if not target_channel:
            return

        # Get sender info from room players
        sender_username = (
            self.scope["user"].username if self.scope["user"].username else ""
        )

        # Get sender's avatar from room avatars (channel -> avatar mapping)
        sender_avatar = room_data["avatars"].get(self.channel_name, "")

        # Get target's avatar
        target_avatar = ""
        for ch, name in room_data["players"].items():
            if name == target_name:
                target_avatar = room_data["avatars"].get(ch, "")
                break

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "data": {
                    "action": "emoji_reaction",
                    "emoji": emoji,
                    "target": target_name,
                    "target_avatar": target_avatar,
                    "sender": sender_username,
                    "sender_avatar": sender_avatar,
                },
            },
        )

    async def start_vote_phase(self):
        room_data = ROOMS[self.room_name]
        room_data["status"] = "voting"
        room_data["votes"] = {}

        alive_names = [
            room_data["players"][ch]
            for ch in room_data["alive_players"]
            if ch in room_data["players"]
        ]

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "data": {
                    "action": "start_voting",
                    "alive_players": alive_names,
                    "vote_duration": 30,
                },
            },
        )

        # Start 30s vote timer
        room_data["vote_timer_task"] = asyncio.create_task(self.run_vote_timer())

        # Trigger bot votes for disconnected players
        bot_channels = room_data.get("bot_controlled", set())
        if any(ch in room_data["alive_players"] for ch in bot_channels):
            asyncio.create_task(self._bot_random_vote())

    async def run_vote_timer(self):
        try:
            await asyncio.sleep(30)
            room_data = ROOMS.get(self.room_name)
            if not room_data or room_data["status"] != "voting":
                return
            # Time's up — calculate with whoever voted; non-voters are skipped
            await self.calculate_votes()
        except asyncio.CancelledError:
            pass

    async def broadcast_vote_counts(self):
        room_data = ROOMS[self.room_name]
        # Build vote count per target username
        vote_counts = {}
        for voter_ch, target_ch in room_data["votes"].items():
            target_name = room_data["players"].get(target_ch)
            if target_name:
                vote_counts[target_name] = vote_counts.get(target_name, 0) + 1

        # Also include who has voted (by avatar)
        voters = [
            room_data["avatars"].get(ch, "❓") for ch in room_data["votes"].keys()
        ]

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "data": {
                    "action": "vote_update",
                    "vote_counts": vote_counts,
                    "voted_count": len(room_data["votes"]),
                    "total_alive": len(room_data["alive_players"]),
                },
            },
        )

    def is_current_speaker(self):
        room_data = ROOMS.get(self.room_name)
        if not room_data or room_data["status"] != "speaking":
            return False
        if not room_data["speaking_order"]:
            return False
        try:
            idx = room_data["current_speaker_index"]
            if idx >= len(room_data["speaking_order"]):
                return False
            speaker_ch = room_data["speaking_order"][idx]
            if speaker_ch not in room_data["players"]:
                return False
            return self.channel_name == speaker_ch
        except (IndexError, KeyError):
            return False

    async def start_speaking_round(self):
        room_data = ROOMS[self.room_name]
        room_data["status"] = "speaking"
        room_data["votes"] = {}
        room_data["round_number"] += 1

        # Find the blank player (if any) to ensure they don't go first
        blank_channel = None
        for ch in room_data["alive_players"]:
            if ch in room_data["words"] and "Blank" in room_data["words"][ch]["role"]:
                blank_channel = ch
                break

        # Build speaking order: shuffle, then move blank to second position if exists
        room_data["speaking_order"] = list(room_data["alive_players"])
        random.shuffle(room_data["speaking_order"])

        if blank_channel and len(room_data["speaking_order"]) > 1:
            # If blank is first, swap with second player
            if room_data["speaking_order"][0] == blank_channel:
                room_data["speaking_order"][0] = room_data["speaking_order"][1]
                room_data["speaking_order"][1] = blank_channel

        room_data["current_speaker_index"] = 0

        lang = room_data["lang"]
        round_msg = (
            f"--- 第{room_data['round_number']}轮发言 ---"
            if lang == "zh"
            else f"--- Round {room_data['round_number']} ---"
        )
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "data": {"action": "system_msg", "message": round_msg},
            },
        )

        await self.broadcast_player_list()
        await self.broadcast_current_speaker()

    async def broadcast_current_speaker(self):
        room_data = ROOMS[self.room_name]

        # Skip speakers who have disconnected
        while room_data["current_speaker_index"] < len(room_data["speaking_order"]):
            speaker_ch = room_data["speaking_order"][room_data["current_speaker_index"]]
            if speaker_ch in room_data["players"]:
                break
            room_data["current_speaker_index"] += 1

        # Check if we've gone through all speakers
        if room_data["current_speaker_index"] >= len(room_data["speaking_order"]):
            if len(room_data["alive_players"]) >= 3:
                await self.start_vote_phase()
            return

        speaker_ch = room_data["speaking_order"][room_data["current_speaker_index"]]
        current_name = room_data["players"][speaker_ch]
        current_avatar = room_data["avatars"].get(speaker_ch, "❓")
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "data": {
                    "action": "speaker_update",
                    "speaker": current_name,
                    "speaker_avatar": current_avatar,
                },
            },
        )

        # If speaker is bot-controlled, auto-skip
        if speaker_ch in room_data.get("bot_controlled", set()):
            asyncio.create_task(self._bot_skip_turn())

    async def calculate_votes(self):
        room_data = ROOMS[self.room_name]
        lang = room_data["lang"]
        round_num = room_data["round_number"]

        # Build vote result message using emojis
        # Format: Round X Voting result:
        #   😎,😜 voted 😴;
        #   😴 skipped voting.

        # Group voters by target
        target_to_voters = {}  # target_ch -> [voter_ch]
        for voter_ch, target_ch in room_data["votes"].items():
            if voter_ch not in room_data["players"]:
                continue
            target_to_voters.setdefault(target_ch, []).append(voter_ch)

        # Find who skipped
        skipped = [
            ch
            for ch in room_data["alive_players"]
            if ch in room_data["players"] and ch not in room_data["votes"]
        ]

        # Build result message
        result_lines = []
        if lang == "zh":
            result_lines.append(f"📊 第{round_num}轮投票结果:")
        else:
            result_lines.append(f"📊 Round {round_num} Voting result:")

        for target_ch, voter_chs in target_to_voters.items():
            target_avatar = room_data["avatars"].get(target_ch, "❓")
            voter_avatars = ",".join(
                [room_data["avatars"].get(ch, "❓") for ch in voter_chs]
            )
            if lang == "zh":
                result_lines.append(f"  {voter_avatars} 投了 {target_avatar};")
            else:
                result_lines.append(f"  {voter_avatars} voted {target_avatar};")

        if skipped:
            skipped_avatars = ",".join(
                [room_data["avatars"].get(ch, "❓") for ch in skipped]
            )
            if lang == "zh":
                result_lines.append(f"  {skipped_avatars} 弃票了。")
            else:
                result_lines.append(f"  {skipped_avatars} skipped voting.")

        result_msg = "\n".join(result_lines)

        # Calculate elimination
        vote_counts = {}  # target_channel -> count
        for voter_ch, target_ch in room_data["votes"].items():
            if voter_ch not in room_data["players"]:
                continue
            vote_counts[target_ch] = vote_counts.get(target_ch, 0) + 1

        max_votes = max(vote_counts.values()) if vote_counts else 0
        eliminated_channels = (
            [ch for ch, count in vote_counts.items() if count == max_votes]
            if max_votes > 0
            else []
        )

        is_tie = len(eliminated_channels) > 1 or max_votes == 0
        eliminated_name = None
        eliminated_avatar = None
        is_no_elimination = is_tie

        if is_no_elimination:
            if lang == "zh":
                result_msg += "\n⚖️ 平票！没有人出局。"
            else:
                result_msg += "\n⚖️ Tie vote! No one is eliminated."
            is_blank_eliminated = False
        else:
            eliminated_channel = eliminated_channels[0]
            eliminated_name = room_data["players"].get(eliminated_channel, "Unknown")
            eliminated_avatar = room_data["avatars"].get(eliminated_channel, "❓")

            # Check if the eliminated player is a Blank
            is_blank_eliminated = (
                eliminated_channel in room_data["words"]
                and "Blank" in room_data["words"][eliminated_channel]["role"]
            )

            if is_blank_eliminated:
                # Store eliminated blank info for guess phase
                room_data["eliminated_blank"] = {
                    "channel": eliminated_channel,
                    "name": eliminated_name,
                    "avatar": eliminated_avatar,
                }
                # Get the civilian word for the guess
                civilian_word = None
                for ch, info in room_data["words"].items():
                    if "Civilian" in info["role"]:
                        civilian_word = info["word"]
                        break
                room_data["blank_guess_word"] = civilian_word

                if lang == "zh":
                    result_msg += f"\n💀 {eliminated_avatar}【{eliminated_name}】被投票出局！(白板存活，可猜词)"
                else:
                    result_msg += f"\n💀 {eliminated_avatar} [{eliminated_name}] was voted out! (Blank survives, can guess)"
            else:
                if eliminated_channel in room_data["alive_players"]:
                    room_data["alive_players"].remove(eliminated_channel)
                if lang == "zh":
                    result_msg += (
                        f"\n💀 {eliminated_avatar}【{eliminated_name}】被投票出局！"
                    )
                else:
                    result_msg += (
                        f"\n💀 {eliminated_avatar} [{eliminated_name}] was voted out!"
                    )

        # Send result as system message in chat
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "data": {
                    "action": "vote_result_inline",
                    "message": result_msg,
                },
            },
        )

        # Update player list (to reflect eliminated status)
        await self.broadcast_player_list()

        # Check for game end conditions immediately (before next phase)
        print(
            f"[calculate_votes] is_no_elimination={is_no_elimination}, is_blank_eliminated={is_blank_eliminated}"
        )
        if not is_blank_eliminated:
            # Only check for game end if NOT blank (blank enters guess phase)
            alive_count = len(room_data["alive_players"])
            print(f"[calculate_votes] alive_count={alive_count}")
            if alive_count < 3:
                await self.end_game_inline()
                return
            # Only check win conditions if there was an elimination (not a tie/no votes)
            if not is_no_elimination:
                print(f"[calculate_votes] Checking win conditions")
                bad_guys = [
                    ch
                    for ch in room_data["alive_players"]
                    if ch in room_data["words"]
                    and (
                        "Undercover" in room_data["words"][ch]["role"]
                        or "Blank" in room_data["words"][ch]["role"]
                    )
                ]
                civilians = [
                    ch
                    for ch in room_data["alive_players"]
                    if ch in room_data["words"]
                    and "Civilian" in room_data["words"][ch]["role"]
                ]
                print(
                    f"[calculate_votes] bad_guys={len(bad_guys)}, civilians={len(civilians)}"
                )
                if not bad_guys:
                    await self.end_game_inline()
                    return
                elif len(bad_guys) >= len(civilians):
                    await self.end_game_inline()
                    return

        print(f"[calculate_votes] Calling _delayed_next_phase")
        # Schedule the next phase
        asyncio.create_task(self._delayed_next_phase(is_tie, is_blank_eliminated))

    async def _delayed_next_phase(self, is_tie, is_blank_eliminated=False):
        await asyncio.sleep(3)

        room_data = ROOMS.get(self.room_name)
        if not room_data or room_data["status"] != "voting":
            return

        lang = room_data["lang"]

        if is_blank_eliminated:
            # Enter blank guess phase
            room_data["status"] = "blank_guess"
            blank_info = room_data.get("eliminated_blank", {})
            civilian_word = room_data.get("blank_guess_word", "")

            if lang == "zh":
                guess_msg = (
                    f"🎯 白板【{blank_info.get('name', '?')}】请在聊天中输入你认为的平民词语进行猜测！"
                    if civilian_word
                    else f"🎯 白板【{blank_info.get('name', '?')}】请在聊天中输入你认为的平民词语进行猜测！"
                )
            else:
                guess_msg = (
                    f"🎯 Blank [{blank_info.get('name', '?')}] Please type your guess for the civilian word in chat!"
                    if civilian_word
                    else f"🎯 Blank [{blank_info.get('name', '?')}] Please type your guess for the civilian word in chat!"
                )

            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_message",
                    "data": {
                        "action": "blank_guess_phase",
                        "blank_name": blank_info.get("name", "?"),
                        "message": guess_msg,
                    },
                },
            )
            return

        # If it's a tie or no votes (no elimination), continue to next round
        print(
            f"[_delayed_next_phase] is_tie={is_tie}, is_blank_eliminated={is_blank_eliminated}"
        )
        if is_tie:
            print(f"[_delayed_next_phase] Continuing: is_tie is True")
            await self.start_speaking_round()
            return

        if len(room_data["alive_players"]) < 3:
            await self.end_game_inline()
            return

        bad_guys = [
            ch
            for ch in room_data["alive_players"]
            if ch in room_data["words"]
            and (
                "Undercover" in room_data["words"][ch]["role"]
                or "Blank" in room_data["words"][ch]["role"]
            )
        ]
        civilians = [
            ch
            for ch in room_data["alive_players"]
            if ch in room_data["words"] and "Civilian" in room_data["words"][ch]["role"]
        ]

        if not bad_guys:
            await self.end_game_inline()
            return
        elif len(bad_guys) >= len(civilians):
            await self.end_game_inline()
            return

        await self.start_speaking_round()

    async def end_game_inline(self):
        """Display game results as chat messages instead of switching screens."""
        room_data = ROOMS[self.room_name]
        lang = room_data["lang"]

        # Determine winner
        bad_guys = [
            ch
            for ch in room_data["alive_players"]
            if ch in room_data["words"]
            and (
                "Undercover" in room_data["words"][ch]["role"]
                or "Blank" in room_data["words"][ch]["role"]
            )
        ]
        civilians = [
            ch
            for ch in room_data["alive_players"]
            if ch in room_data["words"] and "Civilian" in room_data["words"][ch]["role"]
        ]

        if not bad_guys:
            if lang == "zh":
                winner_msg = "🏆 平民胜利！"
            else:
                winner_msg = "🏆 Civilians Win!"
            # Civilians win: each civilian gets 1 star
            for ch in civilians:
                username = room_data["players"].get(ch)
                if username:
                    current = room_data["player_scores"].get(username, 0)
                    room_data["player_scores"][username] = current + 1
                    room_data["player_win_streak"][username] = (
                        room_data["player_win_streak"].get(username, 0) + 1
                    )
            # Reset win streak for bad guys
            for ch in bad_guys:
                username = room_data["players"].get(ch)
                if username:
                    room_data["player_win_streak"][username] = 0
        elif len(bad_guys) >= len(civilians):
            if lang == "zh":
                winner_msg = "🏆 卧底胜利！"
            else:
                winner_msg = "🏆 Undercover Wins!"
            # Undercover wins: each undercover gets 2 stars
            for ch in bad_guys:
                username = room_data["players"].get(ch)
                if username:
                    current = room_data["player_scores"].get(username, 0)
                    room_data["player_scores"][username] = current + 2
                    room_data["player_win_streak"][username] = (
                        room_data["player_win_streak"].get(username, 0) + 1
                    )
            # Reset win streak for civilians
            for ch in civilians:
                username = room_data["players"].get(ch)
                if username:
                    room_data["player_win_streak"][username] = 0
        else:
            if lang == "zh":
                winner_msg = "🏆 游戏结束！"
            else:
                winner_msg = "🏆 Game Over!"
            # Reset all win streaks
            for ch in room_data["players"]:
                username = room_data["players"].get(ch)
                if username:
                    room_data["player_win_streak"][username] = 0

        # Build score display
        score_lines = []
        score_lines.append("--- " + ("得分" if lang == "zh" else "Scores") + " ---")
        for username, score in room_data["player_scores"].items():
            stars = score % 5  # Every 5 stars = 1 sun
            suns = score // 5
            win_streak = room_data["player_win_streak"].get(username, 0)

            stars_str = "🌟" * stars
            suns_str = "☀️" * suns
            streak_str = "🔥" if win_streak >= 3 else ""

            if lang == "zh":
                score_lines.append(f"{username}: {stars_str}{suns_str} {streak_str}")
            else:
                score_lines.append(f"{username}: {stars_str}{suns_str} {streak_str}")

        # Build identity reveal with words
        identity_lines = [winner_msg]
        identity_lines.append(
            "--- " + ("身份公布" if lang == "zh" else "Identities") + " ---"
        )
        for ch, info in room_data["words"].items():
            avatar = room_data["avatars"].get(ch, "❓")
            name = room_data["players"].get(ch, "?")
            role_short = info["role"]
            word = info["word"]
            if lang == "zh":
                identity_lines.append(f"{avatar}{name}: {role_short} → {word}")
            else:
                identity_lines.append(f"{avatar}{name}: {role_short} → {word}")

        # Add score display at the end
        identity_lines.append("\n" + "\n".join(score_lines))

        game_over_msg = "\n".join(identity_lines)

        # Send as system message
        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "data": {
                    "action": "game_over_inline",
                    "message": game_over_msg,
                },
            },
        )

        # Reset game state
        room_data["status"] = "waiting"
        room_data["ready_players"] = set()
        room_data["alive_players"] = []
        room_data["votes"] = {}
        room_data["speaking_order"] = []
        room_data["current_speaker_index"] = 0
        room_data["eliminated_blank"] = None
        room_data["blank_guess_word"] = None

        if room_data.get("vote_timer_task"):
            room_data["vote_timer_task"].cancel()
            room_data["vote_timer_task"] = None

        # Remove bot-controlled (disconnected) players now that game is over
        bot_channels = list(room_data.get("bot_controlled", set()))
        for bot_ch in bot_channels:
            bot_name = room_data["players"].get(bot_ch)
            if bot_name:
                bot_avatar = room_data["avatars"].get(bot_ch, "")
                self._remove_player_data(room_data, bot_ch, bot_name)
                # Also clean up disconnected entry
                room_data.get("disconnected", {}).pop(bot_name, None)

                remove_msg = (
                    f"🚪 {bot_avatar} 【{bot_name}】已从房间移除"
                    if lang == "zh"
                    else f"🚪 {bot_avatar} [{bot_name}] removed from room"
                )
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        "type": "chat_message",
                        "data": {"action": "system_msg", "message": remove_msg},
                    },
                )
        room_data["bot_controlled"] = set()

        # Reassign host if needed
        if room_data.get("host") not in room_data["players"]:
            remaining = list(room_data["players"].keys())
            room_data["host"] = remaining[0] if remaining else None

        await self.broadcast_player_list()

    async def broadcast_player_list(self):
        """Broadcast full player state to all clients."""
        room_data = ROOMS.get(self.room_name)
        if not room_data:
            return

        host_name = room_data["players"].get(room_data["host"])

        players_info = []
        for ch, name in room_data["players"].items():
            score = room_data["player_scores"].get(name, 0)
            win_streak = room_data["player_win_streak"].get(name, 0)
            stars = score % 6
            suns = score // 6

            players_info.append(
                {
                    "name": name,
                    "avatar": room_data["avatars"].get(ch, "❓"),
                    "is_ready": ch in room_data["ready_players"],
                    "is_host": ch == room_data["host"],
                    "is_alive": ch in room_data["alive_players"]
                    if room_data["status"] != "waiting"
                    else True,
                    "stars": stars,
                    "suns": suns,
                    "win_streak": win_streak,
                }
            )

        payload_data = {
            "action": "update_players",
            "players": players_info,
            "host": host_name,
            "game_status": room_data["status"],
            "ready_count": len(room_data["ready_players"]),
            "total_count": len(room_data["players"]),
        }

        await self.channel_layer.group_send(
            self.room_group_name,
            {
                "type": "chat_message",
                "data": payload_data,
                "json": json.dumps(payload_data),
            },
        )

    async def chat_message(self, event):
        if "json" in event:
            await self.send(text_data=event["json"])
        else:
            await self.send(text_data=json.dumps(event["data"]))
