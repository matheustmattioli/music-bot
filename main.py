import os
import asyncio
import discord
from discord.ext import commands
from help_cog import Help
from music_cog import Music
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.all()
intents.message_content = True
bot = commands.Bot(command_prefix="$", intents=intents)
bot.remove_command("help")


async def main():
    async with bot:
        await bot.add_cog(Music(bot))
        await bot.add_cog(Help(bot))

        token = os.getenv("TOKEN")
        if token is not None:
            await bot.start(token)
        else:
            print("Discord API Access Token not available")
            exit(1)


if __name__ == "__main__":
    asyncio.run(main())
