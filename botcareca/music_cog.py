import os
import asyncio
import shlex
from typing import Any, Optional
import discord
from discord import VoiceChannel
from yt_dlp import YoutubeDL
from discord.ext import commands
from discord.ext.commands import Bot
from yt_dlp.utils import ExtractorError


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot: Bot = bot

        self.vc_lock = asyncio.Lock()
        self.is_playing: bool = False
        self.is_paused: bool = False
        self.repeat: bool = False
        self.music_queue: list[tuple[dict[str, str], VoiceChannel]] = []

        self._last_ctx = None
        self._last_channel: Optional[discord.VoiceChannel] = None

        self.YDL_OPTIONS: dict[str, Any] = {
            "format": "bestaudio/best",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "default_search": "ytsearch",
            "socket_timeout": 10,
            "source_address": "0.0.0.0",
        }

        self.FFMPEG_OPTIONS = {
            "options": '-vn -filter:a "volume=0.30"',
        }

        self.vc: Optional[discord.VoiceClient] = None
        self.ytdl: YoutubeDL = YoutubeDL(self.YDL_OPTIONS)  # type: ignore

    async def _ensure_vc(self, ctx, voice_channel):
        vc = ctx.guild.voice_client

        if vc and vc.is_connected():
            if vc.channel.id != voice_channel.id:
                await vc.move_to(voice_channel)
            self.vc = vc
            return vc

        if vc and not vc.is_connected():
            try:
                await vc.disconnect(force=True)
            except Exception:
                pass
            await asyncio.sleep(0.5)

        new_vc = await voice_channel.connect(timeout=10, reconnect=True)
        self.vc = new_vc
        return new_vc

    def _before_with_headers(self, headers: dict[str, str] | None, referer: str) -> str:
        parts = [
            "-nostdin "
            "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
            "-rw_timeout 10000000 "  # 15s read/write timeout (µs)
        ]
        if headers:
            ua = headers.get("User-Agent") or headers.get("user-agent") or "Mozilla/5.0"
            blob = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
            parts += [f"-user_agent {shlex.quote(ua)}", f"-headers {shlex.quote(blob)}"]
        if referer:
            parts.append(f"-referer {shlex.quote(referer)}")
        return " ".join(parts)

    def search_yt(self, item: str) -> dict[str, str] | None:
        try:
            if item.startswith(("http://", "https://")):
                info = self.ytdl.extract_info(item, download=False)
            else:
                info = self.ytdl.extract_info(f"ytsearch1:{item}", download=False)
                if info and "entries" in info and info["entries"]:
                    info = info["entries"][0]

            if not info:
                return None

            src = info.get("webpage_url") or info.get("url")
            title = info.get("title")
            if not src or not title:
                return None

            return {"source": str(src), "title": str(title)}
        except Exception as e:
            print(f"YT search error: {e!r}")
            return None

    async def play_next(self, ctx) -> None:
        if len(self.music_queue) <= 0:
            self.is_playing = False
            self.is_paused = False
            if self.vc:
                await self.vc.disconnect()
            else:
                print("Not connected")
            return

        self.is_playing = True
        m_url = self.music_queue[0][0]["source"]

        if not self.repeat:
            self.music_queue.pop(0)

        ffmpeg_bin = "ffmpeg" if os.name != "nt" else "ffmpeg.exe"

        if os.path.isfile(m_url):
            stream_url = m_url
            before = self._before_with_headers(None, "")
        else:
            data = await asyncio.to_thread(
                self.ytdl.extract_info, m_url, download=False
            )
            headers = data.get("http_headers") or {}
            referer = data.get("webpage_url") or "https://www.youtube.com"
            before = self._before_with_headers(headers, referer)
            stream_url = data.get("url")
            if not stream_url:
                print("could not play next song, failed to extract youtube info")
                return

        if not self.vc:
            await ctx.send("```Not connected to a voice channel: can't play")
            return

        try:
            self.vc.play(
                discord.FFmpegOpusAudio(
                    stream_url,
                    executable=ffmpeg_bin,
                    before_options=before,
                    **getattr(self, "FFMPEG_OPTIONS", {}),
                ),
                after=lambda error: asyncio.run_coroutine_threadsafe(
                    self.play_next(ctx), self.bot.loop
                )
                if not error
                else print(f"Playback error: {error}"),
            )
        except Exception as e:
            print(f"[playback] start failed: {e!r}")
            await ctx.send(f"```FFmpeg failed to start: {e}```")
            self.is_playing = False

    async def play_music(self, ctx) -> None:
        if len(self.music_queue) <= 0:
            self.is_playing = False
            await ctx.send("```No music to play```")
            return
        self.is_playing = True

        song_dict, voice_channel = self.music_queue[0]
        async with self.vc_lock:
            await self._ensure_vc(ctx, voice_channel)
            self._last_ctx = ctx
            self._last_channel = voice_channel

        m_url: str = song_dict["source"]

        if not self.repeat:
            self.music_queue.pop(0)

        if os.path.isfile(m_url):
            stream_url = m_url
            before = self._before_with_headers(None, "")
        else:
            try:
                data = await asyncio.to_thread(
                    self.ytdl.extract_info, m_url, download=False
                )
                stream_url = data.get("url")
                headers = data.get("http_headers") or {}
                referer = data.get("webpage_url") or "https://www.youtube.com"
                before = self._before_with_headers(headers, referer)
                if not stream_url:
                    await ctx.send("```Could not extract a playable URL```")
                    raise ExtractorError("Could not extract a playable URL")
            except ExtractorError as e:
                await ctx.send(f"```Error extracting info: {e}```")
                return

        ffmpeg_bin = "ffmpeg" if os.name != "nt" else "ffmpeg.exe"

        if not self.vc:
            ctx.send("```Not connected to a voice channel: can't play")
            return

        try:
            self.vc.play(
                discord.FFmpegOpusAudio(
                    stream_url,
                    executable=ffmpeg_bin,
                    before_options=before,
                    **getattr(self, "FFMPEG_OPTIONS", {}),
                ),
                after=lambda error: asyncio.run_coroutine_threadsafe(
                    self.play_next(ctx), self.bot.loop
                )
                if not error
                else print(f"Playback error: {error}"),
            )
        except Exception as e:
            print(f"[playback] start failed: {e!r}")
            await ctx.send(f"```FFmpeg failed to start: {e}```")
            self.is_playing = False

    @commands.command()
    async def vstate(self, ctx):
        vc = ctx.guild.voice_client
        msg = (
            f"vc exists: {bool(vc)} | "
            f"connected: {getattr(vc, 'is_connected', lambda: False)()} | "
            f"channel: {getattr(getattr(vc, 'channel', None), 'name', None)} | "
            f"self.vc is None: {self.vc is None}"
        )
        await ctx.send(f"```{msg}```")

    @commands.command(name="forceleave")
    async def forceleave(self, ctx):
        vc = ctx.guild.voice_client
        try:
            if vc:
                await vc.disconnect(force=True)
        except Exception as e:
            await ctx.send(f"```forceleave error: {e}```")
        else:
            self.vc = None
            await ctx.send("```Forced voice disconnect (cleared).```")

    @commands.command(name="play", aliases=["p", "playing"], help="Meci tocar música")
    async def play(self, ctx, *args):
        query = " ".join(args).strip()
        if not query:
            await ctx.send("Usage: `$play <song name or URL>`")
            return

        try:
            voice_state = ctx.author.voice
            if not voice_state or not voice_state.channel:
                raise AttributeError("author not in voice")
            voice_channel = voice_state.channel
        except AttributeError:
            await ctx.send("```You must be in a voice channel to use this command```")
            return

        async with self.vc_lock:
            try:
                await self._ensure_vc(ctx, voice_channel)
                self._last_ctx = ctx
                self._last_channel = voice_channel
                await ctx.send(
                    f"🔊 Connected to **{self.vc.channel.name}**"
                    if self.vc
                    else "🔊 Connected."
                )
            except Exception as e:
                await ctx.send(f"⚠️ Could not join **{voice_channel.name}**: `{e}`")
                print(f"[play] connect/move error: {e!r}")
                return

        if self.is_paused and self.vc:
            self.is_paused = False
            self.is_playing = True
            self.vc.resume()
            await ctx.send("▶️ Resumed playback.")
            print("[play] resumed")
            return
        else:
            self.is_paused = False

        await ctx.typing()
        try:
            if os.path.isfile(query):
                song = {"source": query, "title": query}
                print(f"[play] local file: {query}")
            else:
                song = self.search_yt(query)
                if not song:
                    await ctx.send("```No results found```")
                    print(f"[play] search returned None for: {query}")
                    return
                print(f"[play] found: {song['title']} -> {song['source']}")
        except Exception as e:
            await ctx.send(f"```Search failed: {e}```")
            print(f"[play] search exception: {e!r}")
            return

        try:
            self.music_queue.append((song, voice_channel))
            if self.is_playing:
                position = len(self.music_queue)
                await ctx.send(
                    f"**#{position} - '{song['title']}'** added to the queue"
                )
                print(f"[play] queued at position {position}")
            else:
                await ctx.send(f"**'{song['title']}'** ▶️ now playing")
                print("[play] starting playback via play_music()")
                await self.play_music(ctx)
        except Exception as e:
            await ctx.send(f"```Failed to queue/play: {e}```")
            print(f"[play] queue/play exception: {e!r}")

    @commands.command(name="pause", help="Da uma pausada")
    async def pause(self, ctx):
        if self.is_playing and self.vc:
            self.is_playing = False
            self.is_paused = True
            self.vc.pause()
            await ctx.send("**Music paused.**")
        elif self.is_paused and self.vc:
            self.is_paused = False
            self.is_playing = True
            self.vc.resume()
            await ctx.send("**Music resumed.**")
        else:
            await ctx.send("**Nothing is playing right now.**")

    @commands.command(name="resume", aliases=["r"], help="Des-da uma pausada")
    async def resume(self, ctx: commands.Context) -> None:
        if self.is_paused and self.vc:
            self.is_paused = False
            self.is_playing = True
            self.vc.resume()
            await ctx.send("**Music resumed.**")
        else:
            await ctx.send("**No paused track to resume.**")

    @commands.command(name="skip", aliases=["s", "fs"], help="Pula la cancion")
    async def skip(self, ctx: commands.Context) -> None:
        if self.vc:
            self.vc.stop()
            if self.repeat and len(self.music_queue) > 0:
                self.music_queue.pop(0)
            await ctx.send("**Skipped to next track.**")
        else:
            await ctx.send("**I'm not connected to a voice channel.**")

    @commands.command(name="queue", aliases=["q"], help="Mostra a fila")
    async def queue(self, ctx: commands.Context) -> None:
        retval = ""
        for i in range(0, len(self.music_queue)):
            retval += f"#{i + 1} -" + self.music_queue[i][0]["title"] + "\n"

        if retval != "":
            await ctx.send(f"```queue:\n{retval}```")
        else:
            await ctx.send("```No music in queue```")

    @commands.command(
        name="clear", aliases=["c", "bin"], help="Para tudo e limpa a fila"
    )
    async def clear(self, ctx: commands.Context) -> None:
        if self.vc is not None and self.is_playing:
            self.vc.stop()

        self.music_queue = []

        await ctx.send("```Music queue cleared```")

    @commands.command(
        name="stop", aliases=["disconnect", "l", "d"], help="Mata o abensoado"
    )
    async def dc(self, ctx: commands.Context) -> None:
        self.is_playing = False
        self.is_paused = False

        if self.vc and self.vc.is_connected():
            await self.vc.disconnect()
            await ctx.send("```Disconnected from the voice channel```")

        self.vc = None

    @commands.command(
        name="remove", help="Remove a música da fila pelo índice (veja `$queue`)"
    )
    async def remove(self, ctx: commands.Context, index: int | None = None) -> None:
        if not self.music_queue:
            await ctx.send("```No songs in queue to remove```")
            return

        if index is None:
            await ctx.send("```Usage: $remove <index>  (see $queue for indexes)```")
            return

        idx = index - 1

        if idx < 0 or idx >= len(self.music_queue):
            await ctx.send(
                f"```Invalid index {index}. Queue has {len(self.music_queue)} songs.```"
            )
            return

        removed_song, _ = self.music_queue.pop(idx)
        await ctx.send(f"```Removed #{index}: {removed_song['title']}```")

    @commands.command(name="repeat", aliases=["loop"], help="Pete, repete e nabunda")
    async def repeat_(self, ctx: commands.Context) -> None:
        self.repeat = not self.repeat
        if self.repeat:
            await ctx.send("```Repeat mode is now ON.```")
        else:
            await ctx.send("```Repeat mode is now OFF.```")
