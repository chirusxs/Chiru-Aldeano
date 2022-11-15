import asyncio
import random
import typing
from contextlib import suppress
from urllib.parse import quote as urlquote

import classyjson as cj
import discord
from discord.ext import commands

from bot.cogs.core.database import Database
from bot.models.translation import Fun_Trivia_Question
from bot.utils.ctx import Ctx
from bot.utils.misc import SuppressCtxManager, clean_text, shorten_text
from bot.villager_bot import VillagerBotCluster


class Fun(commands.Cog):
    def __init__(self, bot: VillagerBotCluster):
        self.bot = bot

        self.d = bot.d
        self.k = bot.k

        self.aiohttp = bot.aiohttp
        self.karen = bot.karen

    @property
    def db(self) -> Database:
        return self.bot.get_cog("Database")

    @staticmethod
    def lang_convert(msg, lang):
        keys = list(lang)

        for key in keys:
            msg = msg.replace(key, lang.get(key))

            with suppress(Exception):
                msg = msg.replace(key.upper(), lang.get(key).upper())

        return msg

    async def reddit_post_logic(
        self, ctx: Ctx, post_type: str, *, show_details: bool = True
    ) -> None:
        do_nsfw = False

        if isinstance(ctx.channel, discord.TextChannel):
            do_nsfw = ctx.channel.is_nsfw()

        post = {"nsfw": True, "spoiler": True}

        async with SuppressCtxManager(ctx.typing()):
            while post["spoiler"] or (not do_nsfw and post["nsfw"]):
                resp = await self.aiohttp.get(
                    f"https://api.iapetus11.me/reddit/{post_type}",
                    # headers={"Authorization": self.k.villager_api},
                    params={"requesterId": ctx.channel.id},
                )

                post = cj.classify(await resp.json())

        embed = discord.Embed(color=self.bot.embed_color)

        if show_details:
            embed.title = shorten_text(post["title"], 256)
            embed.url = post["permalink"]
            embed.set_footer(
                text=f"{post['upvotes']}  |  u/{post['author']}", icon_url=self.d.upvote_emoji_image
            )

        embed.set_image(url=post["image"])

        await ctx.send(embed=embed)

    @commands.command(name="cursed", aliases=["cursedmc"])
    @commands.cooldown(1, 1.5, commands.BucketType.user)
    async def cursed_mc(self, ctx: Ctx):
        if random.choice((True, False)):
            await self.reddit_post_logic(ctx, "cursedMinecraft")
        else:
            embed = discord.Embed(color=self.bot.embed_color)
            embed.set_image(
                url=f"https://iapetus11.me/images/cursed_minecraft/{random.choice(self.d.cursed_images)}"
            )

            await ctx.send(embed=embed)

    @commands.command(name="traductoraldeano")
    async def villager_speak(self, ctx: Ctx, *, text: str):
        """Turns the given text into Minecraft villager sounds as text"""

        translated = self.lang_convert(clean_text(ctx.message, text), self.d.fun_langs.villager)
        await ctx.send(shorten_text(translated))

    @commands.command(name="encantar")
    async def enchant_lang(self, ctx: Ctx, *, text: str):
        """Turns regular text into the Minecraft enchantment table language"""

        translated = self.lang_convert(
            clean_text(ctx.message, text).lower(), self.d.fun_langs.enchant
        )
        await ctx.send(shorten_text(translated))

    @commands.command(name="desencantar")
    async def unenchant_lang(self, ctx: Ctx, *, text: str):
        """Turns the Minecraft enchantment table language back into regular text"""

        translated = self.lang_convert(clean_text(ctx.message, text), self.d.fun_langs.unenchant)
        await ctx.send(shorten_text(translated))

        translated = self.lang_convert(clean_text(ctx.message, text), self.d.fun_langs.vaporwave)
        await ctx.send(shorten_text(translated))

    @commands.command(name="owo", aliases=["uwu"])
    async def owofy_text(self, ctx: Ctx, *, text):
        """Make any text more cringe"""

        text = text.lower().replace("l", "w").replace("r", "w")

        if len(text) > 1950:
            await ctx.send_embed(ctx.l.fun.too_long)
        else:
            await ctx.send(f"{text} {random.choice(self.d.owos)}")

    @commands.command(name="lanzarmoneda", aliases=["flipcoin"])
    async def coin_flip(self, ctx: Ctx):
        await ctx.send_embed(random.choice(("heads", "tails")))

    # Trivia stuff

    def calculate_trivia_reward(self, question_difficulty: int) -> int:
        return int((random.random() + 0.25) * (question_difficulty + 0.25) * 9) + 1

    async def trivia_multiple_choice(
        self, ctx: Ctx, question: Fun_Trivia_Question, do_reward: bool
    ) -> None:
        correct_choice = question.a[0]

        choices = question.a.copy()
        random.shuffle(choices)

        embed = discord.Embed(
            color=self.bot.embed_color,
            title=ctx.l.fun.trivia.title.format(
                self.d.emojis.bounce, ctx.l.fun.trivia.difficulty[question.d], ":question:"
            ),
        )

        embed.description = "*{}*".format(
            "\n".join(
                map(
                    " ".join,
                    [question.q.split()[i : i + 7] for i in range(0, len(question.q.split()), 7)],
                )
            )
        )
        embed.set_footer(text="\uFEFF\n" + ctx.l.fun.trivia.time_to_answer)

        for i, c in enumerate(choices):
            c_column = "\n".join(
                map(" ".join, [c.split()[i : i + 3] for i in range(0, len(c.split()), 3)])
            )
            embed.add_field(name="\uFEFF", value=f"**{i+1}.** {c_column}")

            if i % 2 == 0:
                embed.add_field(name="\uFEFF", value="\uFEFF")

        msg = await ctx.reply(embed=embed, mention_author=False)

        for i in range(len(choices)):
            await msg.add_reaction(self.d.emojis.numbers[i + 1])

        def reaction_check(react, r_user):
            return (
                r_user == ctx.author
                and ctx.channel == react.message.channel
                and msg == react.message
                and react.emoji in self.d.emojis.numbers[1 : len(choices) + 1]
            )

        try:
            react, r_user = await self.bot.wait_for(
                "reaction_add", check=reaction_check, timeout=15
            )
        except asyncio.TimeoutError:
            embed = discord.Embed(
                color=self.bot.embed_color,
                title=ctx.l.fun.trivia.title_basic.format(self.d.emojis.bounce, ":question:"),
                description=ctx.l.fun.trivia.timeout,
            )
            await msg.edit(embed=embed)
            return
        finally:
            with suppress(discord.errors.HTTPException):
                await msg.clear_reactions()

        embed = discord.Embed(
            color=self.bot.embed_color,
            title=ctx.l.fun.trivia.title_basic.format(self.d.emojis.bounce, ":question:"),
        )

        if choices[self.d.emojis.numbers.index(react.emoji) - 1] == correct_choice:
            if do_reward:
                emeralds_won = self.calculate_trivia_reward(question.d)
                await self.db.balance_add(ctx.author.id, emeralds_won)
                correct = random.choice(ctx.l.fun.trivia.correct).format(
                    emeralds_won, self.d.emojis.emerald
                )
            else:
                correct = random.choice(ctx.l.fun.trivia.correct).split("\n")[0]

            embed.description = correct
        else:
            embed.description = random.choice(ctx.l.fun.trivia.incorrect)

        await msg.edit(embed=embed)

    async def trivia_true_or_false(self, ctx: Ctx, question: Fun_Trivia_Question, do_reward: bool):
        correct_choice = question.a[0]

        embed = discord.Embed(
            color=self.bot.embed_color,
            title=ctx.l.fun.trivia.title.format(
                self.d.emojis.bounce, ctx.l.fun.trivia.difficulty[question.d], ":question:"
            ),
        )

        embed.description = "*{}*".format(
            "\n".join(
                map(
                    " ".join,
                    [question.q.split()[i : i + 7] for i in range(0, len(question.q.split()), 7)],
                )
            )
        )
        embed.set_footer(text="\uFEFF\n" + ctx.l.fun.trivia.time_to_answer)

        msg = await ctx.reply(embed=embed, mention_author=False)

        await msg.add_reaction(self.d.emojis.yes)
        await msg.add_reaction(self.d.emojis.no)

        def reaction_check(react, r_user):
            return (
                r_user == ctx.author
                and ctx.channel == react.message.channel
                and msg == react.message
                and str(react.emoji) in [self.d.emojis.yes, self.d.emojis.no]
            )

        try:
            react, _ = await self.bot.wait_for("reaction_add", check=reaction_check, timeout=15)
        except asyncio.TimeoutError:
            embed = discord.Embed(
                color=self.bot.embed_color,
                title=ctx.l.fun.trivia.title_basic.format(self.d.emojis.bounce, ":question:"),
                description=ctx.l.fun.trivia.timeout,
            )
            await msg.edit(embed=embed)
            return
        finally:
            with suppress(discord.errors.HTTPException):
                await msg.clear_reactions()

        embed = discord.Embed(
            color=self.bot.embed_color,
            title=ctx.l.fun.trivia.title_basic.format(self.d.emojis.bounce, ":question:"),
        )

        if (correct_choice == "true" and str(react.emoji) == self.d.emojis.yes) or (
            correct_choice == "false" and str(react.emoji) == self.d.emojis.no
        ):
            if do_reward:
                emeralds_won = self.calculate_trivia_reward(question.d)
                await self.db.balance_add(ctx.author.id, emeralds_won)
                correct = random.choice(ctx.l.fun.trivia.correct).format(
                    emeralds_won, self.d.emojis.emerald
                )
            else:
                correct = random.choice(ctx.l.fun.trivia.correct).split("\n")[0]

            embed.description = correct
        else:
            embed.description = random.choice(ctx.l.fun.trivia.incorrect)

        await msg.edit(embed=embed)

    @commands.command(name="trivia", aliases=["mctrivia"])
    @commands.guild_only()
    @commands.max_concurrency(1, per=commands.BucketType.user)
    async def minecraft_trivia(self, ctx: Ctx):
        trivia_commands_ran = await self.karen.trivia_command(ctx.author.id)
        do_reward = trivia_commands_ran <= 7

        question = random.choice(ctx.l.fun.trivia.questions)

        if question.tf:
            await self.trivia_true_or_false(ctx, question, do_reward)
        else:
            await self.trivia_multiple_choice(ctx, question, do_reward)

    @commands.command(name="gayrate", aliases=["gaypercent"])
    async def gay_rate(self, ctx: Ctx, *, thing: typing.Union[discord.Member, str] = None):
        if thing is None:
            thing = ctx.author.mention
        elif isinstance(thing, discord.Member):
            thing = thing.mention

        await ctx.reply_embed(
            ctx.l.fun.gayrate.format("\uFEFF :rainbow_flag: \uFEFF", shorten_text(thing, 256))
        )


async def setup(bot: VillagerBotCluster) -> None:
    await bot.add_cog(Fun(bot))
