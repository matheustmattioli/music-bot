import os, asyncio, discord
from discord.ext import commands
from help_cog import Help
from music_cog import Music
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.all()
intents.message_content = True
bot = commands.Bot(command_prefix='$', intents=intents)
bot.remove_command('help')


async def main():
    async with bot:
        await bot.add_cog(Music(bot))
        await bot.add_cog(Help(bot))
        await bot.start(os.getenv('TOKEN'))

if __name__ == "__main__":
    asyncio.run(main())
