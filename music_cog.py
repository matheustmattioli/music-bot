import asyncio
from functools import partial
import discord
from discord.ext import commands
import yt_dlp

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.is_playing = False
        self.music_queue = []
        self.repeat = False
        self.vc: discord.VoiceClient | None = None

        self.YDL_OPTIONS = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "default_search": "ytsearch",
            "skip_download": True,
        }
        self.FFMPEG_OPTIONS = {
            "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            "options": "-vn -loglevel warning",
        }

    def search_yt(self, query: str):
        with yt_dlp.YoutubeDL(self.YDL_OPTIONS) as ydl:
            try:
                info = ydl.extract_info(query, download=False)
                if "entries" in info:
                    info = info["entries"][0]
                # 'url' is a direct audio URL for ffmpeg, keep 'webpage_url' for display
                return {"stream_url": info["url"], "title": info.get("title", "Unknown"), "page_url": info.get("webpage_url")}
            except Exception as e:
                print("yt_dlp error:", e)
                return None

    async def ensure_voice(self, channel: discord.VoiceChannel):
        if self.vc and self.vc.is_connected():
            if self.vc.channel.id != channel.id:
                await self.vc.move_to(channel)
            return
        self.vc = await channel.connect()

    async def play_next(self):
        try:
            if not self.music_queue:
                self.is_playing = False
                # Optionally disconnect after idle
                await asyncio.sleep(3)
                if self.vc and not self.vc.is_playing():
                    await self.vc.disconnect()
                    self.vc = None
                return

            if not self.repeat:
                # advance to next item
                self.music_queue.pop(0)

            if not self.music_queue:
                self.is_playing = False
                await asyncio.sleep(3)
                if self.vc and not self.vc.is_playing():
                    await self.vc.disconnect()
                    self.vc = None
                return

            await self.play_music()
        except Exception as e:
            print("play_next error:", e)
            self.is_playing = False
            # Attempt a clean disconnect on error
            if self.vc:
                try:
                    await self.vc.disconnect()
                except:
                    pass
                self.vc = None

    async def play_music(self):
        if not self.music_queue or not self.vc or not self.vc.is_connected():
            self.is_playing = False
            return

        self.is_playing = True
        m_url = self.music_queue[0]["stream_url"]

        def _after_play(err):
            # Schedule coroutine safely on the running loop
            if err:
                print("FFmpeg/voice error:", err)
            fut = asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)
            try:
                fut.result()
            except Exception as e:
                print("after result error:", e)

        audio = discord.FFmpegPCMAudio(m_url, **self.FFMPEG_OPTIONS)
        if self.vc.is_playing():
            self.vc.stop()
        self.vc.play(audio, after=_after_play)

    @commands.command(name="play", aliases=["p"], help="Plays a song from YouTube")
    async def play(self, ctx: commands.Context, *, search: str):
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("❌ You need to be in a voice channel!")
            return

        await self.ensure_voice(ctx.author.voice.channel)

        song = self.search_yt(f"ytsearch:{search}")
        if not song:
            await ctx.send("❌ Could not fetch that track. Try another keyword.")
            return

        self.music_queue.append(song)
        await ctx.send(f"✅ **Queued:** {song['title']}")

        if not self.is_playing:
            await self.play_music()

    @commands.command(name="skip", aliases=["s"], help="Skips the current song")
    async def skip(self, ctx: commands.Context):
        if self.vc and self.vc.is_playing():
            self.vc.stop()
            await ctx.send("⏭ Skipped!")
        else:
            await ctx.send("❌ No music is playing.")

    @commands.command(name="stop", help="Stops the music and clears the queue")
    async def stop(self, ctx: commands.Context):
        self.music_queue.clear()
        self.is_playing = False
        if self.vc:
            try:
                await self.vc.disconnect()
            finally:
                self.vc = None
        await ctx.send("🛑 Stopped and cleared the queue.")

    @commands.command(name="queue", aliases=["q"], help="Shows the current queue")
    async def queue_info(self, ctx: commands.Context):
        if not self.music_queue:
            await ctx.send("❌ Queue is empty.")
            return
        queue_text = "\n".join([f"**{i+1}. {s['title']}**" for i, s in enumerate(self.music_queue)])
        await ctx.send(f"🎵 **Current Queue:**\n{queue_text}")

    @commands.command(name="repeat", aliases=["loop"], help="Toggles repeat mode")
    async def repeat_mode(self, ctx: commands.Context):
        self.repeat = not self.repeat
        await ctx.send(f"🔁 Repeat mode {'enabled' if self.repeat else 'disabled'}.")

    @commands.command(name="np", aliases=["nowplaying"], help="Shows the current song")
    async def now_playing(self, ctx: commands.Context):
        if not self.music_queue:
            await ctx.send("❌ Nothing is playing.")
        else:
            await ctx.send(f"🎶 Now Playing: **{self.music_queue[0]['title']}**")

    def cog_unload(self):
        # Called when the cog is unloaded—clean up voice
        if self.vc and self.vc.is_connected():
            coro = self.vc.disconnect()
            try:
                # fire-and-forget during shutdown
                asyncio.get_event_loop().create_task(coro)
            except RuntimeError:
                pass

async def setup(bot):
    await bot.add_cog(Music(bot))
