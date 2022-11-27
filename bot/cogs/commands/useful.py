import asyncio
import io
import json
import os
import secrets
import time
from contextlib import suppress
from typing import Any, Optional
from urllib.parse import quote as urlquote

import aiofiles
import aiohttp
import arrow
import async_cse
import discord
import moviepy.editor
from discord.app_commands import command as slash_command
from discord.ext import commands, tasks
from PIL import ExifTags, Image

from common.models.system_stats import SystemStats

from bot.cogs.core.database import Database
from bot.cogs.core.paginator import Paginator
from bot.models.translation import Translation
from bot.utils.ctx import Ctx
from bot.utils.misc import (
    SuppressCtxManager,
    clean_text,
    fetch_aprox_ban_count,
    get_timedelta_granularity,
    is_valid_image_res,
    parse_timedelta,
    read_limited,
    shorten_chunks,
)
from bot.villager_bot import VillagerBotCluster


class Useful(commands.Cog):
    def __init__(self, bot: VillagerBotCluster):
        self.bot = bot

        self.d = bot.d
        self.karen = bot.karen
        self.google = async_cse.Search(bot.k.google_search)
        self.aiohttp = bot.aiohttp

        self.snipes = dict[int, tuple[discord.Message, float]]()
        self.clear_snipes.start()

    @property
    def db(self) -> Database:
        return self.bot.get_cog("Database")

    @property
    def paginator(self) -> Paginator:
        return self.bot.get_cog("Paginator")

    def cog_unload(self):
        self.clear_snipes.cancel()

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.author.bot and message.content:
            self.snipes[message.channel.id] = message, time.time()

    @tasks.loop(seconds=30)
    async def clear_snipes(self):
        for k, v in list(self.snipes.items()):
            if time.time() - v[1] > 5 * 60:
                try:
                    del self.snipes[k]
                except KeyError:
                    pass

    def _get_main_help_embed(self, lang: Translation, prefix: str) -> discord.Embed:
        embed = discord.Embed(color=self.bot.embed_color)
        embed.set_author(name=lang.help.n.title, icon_url=self.d.splash_logo)
        embed.description = lang.help.main.desc.format(self.d.support, self.d.topgg)

        embed.add_field(
            name=(self.d.emojis.emerald_spinn + lang.help.n.economy), value=f"`{prefix}ayuda econ`"
        )
        embed.add_field(
            name=(self.d.emojis.bounce + " " + lang.help.n.minecraft), value=f"`{prefix}ayuda mc`"
        )
        embed.add_field(
            name=(self.d.emojis.anichest + lang.help.n.utility), value=f"`{prefix}ayuda util`"
        )

        embed.add_field(
            name=(self.d.emojis.rainbow_shep + lang.help.n.fun), value=f"`{prefix}ayuda diversión`"
        )
        embed.add_field(
            name=(self.d.emojis.netherite_sword_ench + lang.help.n.admin),
            value=f"`{prefix}ayuda admin`",
        )
        embed.add_field(name="\uFEFF", value="\uFEFF")

        embed.set_footer(
            text=lang.useful.credits.foot.format(prefix)
            + "  |  "
            + lang.useful.rules.slashrules.format(prefix)
        )

        return embed

    @slash_command(name="ayuda")
    async def help_slash_command(self, inter: discord.Interaction):
        """Revisa el menú de ayuda de Chiru Aldeano"""

        language = self.bot.l[self.bot.language_cache.get(inter.guild_id, "es")]
        prefix = self.bot.prefix_cache.get(inter.guild_id, self.bot.k.default_prefix)
        await inter.response.send_message(embed=self._get_main_help_embed(language, prefix))

    @commands.group(name="ayuda", aliases=["help"], case_insensitive=True)
    async def help(self, ctx: Ctx):
        if ctx.invoked_subcommand is None:
            cmd = ctx.message.content.replace(f"{ctx.prefix}ayuda ", "")

            if cmd != "":
                cmd_true = self.bot.get_command(cmd.lower())

                if cmd_true is not None:
                    all_help = {
                        **ctx.l.help.econ,
                        **ctx.l.help.mc,
                        **ctx.l.help.util,
                        **ctx.l.help.fun,
                    }

                    help_text = all_help.get(str(cmd_true))

                    if help_text is None:
                        await ctx.reply_embed(ctx.l.help.main.nodoc)
                        return

                    embed = discord.Embed(color=self.bot.embed_color)

                    embed.set_author(name=ctx.l.help.n.cmd, icon_url=self.d.splash_logo)
                    embed.set_footer(text=ctx.l.useful.credits.foot.format(ctx.prefix))

                    embed.description = help_text.format(ctx.prefix)

                    if len(cmd_true.aliases) > 0:
                        embed.description += "\n\n" + ctx.l.help.main.aliases.format(
                            "`, `".join(cmd_true.aliases)
                        )

                    try:
                        await ctx.reply(embed=embed, mention_author=False)
                    except discord.errors.HTTPException as e:
                        if (
                            e.code == 50035
                        ):  # invalid form body, happens sometimes when the message to reply to can't be found?
                            await ctx.send(embed=embed, mention_author=False)
                        else:
                            raise

                    return

            embed = self._get_main_help_embed(ctx.l, ctx.prefix)

            await ctx.reply(embed=embed, mention_author=False)

    @help.command(name="economía", aliases=["econ", "economia"])
    async def help_economy(self, ctx: Ctx):
        embed = discord.Embed(color=self.bot.embed_color)

        embed.set_author(
            name=f"{ctx.l.help.n.title} [{ctx.l.help.n.economy}]", icon_url=self.d.splash_logo
        )
        embed.set_footer(text=ctx.l.useful.credits.foot.format(ctx.prefix))

        commands_formatted = "`, `".join(list(ctx.l.help.econ))
        embed.description = f"`{commands_formatted}`\n\n{ctx.l.help.main.howto.format(ctx.prefix)}"

        await ctx.reply(embed=embed, mention_author=False)

    @help.command(name="minecraft", aliases=["mc"])
    async def help_minecraft(self, ctx: Ctx):
        embed = discord.Embed(color=self.bot.embed_color)

        embed.set_author(
            name=f"{ctx.l.help.n.title} [{ctx.l.help.n.minecraft}]", icon_url=self.d.splash_logo
        )
        embed.set_footer(text=ctx.l.useful.credits.foot.format(ctx.prefix))

        commands_formatted = "`, `".join(list(ctx.l.help.mc))
        embed.description = f"`{commands_formatted}`\n\n{ctx.l.help.main.howto.format(ctx.prefix)}"

        await ctx.reply(embed=embed, mention_author=False)

    @help.command(name="utilidad", aliases=["util"])
    async def help_utility(self, ctx: Ctx):
        embed = discord.Embed(color=self.bot.embed_color)

        embed.set_author(
            name=f"{ctx.l.help.n.title} [{ctx.l.help.n.utility}]", icon_url=self.d.splash_logo
        )
        embed.set_footer(text=ctx.l.useful.credits.foot.format(ctx.prefix))

        commands_formatted = "`, `".join(list(ctx.l.help.util))
        embed.description = f"`{commands_formatted}`\n\n{ctx.l.help.main.howto.format(ctx.prefix)}"

        await ctx.reply(embed=embed, mention_author=False)

    @help.command(name="diversión", aliases=["diversion"])
    async def help_fun(self, ctx: Ctx):
        embed = discord.Embed(color=self.bot.embed_color)

        embed.set_author(
            name=f"{ctx.l.help.n.title} [{ctx.l.help.n.fun}]", icon_url=self.d.splash_logo
        )
        embed.set_footer(text=ctx.l.useful.credits.foot.format(ctx.prefix))

        commands_formatted = "`, `".join(list(ctx.l.help.fun))
        embed.description = f"`{commands_formatted}`\n\n{ctx.l.help.main.howto.format(ctx.prefix)}"

        await ctx.reply(embed=embed, mention_author=False)

    @help.command(name="administracion", aliases=["admin"])
    async def help_administrative(self, ctx: Ctx):
        embed = discord.Embed(color=self.bot.embed_color)

        embed.set_author(
            name=f"{ctx.l.help.n.title} [{ctx.l.help.n.admin}]", icon_url=self.d.splash_logo
        )
        embed.set_footer(text=ctx.l.useful.credits.foot.format(ctx.prefix))

        commands_formatted = "`, `".join(list(ctx.l.help.mod))
        embed.description = f"`{commands_formatted}`\n\n{ctx.l.help.main.howto.format(ctx.prefix)}"

        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="créditosoriginales", aliases=["creditosoriginales"])
    @commands.cooldown(1, 2, commands.BucketType.user)
    async def credits(self, ctx: Ctx):
        embed_template = discord.Embed(color=self.bot.embed_color)
        embed_template.set_author(name=ctx.l.useful.credits.credits, icon_url=self.d.splash_logo)

        fields: list[dict[str, str]] = []

        entry: tuple[int, str]
        for i, entry in enumerate(ctx.l.useful.credits.people.items()):
            user_id, contribution = entry

            # get user's current name
            user = self.bot.get_user(self.d.original_credit_users[user_id])
            if user is None:
                user = await self.bot.fetch_user(self.d.original_credit_users[user_id])

            fields.append({"name": f"**{user.display_name}**", "value": contribution})

            if i % 2 == 1:
                fields.append({"value": "\uFEFF", "name": "\uFEFF"})

        pages = [fields[i : i + 9] for i in range(0, len(fields), 9)]
        del fields

        def get_page(page: int) -> discord.Embed:
            embed = embed_template.copy()

            for field in pages[page]:
                embed.add_field(**field)

            embed.set_footer(text=f"{ctx.l.econ.page} {page+1}/{len(pages)}")

            return embed

        await self.paginator.paginate_embed(ctx, get_page, timeout=60, page_count=len(pages))

    @commands.command(name="créditoscomunidad", aliases=["creditoscomunidad"])
    @commands.cooldown(1, 2, commands.BucketType.user)
    async def credits(self, ctx: Ctx):
        embed_template = discord.Embed(color=self.bot.embed_color)
        embed_template.set_author(name=ctx.l.useful.credits.credits, icon_url=self.d.splash_logo)

        fields: list[dict[str, str]] = []

        entry: tuple[int, str]
        for i, entry in enumerate(ctx.l.useful.credits.people.items()):
            user_id, contribution = entry

            # get user's current name
            user = self.bot.get_user(self.d.fork_credit_users[user_id])
            if user is None:
                user = await self.bot.fetch_user(self.d.fork_credit_users[user_id])

            fields.append({"name": f"**{user.display_name}**", "value": contribution})

            if i % 2 == 1:
                fields.append({"value": "\uFEFF", "name": "\uFEFF"})

        pages = [fields[i : i + 9] for i in range(0, len(fields), 9)]
        del fields

        def get_page(page: int) -> discord.Embed:
            embed = embed_template.copy()

            for field in pages[page]:
                embed.add_field(**field)

            embed.set_footer(text=f"{ctx.l.econ.page} {page+1}/{len(pages)}")

            return embed

        await self.paginator.paginate_embed(ctx, get_page, timeout=60, page_count=len(pages))

    @commands.command(name="avatar", aliases=["av"])
    async def member_avatar(self, ctx: Ctx, member: discord.Member = None):
        user = member or ctx.author
        avatar_url = getattr(
            user.avatar,
            "url",
            "https://media.discordapp.net/attachments/643648150778675202/947881629047722064/gGWDJSghKgd8QAAAABJRU5ErkJggg.png",
        )

        embed = discord.Embed(
            color=self.bot.embed_color, description=ctx.l.fun.dl_img.format(avatar_url)
        )
        embed.set_image(url=avatar_url)

        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(
        name="ping"
    )
    async def ping_pong(self, ctx: Ctx):
        content = ctx.message.content.lower()

        if "ping" in content:
            pp = "Pong"
            return

        await ctx.reply_embed(
            f"{self.d.emojis.aniheart} {pp}! \uFEFF `{round(self.bot.latency*1000, 2)} ms`"
        )

    @commands.command(
        name="enlaces",
        aliases=["links"],
    )
    async def useful_links(self, ctx: Ctx):
        embed = discord.Embed(color=self.bot.embed_color)
        embed.set_author(name="Enlaces de Chiru Aldeano", icon_url=self.d.splash_logo)

        embed.description = (
            f"**[{ctx.l.useful.links.support}]({self.d.support})\n"
            f"\n[{ctx.l.useful.links.source}]({self.d.github})\n"
            f"\n[{ctx.l.useful.links.privacy}]({self.d.privacy_policy})**"
        )

        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="estadísticas", aliases=["estadisticas", "stats"])
    async def stats(self, ctx: Ctx):
        with suppress(Exception):
            await ctx.defer()

        uptime_seconds = (arrow.utcnow() - self.bot.start_time).total_seconds()
        uptime = (
            arrow.utcnow()
            .shift(seconds=uptime_seconds)
            .humanize(locale=ctx.l.lang, only_distance=True)
        )

        clusters_bot_stats: list[list[Any]]
        clusters_system_stats: list[SystemStats]
        karen_system_stats: SystemStats
        clusters_bot_stats, clusters_system_stats, karen_system_stats = await asyncio.gather(
            self.karen.fetch_clusters_bot_stats(),
            self.karen.fetch_clusters_system_stats(),
            self.karen.fetch_karen_system_stats(),
        )

        cluster_ping = await self.karen.fetch_clusters_ping()

        (
            guild_count,
            user_count,
            message_count,
            command_count,
            latency_all,
            dm_count,
            session_votes,
        ) = map(sum, zip(*clusters_bot_stats))

        # total_mem = psutil.virtual_memory().total

        embed = discord.Embed(color=self.bot.embed_color)

        embed.set_author(name=ctx.l.useful.stats.stats, icon_url=self.d.splash_logo)
        embed.set_footer(text=ctx.l.useful.credits.foot.format(ctx.prefix))

        general_col_1 = (
            f"{ctx.l.useful.stats.servers}: `{guild_count}`\n"
            f"{ctx.l.useful.stats.dms}: `{dm_count}`\n"
            f"{ctx.l.useful.stats.users}: `{user_count}`\n"
            f"{ctx.l.useful.stats.msgs}: `{message_count}`\n"
            f"{ctx.l.useful.stats.shards}: `{self.bot.shard_count}`\n"
            f"{ctx.l.useful.stats.uptime}: `{uptime}`\n"
        )
        general_col_2 = (
            f"{ctx.l.useful.stats.cmds}: `{command_count}` `({round((command_count / (message_count + .0000001)) * 100, 2)}%)`\n"
            f"{ctx.l.useful.stats.cmds_sec}: `{round(command_count / uptime_seconds, 2)}`\n"
            f"Discord {ctx.l.useful.stats.ping}: `{round((latency_all/len(clusters_bot_stats)) * 1000, 2)} ms`\n"
            f"Cluster {ctx.l.useful.stats.ping}: `{round(cluster_ping * 1000, 2)} ms`\n"
        )

        embed.add_field(name="Chiru Aldeano", value=general_col_1)
        embed.add_field(name="\uFEFF", value="\uFEFF")
        embed.add_field(name="\uFEFF", value=general_col_2)

        for ss in [karen_system_stats, *clusters_system_stats]:
            mem_gb = ss.memory_usage_bytes / 1000000000
            mem_percent = ss.memory_usage_bytes / ss.memory_max_bytes * 100

            embed.add_field(
                name=ss.identifier,
                value=(
                    f"{ctx.l.useful.stats.mem}: `{round(mem_gb, 2)} GB` `({round(mem_percent, 2)}%)`\n"
                    f"{ctx.l.useful.stats.cpu}: `{round(ss.cpu_usage_percent * 100, 2)}%`\n"
                ),
            )
            embed.add_field(name="\uFEFF", value="\uFEFF")
            embed.add_field(
                name="\uFEFF",
                value=(
                    f"{ctx.l.useful.stats.threads}: `{ss.threads}`\n"
                    f"{ctx.l.useful.stats.tasks}: `{ss.asyncio_tasks}`\n"
                ),
            )

        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="infoservidor")
    @commands.guild_only()
    async def server_info(self, ctx: Ctx, *, guild: discord.Guild = None):
        with suppress(Exception):
            await ctx.defer()

        if guild is None:
            guild = ctx.guild

        db_guild = await self.db.fetch_guild(guild.id)

        age = arrow.get(discord.utils.snowflake_time(guild.id))
        display_age = (
            age.format("MMM D, YYYY", locale=ctx.l.lang) + ", " + age.humanize(locale=ctx.l.lang)
        )

        embed = discord.Embed(color=self.bot.embed_color)
        embed.set_author(
            name=f"{guild.name} {ctx.l.useful.ginf.info}",
            icon_url=getattr(guild.icon, "url", None),
        )

        embed.description = f"{ctx.l.useful.ginf.age}: `{display_age}`\n{ctx.l.useful.ginf.owner}: {guild.owner.mention}"

        general = (
            f"{ctx.l.useful.ginf.members}: `{len([m for m in guild.members if not m.bot])}`\n"
            f"{ctx.l.useful.ginf.channels}: `{len(guild.text_channels) + len(guild.voice_channels)}`\n "
            f"{ctx.l.useful.ginf.roles}: `{len(guild.roles)}`\n"
            f"{ctx.l.useful.ginf.emojis}: `{len(guild.emojis)}`\n"
        )

        ban_count_display = f"{ctx.l.useful.ginf.bans}: {self.d.emojis.aniloading}\n"

        villager = (
            f"{ctx.l.useful.ginf.lang}: `{ctx.l.name}`\n"
            f"{ctx.l.useful.ginf.diff}: `{db_guild.difficulty}`\n"
            f"{ctx.l.useful.ginf.cmd_prefix}: `{ctx.prefix}`\n"
            f"{ctx.l.useful.ginf.joined_at}: `{arrow.get(ctx.me.joined_at).humanize(locale=ctx.l.lang)}`\n"
        )

        embed.add_field(name="General :gear:", value=(general + ban_count_display), inline=True)
        embed.add_field(name="Chiru Aldeano " + self.d.emojis.emerald, value=villager, inline=True)

        role_mentions = [r.mention for r in guild.roles if r.id != guild.id][::-1]
        role_mentions_cut = list(shorten_chunks(role_mentions, 1000))
        role_mentions_diff = len(role_mentions) - len(role_mentions_cut)

        embed.add_field(
            name="Roles",
            value=" ".join(role_mentions_cut)
            + (
                (" " + ctx.l.useful.ginf.roles_and_n_others.format(n=role_mentions_diff))
                if role_mentions_diff
                else ""
            ),
            inline=False,
        )

        embed.set_thumbnail(url=getattr(guild.icon, "url", None))
        embed.set_footer(text=ctx.l.useful.credits.foot.format(ctx.prefix))

        msg = await ctx.reply(embed=embed, mention_author=False)

        async with SuppressCtxManager(ctx.defer()):
            aprox_ban_count = await fetch_aprox_ban_count(ctx.guild, seconds=3)
            embed.set_field_at(
                0,
                name=embed.fields[0].name,
                value=(general + f"{ctx.l.useful.ginf.bans}: `{aprox_ban_count}`\n"),
            )

        await msg.edit(embed=embed)

    @commands.command(name="reglasbot", aliases=["reglas"])
    async def rules(self, ctx: Ctx):
        embed = discord.Embed(color=self.bot.embed_color, description=ctx.l.useful.rules.penalty)

        embed.set_author(name=ctx.l.useful.rules.rules, icon_url=self.d.splash_logo)
        embed.set_footer(text=ctx.l.useful.credits.foot.format(ctx.prefix))

        embed.add_field(name="\uFEFF", value=ctx.l.useful.rules.rule_1.format(self.d.support))
        embed.add_field(name="\uFEFF", value="\uFEFF")
        embed.add_field(name="\uFEFF", value=ctx.l.useful.rules.rule_2)

        embed.add_field(name="\uFEFF", value=ctx.l.useful.rules.rule_3)
        embed.add_field(name="\uFEFF", value="\uFEFF")
        embed.add_field(name="\uFEFF", value=ctx.l.useful.rules.rule_4)

        await ctx.reply(embed=embed, mention_author=False)

async def setup(bot: VillagerBotCluster) -> None:
    await bot.add_cog(Useful(bot))
