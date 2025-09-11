import asyncio
import discord
from discord.ext import commands
import yt_dlp

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.is_playing = False
        self.music_queue = []          # list[dict]
        self.repeat = False
        self.vc: discord.VoiceClient | None = None
        self.q_lock = asyncio.Lock()   # protect queue access

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

    # ---------- helpers ----------

    def _is_url(self, s: str) -> bool:
        return s.startswith("http://") or s.startswith("https://")

    async def ensure_voice(self, channel: discord.VoiceChannel):
        if self.vc and self.vc.is_connected():
            if self.vc.channel.id != channel.id:
                await self.vc.move_to(channel)
        else:
            self.vc = await channel.connect()

    async def _resolve_and_replace(self, idx: int, query: str, ctx: commands.Context):
        """Resolve stream info for placeholder at index `idx`."""
        song = None
        try:
            with yt_dlp.YoutubeDL(self.YDL_OPTIONS) as ydl:
                info = ydl.extract_info(query if self._is_url(query) else f"ytsearch:{query}", download=False)
                if "entries" in info:
                    info = info["entries"][0]
                song = {
                    "stream_url": info["url"],
                    "title": info.get("title", "Unknown"),
                    "page_url": info.get("webpage_url"),
                }
        except Exception as e:
            print("yt_dlp error:", e)
            await ctx.send("❌ Failed to fetch that track. Try another keyword/URL.")
            song = None

        async with self.q_lock:
            if 0 <= idx < len(self.music_queue) and self.music_queue[idx].get("_placeholder", False):
                if song:
                    self.music_queue[idx] = song
                else:
                    self.music_queue.pop(idx)

        # if first item resolved and nothing is playing, start
        if song and idx == 0 and not self.is_playing and self.vc and self.vc.is_connected():
            await self.play_music()

    # ---------- core playback ----------

    async def play_music(self):
        async with self.q_lock:
            if not self.music_queue:
                self.is_playing = False
                return
            current = self.music_queue[0]

        # wait briefly if still resolving
        if current.get("_placeholder"):
            for _ in range(50):  # ~5 seconds total
                await asyncio.sleep(0.1)
                async with self.q_lock:
                    if self.music_queue and not self.music_queue[0].get("_placeholder"):
                        current = self.music_queue[0]
                        break
            else:
                self.is_playing = False
                return

        if not self.vc or not self.vc.is_connected():
            self.is_playing = False
            return

        self.is_playing = True
        m_url = current["stream_url"]

        def _after(err: Exception | None):
            if err:
                print("FFmpeg/voice error:", err)
            fut = asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)
            try:
                fut.result()
            except Exception as e:
                print("after result error:", e)

        # Use PCMAudio for broad compatibility
        audio = discord.FFmpegPCMAudio(m_url, **self.FFMPEG_OPTIONS)
        if self.vc.is_playing():
            self.vc.stop()
        self.vc.play(audio, after=_after)

    async def play_next(self):
        try:
            async with self.q_lock:
                if not self.music_queue:
                    self.is_playing = False
                    # optional: timid auto-disconnect
                    await asyncio.sleep(2)
                    if self.vc and not self.vc.is_playing():
                        await self.vc.disconnect(); self.vc = None
                    return

                if not self.repeat and self.music_queue:
                    self.music_queue.pop(0)

                has_next = bool(self.music_queue)

            if has_next:
                await self.play_music()
            else:
                self.is_playing = False
                await asyncio.sleep(2)
                if self.vc and not self.vc.is_playing():
                    await self.vc.disconnect(); self.vc = None
        except Exception as e:
            print("play_next error:", e)
            self.is_playing = False
            if self.vc:
                try:
                    await self.vc.disconnect()
                except:
                    pass
                self.vc = None

    # ---------- commands ----------

    @commands.command(name="play", aliases=["p"], help="Plays a song from YouTube")
    async def play(self, ctx: commands.Context, *, search: str):
        voice_channel = getattr(getattr(ctx.author, "voice", None), "channel", None)
        if not voice_channel:
            await ctx.send("❌ You need to be in a voice channel!")
            return

        await self.ensure_voice(voice_channel)

        # enqueue placeholder immediately so $q shows it
        async with self.q_lock:
            self.music_queue.append({"title": "(resolving…)", "_placeholder": True})
            idx = len(self.music_queue) - 1

        await ctx.send("✅ **Queued:** (resolving…)")
        # resolve in background
        self.bot.loop.create_task(self._resolve_and_replace(idx, search, ctx))

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
        async with self.q_lock:
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
        async with self.q_lock:
            if not self.music_queue:
                await ctx.send("❌ Queue is empty.")
                return
            lines = []
            for i, s in enumerate(self.music_queue):
                t = s.get("title", "Unknown")
                if s.get("_placeholder"):
                    t += " (resolving…)"
                lines.append(f"**{i+1}. {t}**")
        await ctx.send("🎵 **Current Queue:**\n" + "\n".join(lines))

    @commands.command(name="repeat", aliases=["loop"], help="Toggles repeat mode")
    async def repeat_mode(self, ctx: commands.Context):
        self.repeat = not self.repeat
        await ctx.send(f"🔁 Repeat mode {'enabled' if self.repeat else 'disabled'}.")

    @commands.command(name="np", aliases=["nowplaying"], help="Shows the current song")
    async def now_playing(self, ctx: commands.Context):
        async with self.q_lock:
            if not self.music_queue:
                await ctx.send("❌ Nothing is playing.")
                return
            t = self.music_queue[0].get("title", "Unknown")
            if self.music_queue[0].get("_placeholder"):
                t += " (resolving...)"
        await ctx.send(f"🎶 Now Playing: **{t}**")
