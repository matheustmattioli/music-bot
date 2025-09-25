# help_cog.py (only changed the shown prefix)
import discord
from discord.ext import commands


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        name="help", aliases=["h"], help="Displays all available commands"
    )
    async def help_command(self, ctx):
        embed = discord.Embed(
            title="🎵 Music Bot Commands",
            description="Here are the available commands for music control:",
            color=discord.Color.blue(),
        )

        embed.add_field(
            name="▶ Play",
            value="`$play <song>` or `$p <song>`",
            inline=False,
        )
        embed.add_field(
            name="⏸️ Pause",
            value="`$pause` — pause if playing, resume if already paused",
            inline=False,
        )
        embed.add_field(
            name="⏭️ Skip",
            value="`$skip` or `$s`",
            inline=False,
        )
        embed.add_field(
            name="📜 Queue",
            value="`$queue` or `$q`",
            inline=False,
        )
        embed.add_field(
            name="🔁 Repeat",
            value="`$repeat` or `$loop`",
            inline=False,
        )
        embed.add_field(
            name="▶️ Resume",
            value="`$resume` or `$r`",
            inline=False,
        )
        embed.add_field(
            name="🗑️ Remove",
            value="`$remove <index>` — remove a song from the queue by its number (see `$queue`)",
            inline=False,
        )
        embed.add_field(
            name="🧹 Clear",
            value="`$clear` — clear the entire queue (and stop playback)",
            inline=False,
        )

        embed.set_footer(
            text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url
        )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Help(bot))
