import os
import asyncio
from typing import Any
import discord
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

        self.music_queue = []
        self.YDL_OPTIONS: dict[str, str] = {"format": "bestaudio/best"}
        self.FFMPEG_OPTIONS = {
            "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
            "options": '-vn -filter:a "volume=0.30"',
        }

        self.vc = None
        self.ytdl = YoutubeDL(self.YDL_OPTIONS)  # type: ignore

    def search_yt(self, item):
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

    async def play_next(self):
        if len(self.music_queue) > 0:
            self.is_playing = True
            m_url = self.music_queue[0][0]["source"]

            if not self.repeat:
                self.music_queue.pop(0)

            if os.path.isfile(m_url):
                self.vc.play(
                    discord.FFmpegOpusAudio(source=m_url, executable="ffmpeg.exe"),
                    after=lambda e: asyncio.run_coroutine_threadsafe(
                        self.play_next(), self.bot.loop
                    ),
                )
            else:
                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(
                    None, lambda: self.ytdl.extract_info(m_url, download=False)
                )
                song = data["url"]
                self.vc.play(
                    discord.FFmpegOpusAudio(
                        song, executable="ffmpeg.exe", **self.FFMPEG_OPTIONS
                    ),
                    after=lambda e: asyncio.run_coroutine_threadsafe(
                        self.play_next(), self.bot.loop
                    ),
                )
        else:
            self.is_playing = False
            self.is_paused = False
            await self.vc.disconnect()

    async def play_music(self, ctx):
        if len(self.music_queue) > 0:
            self.is_playing = True
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
                self.vc.play(
                    discord.FFmpegOpusAudio(source=m_url, executable="ffmpeg.exe"),
                    after=lambda e: asyncio.run_coroutine_threadsafe(
                        self.play_next(), self.bot.loop
                    ),
                )
            else:
                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(
                    None, lambda: self.ytdl.extract_info(m_url, download=False)
                )
                song = data["url"]
                self.vc.play(
                    discord.FFmpegOpusAudio(
                        song, executable="ffmpeg.exe", **self.FFMPEG_OPTIONS
                    ),
                    after=lambda e: asyncio.run_coroutine_threadsafe(
                        self.play_next(), self.bot.loop
                    ),
                )
        else:
            self.is_playing = False

    @commands.command(name="play", aliases=["p", "playing"], help="Toca o bamgui")
    async def play(self, ctx, *args):
        query = " ".join(args)
        try:
            voice_channel = ctx.author.voice.channel
        except DiscordException:
            await ctx.send("```Not in a voice channel```")
            return
        if self.is_paused:
            self.vc.resume()
        else:
            if os.path.isfile(query):
                song = {}
                song["source"] = query
                song["title"] = query
            else:
                song = self.search_yt(query)
            if type(song) is not type(True):
                await ctx.send(
                    "```Deu bostum. Nao encontrou esse bangui nao. Pode ser live ou playlist essa porra q vc colocou pra tocar.```"
                )
            else:
                if self.is_playing:
                    await ctx.send(
                        f"**#{len(self.music_queue) + 2} -'{song['title']}'** added to the queue"
                    )
                else:
                    await ctx.send(f"**'{song['title']}'** added to the queue")
                self.music_queue.append([song, voice_channel])
                if self.is_playing is not False:
                    await self.play_music(ctx)

    @commands.command(name="pause", help="Da uma pausada")
    async def pause(self, ctx, *args):
        if self.is_playing:
            self.is_playing = False
            self.is_paused = True
            self.vc.pause()
        elif self.is_paused:
            self.is_paused = False
            self.is_playing = True
            self.vc.resume()

    @commands.command(name="resume", aliases=["r"], help="Des-da uma pausada")
    async def resume(self, ctx, *args):
        if self.is_paused:
            self.is_paused = False
            self.is_playing = True
            self.vc.resume()

    @commands.command(name="skip", aliases=["s", "fs"], help="Pula la cancion")
    async def skip(self, ctx):
        if self.vc is not None and self.vc:
            self.vc.stop()
            if self.repeat and len(self.music_queue) > 0:
                self.music_queue.pop(0)

    @commands.command(name="queue", aliases=["q"], help="Mostra a fila")
    async def queue(self, ctx):
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
    async def clear(self, ctx):
        if self.vc is not None and self.is_playing:
            self.vc.stop()
        self.music_queue = []
        await ctx.send("```Music queue cleared```")

    @commands.command(
        name="stop", aliases=["disconnect", "l", "d"], help="Mata o abensoado"
    )
    async def dc(self, ctx):
        self.is_playing = False
        self.is_paused = False
        await self.vc.disconnect()

    @commands.command(name="remove", help="Remove a última música adicionada na phila")
    async def re(self, ctx):
        self.music_queue.pop()
        await ctx.send("```last song removed```")

    @commands.command(name="repeat", aliases=["loop"], help="Pete, repete e nabunda")
    async def repeat(self, ctx):
        self.repeat = not self.repeat  # Toggle the repeat state
        if self.repeat:
            await ctx.send("```Repeat mode is now ON.```")
        else:
            await ctx.send("```Repeat mode is now OFF.```")
