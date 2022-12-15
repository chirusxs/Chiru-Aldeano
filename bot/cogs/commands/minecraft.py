import asyncio
import base64
import json
import random
from contextlib import suppress
from urllib.parse import quote as urlquote

import aiohttp
import aiomcrcon as rcon
import arrow
import classyjson as cj
import discord
from cryptography.fernet import Fernet
from discord.ext import commands

from bot.cogs.core.database import Database
from bot.utils.ctx import Ctx
from bot.utils.misc import SuppressCtxManager, fix_giphy_url
from bot.villager_bot import VillagerBotCluster

try:
    from bot.utils import tiler
except Exception:
    tiler = None


VALID_TILER_FILE_TYPES = {"jpg", "png", "jpeg", "gif", "mp4"}
TILER_MAX_DIM = 1600
TILER_MAX_DIM_GIF = 800


class Minecraft(commands.Cog):
    def __init__(self, bot: VillagerBotCluster):
        self.bot = bot

        self.d = bot.d
        self.k = bot.k

        self.aiohttp = bot.aiohttp
        self.fernet_key = Fernet(self.k.rcon_fernet_key)

        if tiler:
            self.tiler = tiler.Tiler("bot/data/block_palette.json")
        else:
            self.tiler = None

    @property
    def db(self) -> Database:
        return self.bot.get_cog("Database")

    @commands.command(name="servidor", aliases=["estado", "servidormc"])
    @commands.cooldown(1, 2.5, commands.BucketType.user)
    async def mcstatus(self, ctx: Ctx, host=None, port: int = None):
        """Checks the status of a given Minecraft server"""

        if host is None:
            if ctx.guild is None:
                raise commands.MissingRequiredArgument(cj.ClassyDict({"name": "host"}))

            combined = (await self.db.fetch_guild(ctx.guild.id)).mc_server
            if combined is None:
                await ctx.reply_embed(ctx.l.minecraft.mcping.shortcut_error.format(ctx.prefix))
                return
        else:
            if ctx.guild is None:
                raise commands.MissingRequiredArgument(cj.ClassyDict({"name": "host"}))

            combined = (await self.db.fetch_guild(ctx.guild.id)).mc_server
            if combined is None:
                await ctx.reply_embed(ctx.l.minecraft.mcping.shortcut_error.format(ctx.prefix))
                return

        fail = False
        jj: dict = None

        async with SuppressCtxManager(ctx.typing()):
            async with self.aiohttp.get(
                f"https://api.iapetus11.me/mc/server/status/{combined.replace('/', '%2F')}",
                # headers={"Authorization": self.k.villager_api},
            ) as res:  # fetch status from api
                if res.status == 200:
                    jj = await res.json()

                    if not jj["online"]:
                        fail = True
                else:
                    fail = True

        if fail:
            await ctx.reply(
                embed=discord.Embed(
                    color=self.bot.embed_color,
                    title=ctx.l.minecraft.mcping.title_offline.format(
                        self.d.emojis.offline, combined
                    ),
                ),
                mention_author=False,
            )

            return

        player_list = jj.get("players", [])
        if player_list is None:
            player_list = ()
        else:
            player_list = [p["username"] for p in player_list]

        players_online = jj["online_players"]

        embed = discord.Embed(
            color=self.bot.embed_color,
            title=ctx.l.minecraft.mcping.title_online.format(self.d.emojis.online, combined),
        )

        embed.add_field(name=ctx.l.minecraft.mcping.latency, value=f'{jj["latency"]}ms')
        embed.add_field(
            name=ctx.l.minecraft.mcping.version, value=("MC.CHIRUSXS.NET")
        )

        player_list_cut = []

        for p in player_list:
            if not ("§" in p or len(p) > 16 or len(p) < 3 or " " in p or "-" in p):
                player_list_cut.append(p)

        player_list_cut = player_list_cut[:24]

        if len(player_list_cut) < 1:
            embed.add_field(
                name=ctx.l.minecraft.mcping.field_online_players.name.format(
                    players_online, jj["max_players"]
                ),
                value=ctx.l.minecraft.mcping.field_online_players.value,
                inline=False,
            )
        else:
            extra = ""
            if len(player_list_cut) < players_online:
                extra = ctx.l.minecraft.mcping.and_other_players.format(
                    players_online - len(player_list_cut)
                )

            embed.add_field(
                name=ctx.l.minecraft.mcping.field_online_players.name.format(
                    players_online, jj["max_players"]
                ),
                value="`" + "`, `".join(player_list_cut) + "`" + extra,
                inline=False,
            )

        embed.set_image(
            url=f"https://api.iapetus11.me/mc/server/status/{combined}/image?v={random.random()*100000}"
        )

        if jj["favicon"] is not None:
            embed.set_thumbnail(
                url=f"https://api.iapetus11.me/mc/server/status/{combined}/image/favicon"
            )

        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="construir", aliases=["idea"])
    async def build_idea(self, ctx: Ctx):
        """Sends a random "build idea" which you could create"""

        prefix = random.choice(self.d.build_ideas["prefixes"])
        idea = random.choice(self.d.build_ideas["ideas"])

        await ctx.reply_embed(f"¡{prefix} {idea}!")

async def setup(bot: VillagerBotCluster) -> None:
    await bot.add_cog(Minecraft(bot))
