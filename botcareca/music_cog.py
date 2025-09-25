import os
import asyncio
import shlex
from typing import Any, Mapping, Optional, cast
import discord
from discord import VoiceChannel
from yt_dlp import YoutubeDL
from discord.errors import DiscordException
from discord.ext import commands
from discord.ext.commands import Bot


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot: Bot = bot

        self.vc_lock = asyncio.Lock()
        self.is_playing: bool = False
        self.is_paused: bool = False
        self.repeat: bool = False

        self.music_queue: list[tuple[dict[str, str], VoiceChannel]] = []
        self.YDL_OPTIONS: dict[str, str] = {"format": "bestaudio/best"}

        self.FFMPEG_OPTIONS: dict[str, str] = {
            "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
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

    def _build_before_with_headers(
        self, headers: Optional[Mapping[str, str]], referer: str
    ) -> str:
        parts = ["-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"]
        if headers:
            ua = headers.get("User-Agent") or headers.get("user-agent") or "Mozilla/5.0"
            parts.append(f"-user_agent {shlex.quote(ua)}")
        if referer:
            parts.append(f"-referer {shlex.quote(referer)}")
        if headers:
            blob = "".join(f"{k}: {v}\r\n" for k, v in headers.items())
            parts.append(f"-headers {shlex.quote(blob)}")
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

    async def play_next(self) -> None:
        if len(self.music_queue) == 0:
            self.is_playing = False
            self.is_paused = False

            if self.vc and getattr(self.vc, "is_connected", lambda: False)():
                try:
                    await self.vc.disconnect()
                except Exception:
                    pass  # TODO: Trigger a less generic exception and log it
            return

        self.is_playing = True

        song_entry = self.music_queue[0]
        song_dict: dict[str, Any] = (
            song_entry[0] if isinstance(song_entry, (list, tuple)) else song_entry
        )
        m_url: str = str(song_dict.get("source") or "")

        if not self.repeat:
            self.music_queue.pop(0)

        if not self.vc:
            self.is_playing = False
            return

        def _after(_: Optional[Exception]) -> None:
            asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

        if os.path.isfile(m_url):
            try:
                ffmpeg_opts = getattr(self, "FFMPEG_OPTIONS", {}) or {}
                self.vc.play(
                    discord.FFmpegOpusAudio(
                        source=m_url,
                        executable="ffmpeg" if os.name != "nt" else "ffmpeg.exe",
                        **ffmpeg_opts,
                    ),
                    after=_after,
                )
            except DiscordException as e:
                print(f"[music] local play error: {e!r}")
                _after(None)
            return
        try:
            data_map: Optional[Mapping[str, Any]] = cast(
                Optional[Mapping[str, Any]],
                await asyncio.to_thread(self.ytdl.extract_info, m_url, False),
            )
        except Exception as e:
            print(f"[music] ytdl extract error: {e!r}")
            _after(None)
            return

        if not data_map:
            _after(None)
            return

        entries = cast(
            Optional[list[Optional[Mapping[str, Any]]]], data_map.get("entries")
        )
        if entries and len(entries) > 0:
            first = entries[0] or {}
            data_map = cast(Mapping[str, Any], first)

        stream_url: Optional[str] = cast(Optional[str], data_map.get("url"))

        if not stream_url:
            formats = cast(list[Mapping[str, Any]], data_map.get("formats") or [])
            for fmt in formats:
                url = cast(Optional[str], fmt.get("url"))
                acodec = cast(Optional[str], fmt.get("acodec"))
                if url and acodec != "none":
                    stream_url = url
                    break

        if not isinstance(stream_url, str) or not stream_url:
            _after(None)
            return

        try:
            ffmpeg_opts = getattr(self, "FFMPEG_OPTIONS", {}) or {}
            self.vc.play(
                discord.FFmpegOpusAudio(
                    stream_url,
                    executable="ffmpeg" if os.name != "nt" else "ffmpeg.exe",
                    **ffmpeg_opts,
                ),
                after=_after,
            )
        except Exception as e:
            print(f"[music] stream play error: {e!r}")
            _after(None)

    async def play_music(self, ctx) -> None:
        if not self.music_queue:
            self.is_playing = False
            await ctx.send("```No music to play```")
            return
        self.is_playing = True

        song_dict, voice_channel = self.music_queue[0]
        async with self.vc_lock:
            await self._ensure_vc(ctx, voice_channel)

        m_url: str = song_dict["source"]

        if not self.repeat:
            self.music_queue.pop(0)

        stream_url: str
        headers: dict[str, str] | None
        referer: str

        if os.path.isfile(m_url):
            stream_url = m_url
            headers = None
            referer = ""
        else:
            info: Optional[dict[str, Any]] = await asyncio.to_thread(
                self.ytdl.extract_info, m_url, False
            )
            if not info:
                await ctx.send("```Could not extract info for the requested track```")
                self.is_playing = False
                return

            if "entries" in info and info["entries"]:
                info = info["entries"][0] or {}

            stream_url = info.get("url") or ""
            if not stream_url:
                for fmt in info.get("formats", []) or []:
                    u = fmt.get("url")
                    if u and fmt.get("acodec") != "none":
                        stream_url = u
                        break

            if not stream_url:
                await ctx.send("```No playable formats found for this video```")
                self.is_playing = False
                return

            headers = info.get("http_headers") or {}
            referer = info.get("webpage_url") or "https://www.youtube.com"

        before_options = self._build_before_with_headers(headers, referer)
        options = self.FFMPEG_OPTIONS.get("options", "-vn")
        ffmpeg_bin = "ffmpeg" if os.name != "nt" else "ffmpeg.exe"

        def _after(err: Optional[Exception]) -> None:
            if err:
                print(f"[playback] error: {err!r}")
            asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

        try:
            self.vc.play(
                discord.FFmpegOpusAudio(
                    stream_url,
                    executable=ffmpeg_bin,
                    before_options=before_options,
                    options=options,
                ),
                after=_after,
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
