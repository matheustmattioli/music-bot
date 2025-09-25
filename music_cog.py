import os
import asyncio
from typing import Any, Mapping, Optional, cast
import discord
from discord import VoiceChannel
from yt_dlp import YoutubeDL
from discord.errors import DiscordException
from discord.ext import commands
from discord.ext.commands import Bot
from yt_dlp.utils import ExtractorError
from youtubesearchpython import VideosSearch


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot: Bot = bot

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

    def search_yt(self, item) -> dict[str, str] | None:
        try:
            if item.startswith("https://"):
                extracted_info = self.ytdl.extract_info(item, download=False)

                title = extracted_info.get("title")
                if title is None:
                    raise ExtractorError("Error while searching for music video")
                return {"source": item, "title": title}

            search = VideosSearch(item, limit=1)
            search_result: str | dict[Any, Any] = search.result()

            if isinstance(search_result, dict):
                return {
                    "source": search_result["result"][0]["link"],
                    "title": search_result["result"][0]["title"],
                }
            else:
                raise ExtractorError("Error while searching for music video")
        except ExtractorError as e:
            print(f"YT search error: {e}")
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
                        source=m_url, executable="ffmpeg.exe", **ffmpeg_opts
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
                    stream_url, executable="ffmpeg.exe", **ffmpeg_opts
                ),
                after=_after,
            )
        except Exception as e:
            print(f"[music] stream play error: {e!r}")
            _after(None)

    async def play_music(self, ctx) -> None:
        if len(self.music_queue) > 0:
            self.is_playing = True
        else:
            self.is_playing = False
            await ctx.send("```No music to play```")
            return

        m_url = self.music_queue[0][0]["source"]

        if self.vc is None or not self.vc.is_connected():
            self.vc = await self.music_queue[0][1].connect()

            if self.vc is None:
                return await ctx.send("```Unable to connect```")
        else:
            await self.vc.move_to(self.music_queue[0][1])

        if not self.repeat:
            self.music_queue.pop(0)

        if os.path.isfile(m_url):
            source = m_url
        else:
            try:
                data = await asyncio.to_thread(
                    self.ytdl.extract_info, m_url, download=False
                )
                source = data.get("url")
                if not source:
                    await ctx.send("```Could not extract a playable URL```")
                    raise ExtractorError("Could not extract a playable URL")
            except ExtractorError as e:
                await ctx.send(f"```Error extracting info: {e}```")
                return

        self.vc.play(
            discord.FFmpegOpusAudio(
                source,
                executable="ffmpeg.exe",
                **getattr(self, "FFMPEG_OPTIONS", {}),
            ),
            after=lambda error: asyncio.run_coroutine_threadsafe(
                self.play_next(), self.bot.loop
            )
            if not error
            else print(f"Playback error: {error}"),
        )

    @commands.command(name="play", aliases=["p", "playing"], help="Meci tocar música")
    async def play(self, ctx, *args):
        query = " ".join(args)

        try:
            voice_channel = ctx.author.voice.channel
        except DiscordException:
            await ctx.send("```You must be in a voice channel to use this command```")
            return

        if not self.vc or not self.vc.is_connected():
            try:
                self.vc = await voice_channel.connect()
                await ctx.send(f"Connected to **{voice_channel.name}**")
            except Exception as e:
                await ctx.send(f"Could not connect to **{voice_channel.name}**: `{e}`")
                return

        if self.is_paused and self.vc:
            self.vc.resume()
            return

        # TODO: check if play song from file in fact works
        if os.path.isfile(query):
            song = {"source": query, "title": query}
        else:
            song = self.search_yt(query)
            if not song:
                await ctx.send("```No results found```")
                return

        self.music_queue.append((song, voice_channel))

        if self.is_playing:
            position = len(self.music_queue)
            await ctx.send(f"**#{position} -'{song['title']}'** added to the queue")
        else:
            await ctx.send(f"**'{song['title']}'** now playing")

            await self.play_music(ctx)

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

    @commands.command(name="remove", help="Remove a última música adicionada na phila")
    async def re_(self, ctx: commands.Context) -> None:
        if not self.music_queue:
            await ctx.send("```No songs in queue to remove```")
            return None

        self.music_queue.pop()
        await ctx.send("```last song removed```")

    @commands.command(name="repeat", aliases=["loop"], help="Pete, repete e nabunda")
    async def repeat_(self, ctx: commands.Context) -> None:
        self.repeat = not self.repeat  # Toggle the repeat state
        if self.repeat:
            await ctx.send("```Repeat mode is now ON.```")
        else:
            await ctx.send("```Repeat mode is now OFF.```")
