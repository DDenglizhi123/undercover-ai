import json
import random
import os
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer

# In-memory room storage. Consider Redis for production scalability.
ROOMS = {}
WORD_CACHE = {'zh': None, 'en': None}

def get_word_pairs(lang):
    if WORD_CACHE.get(lang):
        return WORD_CACHE[lang]
    filename = 'words_zh.json' if lang == 'zh' else 'words_en.json'
    try:
        words_path = os.path.join(os.path.dirname(__file__), filename)
        with open(words_path, 'r', encoding='utf-8') as f:
            WORD_CACHE[lang] = json.load(f)
    except Exception:
        WORD_CACHE[lang] = [{"civilian": "苹果", "undercover": "鸭梨"}] if lang == 'zh' else [{"civilian": "Apple", "undercover": "Pear"}]
    return WORD_CACHE[lang]

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_name = self.scope['url_route']['kwargs']['room_name']
        self.room_group_name = f'chat_{self.room_name}'

        if self.room_name not in ROOMS:
            ROOMS[self.room_name] = {
                'players': {},           # channel_name -> username
                'username_to_channel': {}, # username -> channel_name (optimization)
                'ready_players': set(),  # channel_names that are in the lobby, ready to play
                'alive_players': [],      # list of channel_names
                'words': {},             # channel_name -> {role, word}
                'votes': {},             # voter_channel -> target_channel
                'status': 'waiting',
                'speaking_order': [],
                'current_speaker_index': 0,
                'restart_votes': set(),   # channel_names that voted to restart
                'lang': 'zh'
            }

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if self.room_name in ROOMS:
            room_data = ROOMS[self.room_name]
            if self.channel_name in room_data['players']:
                username = room_data['players'].pop(self.channel_name)
                room_data['username_to_channel'].pop(username, None)
                room_data['ready_players'].discard(self.channel_name)
                
                # Cleanup empty room
                if not room_data['players']:
                    del ROOMS[self.room_name]
                elif room_data['status'] == 'waiting':
                    ready_names = [room_data['players'][ch] for ch in room_data['ready_players'] if ch in room_data['players']]
                    await self.channel_layer.group_send(
                        self.room_group_name,
                        {'type': 'chat_message', 'data': {'action': 'update_players', 'players': ready_names}}
                    )
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)

    async def receive(self, text_data):
        data = json.loads(text_data)
        action = data.get('action')
        room_data = ROOMS.get(self.room_name)
        if not room_data: return

        if action == 'join':
            await self.handle_join(data)
        elif action == 'start_game':
            await self.handle_start_game()
        elif action == 'chat_msg':
            await self.handle_chat_msg(data)
        elif action == 'chat_audio':
            await self.handle_chat_audio(data)
        elif action == 'end_turn':
            await self.handle_end_turn()
        elif action == 'vote':
            await self.handle_vote(data)
        elif action == 'propose_restart':
            await self.handle_propose_restart()
        elif action == 'vote_restart':
            await self.handle_vote_restart()
        elif action == 'play_again':
            await self.handle_play_again()

    async def handle_join(self, data):
        room_data = ROOMS[self.room_name]
        username = data.get('username')
        lang = data.get('lang', 'zh')
        room_data['lang'] = lang

        if username in room_data['username_to_channel']:
            error_msg = 'Nickname already taken!' if lang == 'en' else '昵称已被占用！'
            await self.send(text_data=json.dumps({'action': 'join_error', 'message': error_msg}))
            return

        room_data['players'][self.channel_name] = username
        room_data['username_to_channel'][username] = self.channel_name
        
        is_spectator = room_data['status'] != 'waiting'
        current_speaker = None
        if is_spectator and room_data['status'] == 'speaking' and room_data['speaking_order']:
            current_speaker_ch = room_data['speaking_order'][room_data['current_speaker_index']]
            current_speaker = room_data['players'].get(current_speaker_ch)

        await self.send(text_data=json.dumps({
            'action': 'join_success',
            'is_spectator': is_spectator,
            'current_speaker': current_speaker
        }))

        if not is_spectator:
            room_data['ready_players'].add(self.channel_name)
            ready_names = [room_data['players'][ch] for ch in room_data['ready_players'] if ch in room_data['players']]
            await self.channel_layer.group_send(
                self.room_group_name,
                {'type': 'chat_message', 'data': {'action': 'update_players', 'players': ready_names}}
            )

    async def handle_start_game(self):
        room_data = ROOMS[self.room_name]
        channel_names = [ch for ch in room_data['ready_players'] if ch in room_data['players']]
        lang = room_data['lang']
        
        if len(channel_names) < 3:
            error_msg = 'At least 3 players required! 👥' if lang == 'en' else '至少需要3人！ 👥'
            await self.send(text_data=json.dumps({'action': 'error', 'message': error_msg}))
            return

        word_pairs = get_word_pairs(lang)
        chosen_pair = random.choice(word_pairs)
        undercover_channel = random.choice(channel_names)
        blank_channel = random.choice([ch for ch in channel_names if ch != undercover_channel]) if len(channel_names) >= 4 else None

        room_data['alive_players'] = list(channel_names)
        room_data['words'] = {}
        room_data['restart_votes'] = set() # Reset restart votes when a new game starts

        for ch in channel_names:
            if ch == undercover_channel:
                role = "卧底 (Undercover)" if lang == 'zh' else "Undercover"
                word = chosen_pair['undercover']
            elif ch == blank_channel:
                role = "白板 (Blank)" if lang == 'zh' else "Blank"
                word = "你是白板！(无词卡) 🤫" if lang == 'zh' else "You are Blank! (No Word) 🤫"
            else:
                role = "平民 (Civilian)" if lang == 'zh' else "Civilian"
                word = chosen_pair['civilian']
                
            room_data['words'][ch] = {'role': role, 'word': word}
            await self.channel_layer.send(ch, {
                'type': 'chat_message', 
                'data': {'action': 'game_started', 'role': role, 'word': word}
            })
        
        await self.start_speaking_round()

    async def handle_chat_msg(self, data):
        if self.is_current_speaker():
            room_data = ROOMS[self.room_name]
            await self.channel_layer.group_send(self.room_group_name, {
                'type': 'chat_message', 
                'data': {
                    'action': 'new_chat_msg', 
                    'sender': room_data['players'][self.channel_name], 
                    'msg': data.get('msg')
                }
            })

    async def handle_chat_audio(self, data):
        if self.is_current_speaker():
            room_data = ROOMS[self.room_name]
            await self.channel_layer.group_send(self.room_group_name, {
                'type': 'chat_message', 
                'data': {
                    'action': 'new_chat_audio', 
                    'sender': room_data['players'][self.channel_name], 
                    'audio_data': data.get('audio_data')
                }
            })

    async def handle_end_turn(self):
        if self.is_current_speaker():
            room_data = ROOMS[self.room_name]
            room_data['current_speaker_index'] += 1
            if room_data['current_speaker_index'] >= len(room_data['speaking_order']):
                room_data['status'] = 'voting'
                alive_names = [room_data['players'][ch] for ch in room_data['alive_players']]
                await self.channel_layer.group_send(self.room_group_name, {
                    'type': 'chat_message', 
                    'data': {'action': 'start_voting', 'alive_players': alive_names}
                })
            else:
                await self.broadcast_current_speaker()

    async def handle_vote(self, data):
        room_data = ROOMS[self.room_name]
        if self.channel_name not in room_data['alive_players']: return
        
        target_username = data.get('target')
        target_channel = room_data['username_to_channel'].get(target_username)
        
        if target_channel:
            room_data['votes'][self.channel_name] = target_channel
            if len(room_data['votes']) == len(room_data['alive_players']):
                await self.calculate_votes()

    async def handle_propose_restart(self):
        room_data = ROOMS[self.room_name]
        if room_data['status'] in ['waiting', 'voting']: # Prevent restart during waiting or voting phase if desired, or allow it
            pass 
        
        # Add the proposer's vote automatically
        room_data['restart_votes'].add(self.channel_name)
        proposer_name = room_data['players'][self.channel_name]
        
        # Broadcast proposal to the room
        await self.channel_layer.group_send(self.room_group_name, {
            'type': 'chat_message', 
            'data': {
                'action': 'restart_proposed',
                'proposer': proposer_name,
                'current_votes': len(room_data['restart_votes']),
                'total_needed': (len(room_data['players']) // 2) + 1 # Simple majority
            }
        })
        await self.check_restart_votes()

    async def handle_vote_restart(self):
        room_data = ROOMS[self.room_name]
        if self.channel_name in room_data['players']:
            room_data['restart_votes'].add(self.channel_name)
            voter_name = room_data['players'][self.channel_name]
            
            await self.channel_layer.group_send(self.room_group_name, {
                'type': 'chat_message', 
                'data': {
                    'action': 'restart_progress',
                    'voter': voter_name,
                    'current_votes': len(room_data['restart_votes']),
                    'total_needed': (len(room_data['players']) // 2) + 1
                }
            })
            await self.check_restart_votes()

    async def check_restart_votes(self):
        room_data = ROOMS[self.room_name]
        total_players = len(room_data['players'])
        votes_needed = (total_players // 2) + 1
        
        if len(room_data['restart_votes']) >= votes_needed:
            # Restart condition met
            await self.channel_layer.group_send(self.room_group_name, {
                'type': 'chat_message', 
                'data': {
                    'action': 'system_msg',
                    'message': '🔄 多数玩家同意，游戏重新开始！' if room_data['lang'] == 'zh' else '🔄 Majority agreed, game restarting!'
                }
            })
            await asyncio.sleep(2) # Brief pause before restarting
            # Mark all current players as ready for the restart
            room_data['ready_players'] = set(room_data['players'].keys())
            await self.handle_start_game()

    def is_current_speaker(self):
        room_data = ROOMS.get(self.room_name)
        if not room_data or room_data['status'] != 'speaking': return False
        try:
            return self.channel_name == room_data['speaking_order'][room_data['current_speaker_index']]
        except IndexError:
            return False

    async def start_speaking_round(self):
        room_data = ROOMS[self.room_name]
        room_data['status'] = 'speaking'
        room_data['votes'] = {} 
        room_data['speaking_order'] = list(room_data['alive_players'])
        random.shuffle(room_data['speaking_order'])
        room_data['current_speaker_index'] = 0
        await self.broadcast_current_speaker()

    async def broadcast_current_speaker(self):
        room_data = ROOMS[self.room_name]
        idx = room_data['current_speaker_index']
        speaker_ch = room_data['speaking_order'][idx]
        current_name = room_data['players'][speaker_ch]
        await self.channel_layer.group_send(self.room_group_name, {
            'type': 'chat_message', 
            'data': {'action': 'speaker_update', 'speaker': current_name}
        })

    async def calculate_votes(self):
        room_data = ROOMS[self.room_name]
        lang = room_data['lang']
        
        aggregated_votes = {} # target_name -> [voter_names]
        vote_counts = {}      # target_channel -> count
        
        for voter_ch, target_ch in room_data['votes'].items():
            target_name = room_data['players'][target_ch]
            voter_name = room_data['players'][voter_ch]
            aggregated_votes.setdefault(target_name, []).append(voter_name)
            vote_counts[target_ch] = vote_counts.get(target_ch, 0) + 1
            
        max_votes = max(vote_counts.values()) if vote_counts else 0
        eliminated_channels = [ch for ch, count in vote_counts.items() if count == max_votes]
        
        is_tie = len(eliminated_channels) > 1
        
        if is_tie:
            msg = '⚖️ 出现平票！没有人出局。' if lang == 'zh' else '⚖️ Tie vote! No one is eliminated.'
        else:
            eliminated_channel = eliminated_channels[0]
            eliminated_name = room_data['players'][eliminated_channel]
            room_data['alive_players'].remove(eliminated_channel)
            msg = f'💀 【{eliminated_name}】被投票出局！' if lang == 'zh' else f'💀 [{eliminated_name}] was voted out!'

        all_eliminated_names = [name for ch, name in room_data['players'].items() if ch not in room_data['alive_players']]

        await self.channel_layer.group_send(self.room_group_name, {
            'type': 'chat_message', 
            'data': {
                'action': 'vote_result', 
                'message': msg, 
                'aggregated_votes': aggregated_votes, 
                'eliminated_players': all_eliminated_names
            }
        })

        # Schedule the next phase as a background task so the receive() handler
        # can return, allowing the last voter's consumer to process the vote_result.
        asyncio.create_task(self._delayed_next_phase(is_tie))

    async def _delayed_next_phase(self, is_tie):
        await asyncio.sleep(5)

        room_data = ROOMS.get(self.room_name)
        if not room_data or room_data['status'] != 'voting':
            return  # Room deleted or game state changed (e.g. restart)

        lang = room_data['lang']

        if not is_tie:
            # Check win conditions
            bad_guys = [ch for ch in room_data['alive_players'] if "Undercover" in room_data['words'][ch]['role'] or "Blank" in room_data['words'][ch]['role']]
            civilians = [ch for ch in room_data['alive_players'] if "Civilian" in room_data['words'][ch]['role']]
            
            if not bad_guys:
                await self.end_game('👑 Civilians/平民', '👑 平民胜利！所有坏人已出局。' if lang == 'zh' else '👑 Civilians Win! All bad guys eliminated.')
                return
            elif len(bad_guys) >= len(civilians):
                await self.end_game('😈 Bad Guys/坏人', '😈 坏人胜利！平民人数不足。' if lang == 'zh' else '😈 Bad guys Win! Too many civilians died.')
                return

        await self.start_speaking_round()

    async def handle_play_again(self):
        room_data = ROOMS.get(self.room_name)
        if not room_data or room_data['status'] != 'waiting':
            return
        # Mark this player as ready and broadcast the ready player list
        room_data['ready_players'].add(self.channel_name)
        ready_names = [room_data['players'][ch] for ch in room_data['ready_players'] if ch in room_data['players']]
        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'chat_message', 'data': {'action': 'update_players', 'players': ready_names}}
        )

    async def end_game(self, winner, message):
        room_data = ROOMS[self.room_name]
        room_data['status'] = 'waiting'
        room_data['ready_players'] = set()  # Reset: players must click "Play Again" to rejoin lobby
        all_identities = {room_data['players'][ch]: info for ch, info in room_data['words'].items()}
        await self.channel_layer.group_send(self.room_group_name, {
            'type': 'chat_message', 
            'data': {
                'action': 'game_over', 
                'winner': winner, 
                'message': message, 
                'identities': all_identities
            }
        })

    async def chat_message(self, event):
        await self.send(text_data=json.dumps(event['data']))

