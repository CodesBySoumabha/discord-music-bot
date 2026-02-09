from discord.ext import commands
import discord
import yt_dlp
import asyncio
from collections import deque
from utils.spotify_api import get_spotify_track_query

class Song:
    def __init__(self, title, url, duration=None, requester=None):
        self.title = title
        self.url = url
        self.duration = duration
        self.requester = requester

    def __str__(self):
        duration_str = ""
        if self.duration:
            minutes, seconds = divmod(self.duration, 60)
            duration_str = f" ({int(minutes)}:{int(seconds):02d})"
        return f"**{self.title}**{duration_str}"

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = {}
        self.current_song = {}
        self.is_playing = {}
        self.max_queue_size = 100
        self.max_user_songs = 3

        self.ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'extractaudio': False,
            'default_search': 'ytsearch',
            'source_address': '0.0.0.0',
            'socket_timeout': 10,
            'retries': 1,
        }

        self.ydl = yt_dlp.YoutubeDL(self.ydl_opts)

    def get_guild_queue(self, guild_id):
        if guild_id not in self.queue:
            self.queue[guild_id] = deque()
        return self.queue[guild_id]

    def extract_info_sync(self, query):
        return self.ydl.extract_info(query, download=False)

    async def process_song(self, query, requester):
        if "spotify.com/track" in query:
            query, error = await get_spotify_track_query(query)
            if error:
                return None, error

        if not query.startswith(('http://', 'https://')):
            query = f"ytsearch1:{query}"

        try:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, self.extract_info_sync, query)

            if 'entries' in info and len(info['entries']) > 0:
                info = info['entries'][0]
            elif 'entries' in info and len(info['entries']) == 0:
                return None, "No results found."

            url = info.get('url')
            title = info.get('title', 'Unknown Title')
            duration = info.get('duration', 0)

            if not url:
                return None, "Could not extract audio URL."

            song = Song(title, url, duration, requester)
            return song, None

        except Exception as e:
            return None, f"Error retrieving video: {e}"

    async def play_next(self, ctx):
        guild_id = ctx.guild.id
        guild_queue = self.get_guild_queue(guild_id)

        if not guild_queue:
            self.is_playing[guild_id] = False
            self.current_song[guild_id] = None
            await ctx.send("🎵 Queue is empty. Use `!play <song>` to add songs!")
            return

        song = guild_queue.popleft()
        self.current_song[guild_id] = song

        vc = ctx.voice_client
        if not vc:
            return

        ffmpeg_opts = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn',
        }

        def after_playing(error):
            if error:
                print(f'Player error: {error}')

            coro = self.play_next(ctx)
            fut = asyncio.run_coroutine_threadsafe(coro, self.bot.loop)
            try:
                fut.result()
            except Exception as e:
                print(f'Error playing next song: {e}')

        try:
            audio_source = discord.FFmpegPCMAudio(song.url, **ffmpeg_opts)
            vc.play(audio_source, after=after_playing)

            requester_str = f" (requested by {song.requester.display_name})" if song.requester else ""
            await ctx.send(f"▶️ Now playing: {song}{requester_str}")

        except Exception as e:
            await ctx.send(f"❌ FFmpeg playback error: {e}")
            await self.play_next(ctx)

    @commands.command(aliases=['p'])
    async def play(self, ctx, *, query):
        if not ctx.author.voice:
            await ctx.send("❌ You're not in a voice channel.")
            return

        voice_channel = ctx.author.voice.channel
        permissions = voice_channel.permissions_for(ctx.guild.me)
        if not permissions.connect or not permissions.speak:
            await ctx.send("❌ I don't have permission to connect or speak in that voice channel.")
            return

        status_msg = await ctx.send("🔍 Processing song...")

        song, error = await self.process_song(query, ctx.author)
        if error:
            await status_msg.edit(content=f"❌ {error}")
            return

        vc = ctx.voice_client
        if not vc:
            try:
                vc = await voice_channel.connect()
            except Exception as e:
                await status_msg.edit(content=f"❌ Failed to connect: {e}")
                return
        elif vc.channel != voice_channel:
            try:
                await vc.move_to(voice_channel)
            except Exception as e:
                await status_msg.edit(content=f"❌ Failed to move to voice channel: {e}")
                return

        guild_id = ctx.guild.id
        guild_queue = self.get_guild_queue(guild_id)

        if len(guild_queue) >= self.max_queue_size:
            await status_msg.edit(content=f"❌ Queue is full! Maximum {self.max_queue_size} songs allowed.")
            return

        user_songs_in_queue = sum(1 for s in guild_queue if s.requester == ctx.author)
        if user_songs_in_queue >= self.max_user_songs:
            await status_msg.edit(content=f"❌ You already have {self.max_user_songs} songs in the queue! Wait for them to play or use `!remove` to remove one.")
            return

        guild_queue.append(song)

        if not self.is_playing.get(guild_id, False):
            self.is_playing[guild_id] = True
            await status_msg.edit(content="🎵 Starting playback...")
            await self.play_next(ctx)
        else:
            queue_position = len(guild_queue)
            user_songs_count = sum(1 for s in guild_queue if s.requester == ctx.author)
            await status_msg.edit(content=f"✅ Added to queue: {song} (Position: {queue_position}) | Your songs in queue: {user_songs_count}/{self.max_user_songs}")

    @commands.command(aliases=['rm'])
    async def remove(self, ctx, position: int):
        guild_id = ctx.guild.id
        guild_queue = self.get_guild_queue(guild_id)

        if not guild_queue:
            await ctx.send("📝 Queue is empty.")
            return

        if position < 1 or position > len(guild_queue):
            await ctx.send(f"❌ Invalid position. Queue has {len(guild_queue)} songs.")
            return

        queue_list = list(guild_queue)
        removed_song = queue_list.pop(position - 1)
        self.queue[guild_id] = deque(queue_list)

        await ctx.send(f"🗑️ Removed: {removed_song}")

    # Other commands remain unchanged...

async def setup(bot):
    await bot.add_cog(Music(bot))
