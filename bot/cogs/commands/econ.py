import asyncio
import datetime
import functools
import math
import random
from collections import defaultdict
from typing import Any

import arrow
import discord
import numpy.random
from discord.ext import commands

from common.models.data import ShopItem
from common.models.db.item import Item

from bot.cogs.core.badges import Badges
from bot.cogs.core.database import Database
from bot.cogs.core.paginator import Paginator
from bot.utils.ctx import Ctx
from bot.utils.misc import (
    SuppressCtxManager,
    calc_total_wealth,
    craft_lbs,
    emojify_crop,
    emojify_item,
    format_required,
    item_case,
    make_health_bar,
)
from bot.villager_bot import VillagerBotCluster


class Econ(commands.Cog):
    def __init__(self, bot: VillagerBotCluster):
        self.bot = bot

        self.d = bot.d
        self.karen = bot.karen

        self._link_max_concurrency()

    @property
    def db(self) -> Database:
        return self.bot.get_cog("Database")

    @property
    def badges(self) -> Badges:
        return self.bot.get_cog("Badges")

    @property
    def paginator(self) -> Paginator:
        return self.bot.get_cog("Paginator")

    @functools.lru_cache(maxsize=None)  # calculate chances for a specific pickaxe to find emeralds
    def calc_yield_chance_list(self, pickaxe: str):
        yield_ = self.d.mining.yields_pickaxes[pickaxe]  # [xTrue, xFalse]
        return [True] * yield_[0] + [False] * yield_[1]

    def _link_max_concurrency(self):
        # This links the max concurrency of the with, dep, sell, give, etc.. cmds
        for command in (
            self.vault_deposit,
            self.vault_withdraw,
            self.buy,
            self.sell,
            self.give,
            self.gamble,
            self.search,
            self.mine,
            self.pillage,
        ):
            command._max_concurrency = self.max_concurrency_dummy._max_concurrency

    async def math_problem(self, ctx: Ctx, addition=1):
        # simultaneously updates the value in Karen and retrieves the current value
        mine_commands = await self.karen.mine_command(ctx.author.id, addition)

        if mine_commands >= 100:
            x, y = random.randint(0, 15), random.randint(0, 10)
            prob = f"{y*random.choice([chr(u) for u in (65279, 8203, 8204, 8205)])}{x}{x*random.choice([chr(u) for u in (65279, 8203, 8204, 8205)])}+{y}"
            prob = (prob, str(x + y))

            m = await ctx.reply(
                embed=discord.Embed(
                    color=self.bot.embed_color,
                    description=ctx.l.econ.math_problem.problem.format("process.exit(69)"),
                ),
                mention_author=False,
            )
            asyncio.create_task(
                m.edit(
                    embed=discord.Embed(
                        color=self.bot.embed_color,
                        description=ctx.l.econ.math_problem.problem.format(prob[0]),
                    )
                )
            )

            def author_check(m):
                return m.channel == ctx.channel and m.author == ctx.author

            try:
                m = await self.bot.wait_for("message", check=author_check, timeout=10)
            except asyncio.TimeoutError:
                await ctx.reply_embed(ctx.l.econ.math_problem.timeout)
                return False

            if m.content != prob[1]:
                await self.bot.reply_embed(
                    m, ctx.l.econ.math_problem.incorrect.format(self.d.emojis.no)
                )
                return False

            await self.karen.mine_commands_reset(ctx.author.id)
            await self.bot.reply_embed(m, ctx.l.econ.math_problem.correct.format(self.d.emojis.yes))

        return True

    @commands.command(name="max_concurrency_dummy")
    @commands.max_concurrency(1, commands.BucketType.user)
    async def max_concurrency_dummy(self, ctx: Ctx):
        pass

    @commands.command(name="perfil", aliases=["pp"])
    async def profile(self, ctx: Ctx, *, user: discord.User = None):
        if user is None:
            user = ctx.author

        if user.bot:
            if user.id == self.bot.user.id:
                await ctx.reply_embed(ctx.l.econ.pp.bot_1)
            else:
                await ctx.reply_embed(ctx.l.econ.pp.bot_2)

            return

        db_user = await self.db.fetch_user(user.id)
        u_items = await self.db.fetch_items(user.id)

        total_wealth = calc_total_wealth(db_user, u_items)
        health_bar = make_health_bar(
            db_user.health,
            20,
            self.d.emojis.heart_full,
            self.d.emojis.heart_half,
            self.d.emojis.heart_empty,
        )

        mooderalds = getattr(await self.db.fetch_item(user.id, "Antimeralda"), "amount", 0)

        user_badges_str = self.badges.emojify_badges(await self.badges.fetch_user_badges(user.id))

        active_fx = await self.karen.fetch_active_fx(user.id)

        if db_user.shield_pearl and (
            arrow.get(db_user.shield_pearl).shift(months=1) > arrow.utcnow()
        ):
            active_fx.add("escudo perla")

        embed = discord.Embed(color=self.bot.embed_color, description=f"{health_bar}")
        embed.set_author(name=user.display_name, icon_url=getattr(user.avatar, "url", None))

        embed.add_field(
            name=ctx.l.econ.pp.total_wealth, value=f"{total_wealth}{self.d.emojis.emerald}"
        )
        embed.add_field(name="\uFEFF", value="\uFEFF")
        embed.add_field(
            name=ctx.l.econ.pp.mooderalds, value=f"{mooderalds}{self.d.emojis.autistic_emerald}"
        )

        embed.add_field(name=ctx.l.econ.pp.pick, value=(await self.db.fetch_pickaxe(user.id)))
        embed.add_field(name="\uFEFF", value="\uFEFF")
        embed.add_field(name=ctx.l.econ.pp.sword, value=(await self.db.fetch_sword(user.id)))

        if active_fx:
            embed.add_field(
                name=ctx.l.econ.pp.fx,
                value=f"`{'`, `'.join(map(item_case, active_fx))}`",
                inline=False,
            )

        if user_badges_str:
            embed.add_field(name="\uFEFF", value=user_badges_str, inline=False)

        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="saldo", aliases=["bal"])
    async def balance(self, ctx: Ctx, *, user: discord.User = None):
        """Shows the balance of a user or the message sender"""

        if user is None:
            user = ctx.author

        if user.bot:
            if user.id == self.bot.user.id:
                await ctx.reply_embed(ctx.l.econ.bal.bot_1)
            else:
                await ctx.reply_embed(ctx.l.econ.bal.bot_2)

            return

        db_user = await self.db.fetch_user(user.id)
        u_items = await self.db.fetch_items(user.id)

        total_wealth = calc_total_wealth(db_user, u_items)

        mooderalds = getattr(await self.db.fetch_item(user.id, "Antimeralda"), "amount", 0)

        embed = discord.Embed(color=self.bot.embed_color)
        embed.set_author(
            name=ctx.l.econ.bal.s_emeralds.format(user.display_name),
            icon_url=getattr(user.avatar, "url", None),
        )

        embed.description = (
            ctx.l.econ.bal.total_wealth.format(total_wealth, self.d.emojis.emerald)
            + "\n"
            + ctx.l.econ.bal.autistic_emeralds.format(mooderalds, self.d.emojis.autistic_emerald)
        )

        embed.add_field(
            name=ctx.l.econ.bal.pocket, value=f"{db_user.emeralds}{self.d.emojis.emerald}"
        )
        embed.add_field(
            name=ctx.l.econ.bal.vault,
            value=f"{db_user.vault_balance}/{db_user.vault_max} {self.d.emojis.emerald_block}",
        )

        await ctx.reply(embed=embed, mention_author=False)

    async def inventory_logic(
        self, ctx: Ctx, user, items: list[Item], cat: str, items_per_page: int = 8
    ):
        """Logic behind generation of inventory embeds + pagination"""

        embed_template = discord.Embed(color=self.bot.embed_color)
        embed_template.set_author(
            name=ctx.l.econ.inv.s_inventory.format(user.display_name, cat),
            icon_url=getattr(user.avatar, "url", None),
        )

        # handle if there are no passed items
        if len(items) == 0:
            embed_template.description = ctx.l.econ.inv.empty
            await ctx.send(embed=embed_template)
            return

        fish_prices = {fish.name: fish.current for fish in self.d.fishing.fish.values()}
        # iterate through passed items, try to set fish values properly if they exist
        for item in items:
            try:
                item.sell_price = fish_prices[item.name]
            except KeyError:
                pass

        items = sorted(
            items, key=(lambda item: item.sell_price), reverse=True
        )  # sort items by sell price
        items_chunks = [
            items[i : i + items_per_page] for i in range(0, len(items), items_per_page)
        ]  # split items into chunks
        del items

        def get_page(page: int) -> discord.Embed:
            embed = embed_template.copy()

            embed.description = "\n".join(
                [
                    f"{emojify_item(self.d, item.name)} `{item.amount}x` **{item.name}** ({item.sell_price}{self.d.emojis.emerald})"
                    for item in items_chunks[page]
                ]
            )

            embed.set_footer(text=f"{ctx.l.econ.page} {page+1}/{len(items_chunks)}")

            return embed

        await self.paginator.paginate_embed(ctx, get_page, timeout=60, page_count=len(items_chunks))

    async def inventory_boiler(self, ctx: Ctx, user: discord.User = None):
        if ctx.invoked_subcommand is not None:
            return False, None

        if user is None:
            user = ctx.author

        if user.bot:
            if user.id == self.bot.user.id:
                await ctx.reply_embed(ctx.l.econ.inv.bot_1)
            else:
                await ctx.reply_embed(ctx.l.econ.inv.bot_2)

            return False, user

        return True, user

    @commands.group(name="inventario", aliases=["inv"], case_insensitive=True)
    @commands.max_concurrency(3, per=commands.BucketType.user, wait=False)
    @commands.guild_only()
    @commands.cooldown(2, 2, commands.BucketType.user)
    async def inventory(self, ctx: Ctx):
        if ctx.invoked_subcommand is not None:
            return

        split = ctx.message.content.split()

        if len(split) <= 1:
            user = ctx.author
        else:
            try:
                user = await commands.UserConverter().convert(ctx, " ".join(split[1:]))
            except BaseException:
                raise commands.BadArgument

        if user.bot:
            if user.id == self.bot.user.id:
                await ctx.reply_embed(ctx.l.econ.inv.bot_1)
            else:
                await ctx.reply_embed(ctx.l.econ.inv.bot_2)

            return

        items = await self.db.fetch_items(user.id)

        await self.inventory_logic(ctx, user, items, ctx.l.econ.inv.cats.all, 16)

    @inventory.command(name="herramientas", aliases=["herramienta"])
    async def inventory_tools(self, ctx: Ctx, user: discord.User = None):
        valid, user = await self.inventory_boiler(ctx, user)

        if not valid:
            return

        items = [e for e in await self.db.fetch_items(user.id) if e.name in self.d.cats["tools"]]

        await self.inventory_logic(ctx, user, items, ctx.l.econ.inv.cats.tools)

    @inventory.command(name="magia")
    async def inventory_magic(self, ctx: Ctx, user: discord.User = None):
        valid, user = await self.inventory_boiler(ctx, user)

        if not valid:
            return

        items = [e for e in await self.db.fetch_items(user.id) if e.name in self.d.cats["magic"]]

        await self.inventory_logic(ctx, user, items, ctx.l.econ.inv.cats.magic)

    @inventory.command(name="otros")
    async def inventory_misc(self, ctx: Ctx, user: discord.User = None):
        valid, user = await self.inventory_boiler(ctx, user)

        if not valid:
            return

        combined_cats = self.d.cats["tools"] + self.d.cats["magic"] + self.d.cats["fish"]
        items = [e for e in await self.db.fetch_items(user.id) if e.name not in combined_cats]

        await self.inventory_logic(
            ctx, user, items, ctx.l.econ.inv.cats.misc, (16 if len(items) > 24 else 8)
        )

    @inventory.command(name="pesca")
    async def inventory_fish(self, ctx: Ctx, user: discord.User = None):
        valid, user = await self.inventory_boiler(ctx, user)

        if not valid:
            return

        items = [e for e in await self.db.fetch_items(user.id) if e.name in self.d.cats["fish"]]

        await self.inventory_logic(ctx, user, items, ctx.l.econ.inv.cats.fish)

    @inventory.command(name="agricultura")
    async def inventory_farming(self, ctx: Ctx, user: discord.User = None):
        valid, user = await self.inventory_boiler(ctx, user)

        if not valid:
            return

        items = [e for e in await self.db.fetch_items(user.id) if e.name in self.d.cats["farming"]]

        await self.inventory_logic(ctx, user, items, ctx.l.econ.inv.cats.farming)

    @commands.command(name="depositar", aliases=["dep"])
    # @commands.cooldown(1, 2, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.user)
    async def vault_deposit(self, ctx: Ctx, emerald_blocks: str):
        """Deposits the given amount of emerald blocks into the vault"""

        db_user = await self.db.fetch_user(ctx.author.id)

        if db_user.emeralds < 9:
            await ctx.reply_embed(ctx.l.econ.dep.poor_loser)
            return

        if emerald_blocks.lower() in ("todo", "max", "máx"):
            amount = db_user.vault_max - db_user.vault_balance

            if amount * 9 > db_user.emeralds:
                amount = math.floor(db_user.emeralds / 9)
        else:
            try:
                amount = int(emerald_blocks)
            except ValueError:
                await ctx.reply_embed(ctx.l.econ.use_a_number_stupid)
                return

        if amount * 9 > db_user.emeralds:
            await ctx.reply_embed(ctx.l.econ.dep.stupid_3)
            return

        if amount < 1:
            if emerald_blocks.lower() in ("todo", "max"):
                await ctx.reply_embed(ctx.l.econ.dep.stupid_2)
            else:
                await ctx.reply_embed(ctx.l.econ.dep.stupid_1)

            return

        if amount > db_user.vault_max - db_user.vault_balance:
            await ctx.reply_embed(ctx.l.econ.dep.stupid_2)
            return

        await self.db.balance_sub(ctx.author.id, amount * 9)
        await self.db.set_vault(ctx.author.id, db_user.vault_balance + amount, db_user.vault_max)

        await ctx.reply_embed(
            ctx.l.econ.dep.deposited.format(
                amount, self.d.emojis.emerald_block, amount * 9, self.d.emojis.emerald
            )
        )

    @commands.command(name="retirar", aliases=["ret"])
    @commands.cooldown(1, 2, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.user)
    async def vault_withdraw(self, ctx: Ctx, emerald_blocks: str):
        """Withdraws a certain amount of emerald blocks from the vault"""

        db_user = await self.db.fetch_user(ctx.author.id)

        if db_user.vault_balance < 1:
            await ctx.reply_embed(ctx.l.econ.withd.poor_loser)
            return

        if emerald_blocks.lower() in ("todo", "max", "máx"):
            amount = db_user.vault_balance
        else:
            try:
                amount = int(emerald_blocks)
            except ValueError:
                await ctx.reply_embed(ctx.l.econ.use_a_number_stupid)
                return

        if amount < 1:
            await ctx.reply_embed(ctx.l.econ.withd.stupid_1)
            return

        if amount > db_user.vault_balance:
            await ctx.reply_embed(ctx.l.econ.withd.stupid_2)
            return

        await self.db.balance_add(ctx.author.id, amount * 9)
        await self.db.set_vault(ctx.author.id, db_user.vault_balance - amount, db_user.vault_max)

        await ctx.reply_embed(
            ctx.l.econ.withd.withdrew.format(
                amount, self.d.emojis.emerald_block, amount * 9, self.d.emojis.emerald
            )
        )

    @commands.group(name="tienda", case_insensitive=True)
    @commands.guild_only()
    @commands.cooldown(2, 10, commands.BucketType.user)
    async def shop(self, ctx: Ctx):
        """Shows the available options in the Villager Shop"""

        if ctx.invoked_subcommand is None:
            embed = discord.Embed(color=self.bot.embed_color)
            embed.set_author(name=ctx.l.econ.shop.villager_shop, icon_url=self.d.splash_logo)

            # row 1
            embed.add_field(
                name=f"__**{ctx.l.econ.shop.tools.format(self.d.emojis.netherite_pickaxe_ench)}**__",
                value=f"`{ctx.prefix}tienda herramientas`",
            )
            embed.add_field(name="\uFEFF", value="\uFEFF")
            embed.add_field(
                name=f"__**{ctx.l.econ.shop.magic.format(self.d.emojis.enchanted_book)}**__",
                value=f"`{ctx.prefix}tienda magia`",
            )

            # row 2
            embed.add_field(
                name=f"__**{ctx.l.econ.shop.other.format(self.d.emojis.totem)}**__",
                value=f"`{ctx.prefix}tienda otros`",
            )
            embed.add_field(name="\uFEFF", value="\uFEFF")
            embed.add_field(
                name=f"__**{ctx.l.econ.shop.farming.format(self.d.emojis.farming.normal['wheat'])}**__",
                value=f"`{ctx.prefix}tienda agricultura`",
            )

            embed.set_footer(text=ctx.l.econ.shop.embed_footer.format(ctx.prefix))

            await ctx.reply(embed=embed, mention_author=False)

    async def shop_logic(self, ctx: Ctx, category: str, header: str) -> None:
        """The logic behind the shop pages"""

        items = list[ShopItem]()

        # only get items that are in the specified category
        item: ShopItem
        for item in self.d.shop_items.values():
            if category in item.cat:
                items.append(item)

        items = sorted(items, key=(lambda item: item.buy_price))  # sort items by their buy price
        item_pages = [items[i : i + 4] for i in range(0, len(items), 4)]  # put items in groups of 4
        del items

        def get_page(page: int) -> discord.Embed:
            embed = discord.Embed(color=self.bot.embed_color)
            embed.set_author(name=header, icon_url=self.d.splash_logo)

            for item in item_pages[page]:
                embed.add_field(
                    name=f"{emojify_item(self.d, item.db_entry.item)} {item.db_entry.item} ({format_required(self.d, item)})",
                    value=f"`{ctx.prefix}comprar {item.db_entry.item.lower()}`",
                    inline=False,
                )

            embed.set_footer(text=f"{ctx.l.econ.page} {page+1}/{len(item_pages)}")

            return embed

        await self.paginator.paginate_embed(ctx, get_page, timeout=60, page_count=len(item_pages))

    @shop.command(name="herramientas")
    async def shop_tools(self, ctx: Ctx):
        """Allows you to shop for tools"""

        await self.shop_logic(
            ctx, "tools", f"{ctx.l.econ.shop.villager_shop} [{ctx.l.econ.shop.tools[3:]}]"
        )

    @shop.command(name="magia")
    async def shop_magic(self, ctx: Ctx):
        """Allows you to shop for magic items"""

        await self.shop_logic(
            ctx, "magic", f"{ctx.l.econ.shop.villager_shop} [{ctx.l.econ.shop.magic[3:]}]"
        )

    @shop.command(name="agricultura", aliases=["agri"])
    async def shop_farming(self, ctx: Ctx):
        """Allows you to shop for farming items"""

        await self.shop_logic(
            ctx, "farming", f"{ctx.l.econ.shop.villager_shop} [{ctx.l.econ.shop.farming[3:]}]"
        )

    @shop.command(name="otros")
    async def shop_other(self, ctx: Ctx):
        """Allows you to shop for other/miscellaneous items"""

        await self.shop_logic(
            ctx, "other", f"{ctx.l.econ.shop.villager_shop} [{ctx.l.econ.shop.other[3:]}]"
        )

    @commands.command(name="mercadopeces", aliases=["tiendapeces"])
    async def fish_market(self, ctx: Ctx):
        embed_template = discord.Embed(
            color=self.bot.embed_color,
            title=ctx.l.econ.fishing.market.title.format(
                self.d.emojis.fish.cod, self.d.emojis.fish.rainbow_trout
            ),
            description=ctx.l.econ.fishing.market.desc,
        )

        fields = list[dict[str, str]]()

        for i, fish in enumerate(self.d.fishing.fish.items()):
            fish_id, fish = fish

            fields.append(
                {
                    "name": f"{self.d.emojis.fish[fish_id]} {fish.name}",
                    "value": ctx.l.econ.fishing.market.current.format(
                        fish.current, self.d.emojis.emerald
                    ),
                }
            )

            if i % 2 == 0:
                fields.append({"name": "\uFEFF", "value": "\uFEFF"})

        pages = [fields[i : i + 6] for i in range(0, len(fields), 6)]
        del fields

        def get_page(page: int) -> discord.Embed:
            embed = embed_template.copy()

            for field in pages[page]:
                embed.add_field(**field)

            embed.set_footer(text=f"{ctx.l.econ.page} {page+1}/{len(pages)}")

            return embed

        await self.paginator.paginate_embed(ctx, get_page, timeout=60, page_count=len(pages))

    @commands.command(name="comprar", aliases=["com"])
    # @commands.cooldown(1, 5, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.user)
    async def buy(self, ctx: Ctx, *, amount_item: str):
        """Allows you to buy items"""

        amount_item = amount_item.lower()
        db_user = await self.db.fetch_user(ctx.author.id)

        if amount_item.startswith("max ") or amount_item.startswith("máx ") or amount_item.startswith("todo "):
            item = amount_item[4:]

            try:
                amount = math.floor(db_user.emeralds / self.d.shop_items[item].buy_price)
            except KeyError:
                await ctx.reply_embed(ctx.l.econ.buy.stupid_2.format(item))
                return

            if amount < 1:
                await ctx.reply_embed(ctx.l.econ.buy.poor_loser_1)
                return
        else:
            split = amount_item.split()

            try:
                amount = split.pop(0)
                amount = int(amount)
            except ValueError:
                item = amount
                item += (" " + " ".join(split)) if len(split) > 0 else ""
                amount = 1
            else:
                item = " ".join(split)

        if amount < 1:
            await ctx.reply_embed(ctx.l.econ.buy.stupid_1)
            return

        shop_item = self.d.shop_items.get(item)

        # shop item doesn't exist lol
        if shop_item is None:
            await ctx.reply_embed(ctx.l.econ.buy.stupid_2.format(item))
            return

        # check if user can actually afford to buy that amount of that item
        if shop_item.buy_price * amount > db_user.emeralds:
            await ctx.reply_embed(
                ctx.l.econ.buy.poor_loser_2.format(amount, shop_item.db_entry.item)
            )
            return

        db_item = await self.db.fetch_item(ctx.author.id, shop_item.db_entry.item)

        # get count of item in db for that user
        if db_item is not None:
            db_item_count = db_item.amount
        else:
            db_item_count = 0

        # if they already have hit the limit on how many they can buy of that item
        count_lt = shop_item.requires.get("count_lt")
        if count_lt is not None and count_lt < db_item_count + amount:
            await ctx.reply_embed(ctx.l.econ.buy.no_to_item_1)
            return

        # ensure user has required items
        for req_item, req_amount in shop_item.requires.get("items", {}).items():
            db_req_item = await self.db.fetch_item(ctx.author.id, req_item)

            if db_req_item is None or db_req_item.amount < req_amount:
                await ctx.reply_embed(
                    ctx.l.econ.buy.need_total_of.format(
                        req_amount, req_item, self.d.emojis[self.d.emoji_items[req_item]]
                    )
                )
                return

        await self.db.balance_sub(ctx.author.id, shop_item.buy_price * amount)

        for req_item, req_amount in shop_item.requires.get("items", {}).items():
            await self.db.remove_item(ctx.author.id, req_item, req_amount * amount)

        sellable = True
        # hoes shouldn't be sellable
        if shop_item.db_entry.item.startswith("Azada"):
            sellable = False

        await self.db.add_item(
            ctx.author.id,
            shop_item.db_entry.item,
            shop_item.db_entry.sell_price,
            amount,
            shop_item.db_entry.sticky,
            sellable=sellable,
        )

        if (
            shop_item.db_entry.item.startswith("Pico")
            or shop_item.db_entry.item == "Amuleto del Pillager"
        ):
            await self.karen.update_support_server_member_roles(ctx.author.id)
        elif shop_item.db_entry.item == "Trofeo de Dinero":
            await self.db.rich_trophy_wipe(ctx.author.id)
            await self.karen.update_support_server_member_roles(ctx.author.id)

        await ctx.reply_embed(
            ctx.l.econ.buy.you_done_bought.format(
                amount,
                shop_item.db_entry.item,
                format_required(self.d, shop_item, amount),
                amount + db_item_count,
            ),
        )

    @commands.command(name="vender", aliases=["ven"])
    # @commands.cooldown(1, 2, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.user)
    async def sell(self, ctx: Ctx, *, amount_item):
        """Allows you to sell items"""

        amount_item = amount_item.lower()

        if amount_item.startswith("max ") or amount_item.startswith("máx ") or amount_item.startswith("todo "):
            item = amount_item[4:]
            db_item = await self.db.fetch_item(ctx.author.id, item)

            if db_item is None:
                await ctx.reply_embed(ctx.l.econ.sell.invalid_item)
                return

            amount = db_item.amount
        else:
            split = amount_item.split(" ")

            try:
                amount = split.pop(0)
                amount = int(amount)
            except ValueError:
                item = amount
                item += (" " + " ".join(split)) if len(split) > 0 else ""
                amount = 1
            else:
                item = " ".join(split)

            db_item = await self.db.fetch_item(ctx.author.id, item)

        if db_item is None:
            await ctx.reply_embed(ctx.l.econ.sell.invalid_item)
            return

        if not db_item.sellable:
            await ctx.reply_embed(ctx.l.econ.sell.stupid_3)
            return

        if amount > db_item.amount:
            await ctx.reply_embed(ctx.l.econ.sell.stupid_1)
            return

        if amount < 1:
            await ctx.reply_embed(ctx.l.econ.sell.stupid_2)
            return

        for fish in self.d.fishing.fish.values():
            if db_item.name == fish.name:
                db_item.sell_price = fish.current

        await self.db.balance_add(ctx.author.id, amount * db_item.sell_price)
        await self.db.remove_item(ctx.author.id, db_item.name, amount)

        await self.db.update_lb(ctx.author.id, "week_emeralds", amount * db_item.sell_price)

        if db_item.name.startswith("Pico") or db_item.name == "Amuleto del Pillager":
            await self.karen.update_support_server_member_roles(ctx.author.id)

        await ctx.reply_embed(
            ctx.l.econ.sell.you_done_sold.format(
                amount, db_item.name, amount * db_item.sell_price, self.d.emojis.emerald
            ),
        )

    @commands.command(name="dar", aliases=["regalar"])
    @commands.guild_only()
    # @commands.cooldown(1, 10, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.user)
    async def give(self, ctx: Ctx, victim: discord.Member, *, amount_item: str):
        """Give an item or emeralds to another person"""

        if victim.bot:
            if victim.id == self.bot.user.id:
                await ctx.reply_embed(ctx.l.econ.give.bot_1)
            else:
                await ctx.reply_embed(ctx.l.econ.give.bot_2)
            return

        if ctx.author.id == victim.id:
            await ctx.reply_embed(ctx.l.econ.give.stupid_1)
            return

        amount_item = amount_item.lower()
        try:
            # to be given is emeralds
            amount = int(amount_item)
            item = "emerald"
        except Exception:
            split = amount_item.split(" ")
            try:
                temp_split = split.copy()
                amount = int(temp_split.pop(0))
                split = temp_split

            except Exception:
                amount = 1

            item = " ".join(split)

        if amount < 1:
            await ctx.reply_embed(ctx.l.econ.give.stupid_2)
            return

        db_user = await self.db.fetch_user(ctx.author.id)

        if "pico" in item.lower() or "espada" in item.lower():
            await ctx.reply_embed(ctx.l.econ.give.and_i_oop)
            return

        if item in ("emerald", "emeralds", ":emerald:"):
            if amount > db_user.emeralds:
                await ctx.reply_embed(ctx.l.econ.give.stupid_3)
                return

            await self.db.balance_sub(ctx.author.id, amount)
            await self.db.balance_add(victim.id, amount)
            await self.db.log_transaction(
                "emerald", amount, arrow.utcnow().datetime, ctx.author.id, victim.id
            )

            await ctx.reply_embed(
                ctx.l.econ.give.gaveems.format(
                    ctx.author.mention, amount, self.d.emojis.emerald, victim.mention
                )
            )

            if (await self.db.fetch_user(victim.id)).give_alert:
                await self.bot.send_embed(
                    victim,
                    ctx.l.econ.give.gaveyouems.format(
                        ctx.author.mention, amount, self.d.emojis.emerald
                    ),
                )
        else:
            db_item = await self.db.fetch_item(ctx.author.id, item)

            if db_item is None or amount > db_item.amount:
                await ctx.reply_embed(ctx.l.econ.give.stupid_4)
                return

            if db_item.sticky:
                await ctx.reply_embed(ctx.l.econ.give.and_i_oop)
                return

            if amount < 1:
                await ctx.reply_embed(ctx.l.econ.give.stupid_2)
                return

            await self.db.remove_item(ctx.author.id, item, amount)
            await self.db.add_item(victim.id, db_item.name, db_item.sell_price, amount)
            self.bot.loop.create_task(
                self.db.log_transaction(
                    db_item.name, amount, arrow.utcnow().datetime, ctx.author.id, victim.id
                )
            )

            await ctx.reply_embed(
                ctx.l.econ.give.gave.format(
                    ctx.author.mention, amount, db_item.name, victim.mention
                )
            )

            if (await self.db.fetch_user(victim.id)).give_alert:
                await self.bot.send_embed(
                    victim,
                    ctx.l.econ.give.gaveyou.format(ctx.author.mention, amount, db_item.name),
                    ignore_exceptions=True,
                )

    @commands.command(name="apostar", aliases=["bet"])
    # @commands.cooldown(1, 30, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.user)
    async def gamble(self, ctx: Ctx, amount):
        """Gamble for emeralds with Villager Bot"""

        db_user = await self.db.fetch_user(ctx.author.id)

        if amount.lower() in ("todo", "max", "máx"):
            amount = db_user.emeralds

        else:
            try:
                amount = int(amount)
            except ValueError:
                await ctx.reply_embed(ctx.l.econ.use_a_number_stupid)
                return

        if amount > db_user.emeralds:
            await ctx.reply_embed(ctx.l.econ.gamble.stupid_1)
            return

        if amount < 10:
            await ctx.reply_embed(ctx.l.econ.gamble.stupid_2)
            return

        if amount > 50000:
            await ctx.reply_embed(ctx.l.econ.gamble.stupid_3)
            return

        if db_user.emeralds >= 200_000:
            await ctx.reply_embed(ctx.l.econ.gamble.too_rich)
            return

        u_roll = random.randint(1, 6) + random.randint(1, 6)
        b_roll = random.randint(1, 6) + random.randint(1, 6)

        await ctx.reply_embed(ctx.l.econ.gamble.roll.format(u_roll, b_roll))

        if u_roll > b_roll:
            multi = (
                40
                + random.randint(5, 30)
                + (await self.db.fetch_item(ctx.author.id, "Amuleto del Pillager") is not None)
                * 20
            )
            multi += (
                await self.db.fetch_item(ctx.author.id, "Trofeo de Dinero") is not None
            ) * 40
            multi = (150 + random.randint(-5, 0)) if multi >= 150 else multi
            multi /= 100

            won = multi * amount
            won = math.ceil(min(won, math.log(won, 1.001)))

            await self.db.balance_add(ctx.author.id, won)
            await ctx.reply_embed(
                ctx.l.econ.gamble.win.format(
                    random.choice(ctx.l.econ.gamble.actions), won, self.d.emojis.emerald
                )
            )
        elif u_roll < b_roll:
            await self.db.balance_sub(ctx.author.id, amount)
            await ctx.reply_embed(ctx.l.econ.gamble.lose.format(amount, self.d.emojis.emerald))
        else:
            await ctx.reply_embed(ctx.l.econ.gamble.tie)

    @commands.command(name="buscar")
    # @commands.cooldown(1, 30 * 60, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.user)
    async def search(self, ctx: Ctx):
        """Beg for emeralds"""

        db_user = await self.db.fetch_user(ctx.author.id)

        # determine whether user gains (True) or loses emeralds (False)
        if random.choice([True, True, True, True, True, False]) or db_user.emeralds < 2:
            # random chance to get mooderald
            if random.randint(1, 420) == 420:
                mooderalds = random.randint(1, 3)
                await self.db.add_item(ctx.author.id, "Antimeralda", 768, mooderalds, True)
                await ctx.reply_embed(
                    random.choice(ctx.l.econ.beg.mooderald).format(
                        f"{mooderalds}{self.d.emojis.autistic_emerald}"
                    )
                )
            else:  # give em emeralds
                amount = 9 + math.ceil(math.log(db_user.emeralds + 1, 1.5)) + random.randint(1, 5)
                amount = random.randint(1, 4) if amount < 1 else amount

                await self.db.balance_add(ctx.author.id, amount)

                await ctx.reply_embed(
                    random.choice(ctx.l.econ.beg.positive).format(
                        f"{amount}{self.d.emojis.emerald}"
                    )
                )
        else:  # user loses emeralds
            amount = (
                9 + math.ceil(math.log(db_user.emeralds + 1, 1.3)) + random.randint(1, 5)
            )  # ah yes, meth

            if amount < 1:
                amount = random.randint(1, 4)
            elif amount > 45000:
                amount = 45000 + random.randint(0, abs(int((amount - 45000)) / 3) + 1)

            if db_user.emeralds < amount:
                amount = db_user.emeralds

            await self.db.balance_sub(ctx.author.id, amount)

            await ctx.reply_embed(
                random.choice(ctx.l.econ.beg.negative).format(f"{amount}{self.d.emojis.emerald}")
            )

    @commands.command(name="minar", aliases=["mi"])
    @commands.guild_only()
    # @commands.cooldown(1, 4, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.user)
    async def mine(self, ctx: Ctx):
        if not await self.math_problem(ctx):
            return

        pickaxe = await self.db.fetch_pickaxe(ctx.author.id)

        # see if user has chugged a poción de suerte
        lucky = await self.karen.check_active_fx(ctx.author.id, "Poción de Suerte")

        # iterate through items findable via mining
        for item in self.d.mining.findables:
            # check if user should get item based on rarity (item.rarity)
            if random.randint(0, item.rarity) == 1 or (
                lucky and random.randint(0, item.rarity) < 3
            ):
                await self.db.add_item(ctx.author.id, item.item, item.sell_price, 1, item.sticky)

                await ctx.reply_embed(
                    f"{self.d.emojis[self.d.emoji_items[pickaxe]]} \uFEFF "
                    + ctx.l.econ.mine.found_item_1.format(
                        random.choice(ctx.l.econ.mine.actions),
                        1,
                        item.item,
                        item.sell_price,
                        self.d.emojis.emerald,
                        random.choice(ctx.l.econ.mine.places),
                    ),
                )

                return

        # calculate if user finds emeralds or not
        found = random.choice(self.calc_yield_chance_list(pickaxe))

        if found:
            # calculate bonus emeralds from enchantment items
            for item in self.d.mining.yields_enchant_items.keys():
                if await self.db.fetch_item(ctx.author.id, item) is not None:
                    found += random.choice(self.d.mining.yields_enchant_items[item])
                    break

            found = int(found) * random.randint(1, 2)

            if await self.db.fetch_item(ctx.author.id, "Trofeo de Dinero") is not None:
                found *= 2

            await self.db.balance_add(ctx.author.id, found)

            await self.db.update_lb(ctx.author.id, "week_emeralds", found)

            await ctx.reply_embed(
                f"{self.d.emojis[self.d.emoji_items[pickaxe]]} \uFEFF "
                + ctx.l.econ.mine.found_emeralds.format(
                    random.choice(ctx.l.econ.mine.actions), found, self.d.emojis.emerald
                ),
            )
        else:
            # only works cause num of pickaxes is 6 and levels of fake finds is 3
            fake_finds = self.d.mining.finds[2 - self.d.mining.pickaxes.index(pickaxe) // 2]

            find = random.choice(fake_finds)
            find_amount = random.randint(1, 6)

            await self.db.add_to_trashcan(
                ctx.author.id, find, self.d.mining.find_values[find], find_amount
            )

            await ctx.reply_embed(
                f"{self.d.emojis[self.d.emoji_items[pickaxe]]} \uFEFF "
                + ctx.l.econ.mine.found_item_2.format(
                    random.choice(ctx.l.econ.mine.actions),
                    find_amount,
                    random.choice(ctx.l.econ.mine.useless),
                    find,
                ),
            )

        # rng increase vault space
        if random.randint(0, 50) == 1 or (lucky and random.randint(1, 25) == 1):
            db_user = await self.db.fetch_user(ctx.author.id)
            if db_user.vault_max < 2000:
                await self.db.update_user(ctx.author.id, vault_max=(db_user.vault_max + 1))

    @commands.command(name="pescar", aliases=["pe"])
    @commands.guild_only()
    # @commands.cooldown(1, 2, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.user)
    async def fish(self, ctx: Ctx):
        if not await self.math_problem(ctx, 5):
            return

        if await self.db.fetch_item(ctx.author.id, "Caña de Pesca") is None:
            await ctx.reply_embed(ctx.l.econ.fishing.stupid_1)
            return

        await ctx.reply_embed(random.choice(ctx.l.econ.fishing.cast))

        async with SuppressCtxManager(ctx.typing()):
            wait = random.randint(12, 32)

            lure_i_book, seaweed_active, lucky = await asyncio.gather(
                self.db.fetch_item(ctx.author.id, "Libro Atracción I"),
                self.karen.check_active_fx(ctx.author.id, "Alga Marina"),
                self.karen.check_active_fx(ctx.author.id, "Poción de Suerte"),
            )

            if lure_i_book is not None:
                wait -= 4

            if seaweed_active:
                wait -= 12
                wait = max(random.randint(3, 10), wait)

            await asyncio.sleep(wait)

        # determine if user has fished up junk or an item (rather than a fish)
        if random.randint(1, 8) == 1 or (lucky and random.randint(1, 5) == 1):

            # calculate the chance for them to fish up junk (True means junk)
            if await self.db.fetch_item(ctx.author.id, "Trofeo de Pesca") is not None or lucky:
                junk_chance = (True, False, False, False, False)
            else:
                junk_chance = (True, True, True, False, False)

            # determine if they fished up junk
            if random.choice(junk_chance):
                junk = random.choice(ctx.l.econ.fishing.junk)
                await ctx.reply_embed(junk, True)

                if "meme" in junk:
                    await self.bot.get_cog("Fun").meme(ctx)

                return

            # iterate through fishing findables until something is found
            while True:
                for item in self.d.fishing.findables:
                    if random.randint(0, (item.rarity // 2) + 2) == 1:
                        await self.db.add_item(
                            ctx.author.id, item.item, item.sell_price, 1, item.sticky
                        )
                        await ctx.reply_embed(
                            random.choice(ctx.l.econ.fishing.item).format(
                                item.item, item.sell_price, self.d.emojis.emerald
                            ),
                            True,
                        )
                        return

        fish_id = random.choices(self.d.fishing.fish_ids, self.d.fishing.fishing_weights)[0]
        fish = self.d.fishing.fish[fish_id]

        await self.db.add_item(ctx.author.id, fish.name, -1, 1)
        await ctx.reply_embed(
            random.choice(ctx.l.econ.fishing.caught).format(fish.name, self.d.emojis.fish[fish_id]),
            True,
        )

        await self.db.update_lb(ctx.author.id, "fish_fished", 1, "add")

        if random.randint(0, 50) == 1 or (lucky and random.randint(1, 25) == 1):
            db_user = await self.db.fetch_user(ctx.author.id)

            if db_user.vault_max < 2000:
                await self.db.update_user(ctx.author.id, vault_max=(db_user.vault_max + 1))

    @commands.command(name="robar", aliases=["rob"])
    @commands.guild_only()
    # @commands.cooldown(1, 300, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.user)
    async def pillage(self, ctx: Ctx, *, victim: discord.Member):
        if victim.bot:
            if victim.id == self.bot.user.id:
                await ctx.reply_embed(ctx.l.econ.pillage.bot_1)
            else:
                await ctx.reply_embed(ctx.l.econ.pillage.bot_2)

            return

        if ctx.author.id == victim.id:
            await ctx.reply_embed(ctx.l.econ.pillage.stupid_1)
            return

        if ctx.guild.get_member(victim.id) is None:
            await ctx.reply_embed(ctx.l.econ.pillage.stupid_2)
            return

        db_user = await self.db.fetch_user(ctx.author.id)

        if db_user.emeralds < 64:
            await ctx.reply_embed(ctx.l.econ.pillage.stupid_3.format(self.d.emojis.emerald))
            return

        db_victim = await self.db.fetch_user(victim.id)

        if db_victim.emeralds < 64:
            await ctx.reply_embed(ctx.l.econ.pillage.stupid_4.format(self.d.emojis.emerald))
            return

        # check if victim has a escudo de perlas active
        if db_victim.shield_pearl and (
            arrow.get(db_victim.shield_pearl).shift(months=1) > arrow.utcnow()
        ):
            await ctx.reply_embed(ctx.l.econ.pillage.stupid_5)
            return

        if db_user.shield_pearl:
            await self.db.update_user(ctx.author.id, shield_pearl=None)

        user_bees = getattr(await self.db.fetch_item(ctx.author.id, "Tarro de Abejas"), "amount", 0)
        victim_bees = getattr(await self.db.fetch_item(victim.id, "Tarro de Abejas"), "amount", 0)

        if await self.db.fetch_item(victim.id, "Amuleto del Pillager"):
            chances = [False] * 5 + [True]
        elif user_bees > victim_bees:
            chances = [False] * 3 + [True] * 5
        elif user_bees < victim_bees:
            chances = [False] * 5 + [True] * 3
        else:
            chances = [True, False]

        pillager_sword_lvl = self.d.sword_list.index(
            (await self.db.fetch_sword(ctx.author.id)).lower()
        )
        victim_sword_lvl = self.d.sword_list.index((await self.db.fetch_sword(victim.id)).lower())

        if pillager_sword_lvl > victim_sword_lvl:
            chances.append(True)
        elif pillager_sword_lvl < victim_sword_lvl:
            chances.append(False)

        success = random.choice(chances)

        if success:
            # calculate base stolen value
            percents = list(range(10, 41, 5))  # 10%-40% [10, 15, 20, 25, 30, 35, 40]
            weights = [0.26, 0.22, 0.17, 0.14, 0.11, 0.07, 0.03]
            percent = numpy.random.choice(percents, 1, p=weights)[0]
            stolen = math.ceil(db_victim.emeralds * (percent / 100))
            # calculate and implement cap based off pillager's balance
            stolen = min(
                stolen,
                math.ceil(db_user.emeralds**1.1 + db_user.emeralds * 5) + random.randint(1, 10),
            )

            # 8% tax to prevent exploitation of pillaging leaderboard
            adjusted = math.ceil(stolen * 0.92)

            await self.db.balance_sub(victim.id, stolen)
            await self.db.balance_add(ctx.author.id, adjusted)  # 8% tax

            await self.db.update_lb(ctx.author.id, "week_emeralds", adjusted)

            await ctx.reply_embed(
                random.choice(ctx.l.econ.pillage.u_win.user).format(adjusted, self.d.emojis.emerald)
            )
            await self.bot.send_embed(
                victim,
                random.choice(ctx.l.econ.pillage.u_win.victim).format(
                    ctx.author.mention, stolen, self.d.emojis.emerald
                ),
            )

            await self.db.update_lb(ctx.author.id, "pillaged_emeralds", adjusted, "add")
        else:
            penalty = max(32, db_user.emeralds // 3)

            await self.db.balance_sub(ctx.author.id, penalty)
            await self.db.balance_add(victim.id, penalty)

            await ctx.reply_embed(
                random.choice(ctx.l.econ.pillage.u_lose.user).format(penalty, self.d.emojis.emerald)
            )
            await self.bot.send_embed(
                victim, random.choice(ctx.l.econ.pillage.u_lose.victim).format(ctx.author.mention)
            )

    @commands.command(name="usar", aliases=["comer", "chugear"])
    # @commands.cooldown(1, 1, commands.BucketType.user)
    async def use_item(self, ctx: Ctx, *, thing):
        """Allows you to use potions and some other items"""

        thing = thing.lower()
        split = thing.split()

        try:
            amount = int(split[0])
            thing = " ".join(split[1:])
        except (IndexError, ValueError):
            amount = 1

        if amount < 1:
            await ctx.reply_embed(ctx.l.econ.use.stupid_3)
            return

        if amount > 100:
            await ctx.reply_embed(ctx.l.econ.use.stupid_4)
            return

        if await self.karen.check_active_fx(ctx.author.id, thing):
            await ctx.reply_embed(ctx.l.econ.use.stupid_1)
            return

        db_item = await self.db.fetch_item(ctx.author.id, thing)

        if db_item is None:
            await ctx.reply_embed(ctx.l.econ.use.stupid_2)
            return

        if db_item.amount < amount:
            await ctx.reply_embed(ctx.l.econ.use.stupid_5)
            return

        generic_potions = {
            "poción apuro i": 60 * 7,
            "poción apuro ii": 60 * 6,
            "poción de suerte": 60 * 4.5,
        }

        if thing in generic_potions:
            duration = generic_potions[thing]

            if amount > 1:
                await ctx.reply_embed(ctx.l.econ.use.stupid_1)
                return

            await self.db.remove_item(ctx.author.id, db_item.name, 1)
            await self.karen.add_active_fx(ctx.author.id, db_item.name, duration)
            await ctx.reply_embed(ctx.l.econ.use.chug.format(db_item.name, duration / 60))

            await asyncio.sleep(duration)
            await self.bot.send_embed(ctx.author, ctx.l.econ.use.done.format(db_item.name))
            return

        if thing == "hueso molido":
            if amount > 1:
                await ctx.reply_embed(ctx.l.econ.use.stupid_1)
                return

            await self.db.remove_item(ctx.author.id, thing, 1)
            await ctx.reply_embed(ctx.l.econ.use.use_bonemeal)

            await self.db.use_bonemeal(ctx.author.id)

            return

        if thing == "alga marina":
            duration = 60 * 30

            if amount > 1:
                await ctx.reply_embed(ctx.l.econ.use.stupid_1)
                return

            await self.db.remove_item(ctx.author.id, thing, 1)
            await self.karen.add_active_fx(ctx.author.id, "Alga Marina", duration)
            await ctx.reply_embed(ctx.l.econ.use.smoke_seaweed.format(30))

            await asyncio.sleep(duration)
            await self.bot.send_embed(ctx.author, ctx.l.econ.use.seaweed_done)
            return

        if thing == "poción de bóveda":
            if amount > 1:
                await ctx.reply_embed(ctx.l.econ.use.stupid_1)
                return

            db_user = await self.db.fetch_user(ctx.author.id)

            if db_user.vault_max > 1999:
                await ctx.reply_embed(ctx.l.econ.use.vault_max)
                return

            add = random.randint(9, 15)

            if db_user.vault_max + add > 2000:
                add = 2000 - db_user.vault_max

            await self.db.remove_item(ctx.author.id, "Poción de Bóveda", 1)
            await self.db.set_vault(ctx.author.id, db_user.vault_balance, db_user.vault_max + add)

            await ctx.reply_embed(ctx.l.econ.use.vault_pot.format(add))
            return

        if thing == "tarro de miel":
            db_user = await self.db.fetch_user(ctx.author.id)

            max_amount = 20 - db_user.health
            if max_amount < 1:
                await ctx.reply_embed(ctx.l.econ.use.cant_use_any.format("Tarros de Miel"))
                return

            if db_user.health + amount > 20:
                amount = max_amount

            await self.db.update_user(ctx.author.id, health=(db_user.health + amount))
            await self.db.remove_item(ctx.author.id, "Tarro de Miel", amount)

            new_health = amount + db_user.health
            await ctx.reply_embed(
                ctx.l.econ.use.chug_honey.format(amount, new_health, self.d.emojis.heart_full)
            )

            return

        if thing == "regalo":
            if amount > 1:
                await ctx.reply_embed(ctx.l.econ.use.stupid_1)
                return

            await self.db.remove_item(ctx.author.id, "Regalo", 1)

            while True:
                for item in self.d.mining.findables:
                    if random.randint(0, (item.rarity // 2) + 2) == 1:
                        await self.db.add_item(
                            ctx.author.id, item.item, item.sell_price, 1, item.sticky
                        )
                        await ctx.reply_embed(
                            random.choice(ctx.l.econ.use.present).format(
                                item.item, item.sell_price, self.d.emojis.emerald
                            )
                        )

                        return

        if thing == "barril":
            if amount > 1:
                await ctx.reply_embed(ctx.l.econ.use.stupid_1)
                return

            await self.db.remove_item(ctx.author.id, "Barril", 1)

            for _ in range(20):
                for item in self.d.mining.findables:
                    if item.rarity > 1000:
                        if random.randint(0, (item.rarity // 1.5) + 5) == 1:
                            await self.db.add_item(
                                ctx.author.id, item.item, item.sell_price, 1, item.sticky
                            )
                            await ctx.reply_embed(
                                random.choice(ctx.l.econ.use.barrel_item).format(
                                    item.item, item.sell_price, self.d.emojis.emerald
                                )
                            )

                            return

            ems = random.randint(2, 4096)

            if await self.db.fetch_item(ctx.author.id, "Trofeo de Dinero") is not None:
                ems *= 1.5
                ems = round(ems)

            await self.db.balance_add(ctx.author.id, ems)

            await self.db.update_lb(ctx.author.id, "week_emeralds", ems)

            await ctx.reply_embed(
                random.choice(ctx.l.econ.use.barrel_ems).format(ems, self.d.emojis.emerald)
            )
            return

        if thing == "recipiente de cristal":
            slime_balls = await self.db.fetch_item(ctx.author.id, "Bola de Slime")

            if slime_balls is None or slime_balls.amount < amount:
                await ctx.reply_embed(ctx.l.econ.use.need_slimy_balls)
                return

            await self.db.remove_item(ctx.author.id, "Bola de Slime", amount)
            await self.db.remove_item(ctx.author.id, "Recipiente de Cristal", amount)
            await self.db.add_item(ctx.author.id, "Recipiente de Slime", 13, amount, False)

            await ctx.reply_embed(ctx.l.econ.use.slimy_balls_funne.format(amount))
            return

        if thing == "recipiente de slime":
            await self.db.remove_item(ctx.author.id, "Recipiente de Slime", amount)
            await self.db.add_item(ctx.author.id, "Bola de Slime", 5, amount, True)

            await ctx.reply_embed(ctx.l.econ.use.beaker_of_slime_undo.format(amount))
            return

        if thing == "escudo perla":
            db_user = await self.db.fetch_user(ctx.author.id)

            if (
                db_user.shield_pearl
                and (arrow.get(db_user.shield_pearl).shift(months=1) > arrow.utcnow())
            ) or amount > 1:
                await ctx.reply_embed(ctx.l.econ.use.stupid_1)
                return

            await self.db.remove_item(ctx.author.id, "Escudo Perla", 1)
            await self.db.update_user(ctx.author.id, shield_pearl=arrow.utcnow().datetime)

            await ctx.reply_embed(ctx.l.econ.use.use_shield_pearl)
            return

        if thing == "perla del tiempo":
            await asyncio.gather(
                self.db.add_crop_time(ctx.author.id, datetime.timedelta(days=-2)),
                self.karen.cooldown_reset("honey", ctx.author.id),
                self.karen.cooldown_reset("pillage", ctx.author.id),
                self.karen.cooldown_reset("search", ctx.author.id),
                self.karen.clear_active_fx(ctx.author.id),
                self.db.remove_item(ctx.author.id, "Perla del Tiempo", 1),
            )

            await ctx.reply_embed(ctx.l.econ.use.use_time_pearl)
            return

        await ctx.reply_embed(ctx.l.econ.use.stupid_6)

    @commands.command(name="miel")
    # @commands.cooldown(1, 24 * 60 * 60, commands.BucketType.user)
    async def honey(self, ctx: Ctx):
        bees = await self.db.fetch_item(ctx.author.id, "Tarro de Abejas")

        bees = 0 if bees is None else bees.amount

        if bees < 100:
            await ctx.reply_embed(random.choice(ctx.l.econ.honey.stupid_1))
            ctx.command.reset_cooldown(ctx)
            return

        # https://www.desmos.com/calculator/radpbfvgsp
        if bees >= 32768:
            bees = int((bees + 1024 * 103.725) // 25)
        elif bees >= 1024:
            bees = int((bees + 1024 * 6) // 7)

        jars = bees - random.randint(math.ceil(bees / 6), math.ceil(bees / 2))
        await self.db.add_item(ctx.author.id, "Tarro de Miel", 1, jars)

        await ctx.reply_embed(random.choice(ctx.l.econ.honey.honey).format(jars))

        # see if user has chugged a poción de suerte
        lucky = await self.karen.check_active_fx(ctx.author.id, "Poción de Suerte")

        if not lucky and random.choice([False] * 3 + [True]):
            bees_lost = random.randint(math.ceil(bees / 75), math.ceil(bees / 50))

            await self.db.remove_item(ctx.author.id, "Tarro de Abejas", bees_lost)

            await ctx.reply_embed(random.choice(ctx.l.econ.honey.ded).format(bees_lost))

    @commands.group(
        name="top", aliases=["lb", "tablas"], case_insensitive=True
    )
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.user)
    @commands.max_concurrency(1, commands.BucketType.user)
    async def leaderboards(self, ctx: Ctx):
        if ctx.invoked_subcommand is not None:
            return

        ctx.command.reset_cooldown(ctx)

        embed = discord.Embed(color=self.bot.embed_color, title=ctx.l.econ.lb.title)

        embed.add_field(
            name=f"{ctx.l.econ.lb.emeralds} {self.d.emojis.emerald}",
            value=f"`{ctx.prefix}top esmeraldas`",
        )

        embed.add_field(name="\uFEFF", value="\uFEFF")

        embed.add_field(
            name=f"{ctx.l.econ.lb.trash} {self.d.emojis.diamond}",
            value=f"`{ctx.prefix}top minerales`",
        )

        embed.add_field(
            name=f"{ctx.l.econ.lb.farming} {self.d.emojis.farming.normal['wheat']}",
            value=f"`{ctx.prefix}top agricultura`",
        )

        embed.add_field(name="\uFEFF", value="\uFEFF")
        
        embed.add_field(
            name=f"{ctx.l.econ.lb.fish} {self.d.emojis.fish.cod}",
            value=f"`{ctx.prefix}top pesca`",
        )

        embed.add_field(
            name=f"{ctx.l.econ.lb.kills} {self.d.emojis.stevegun}",
            value=f"`{ctx.prefix}top mobs`",
        )

        embed.add_field(name="\uFEFF", value="\uFEFF")

        embed.add_field(
            name=f"{ctx.l.econ.lb.stolen} {self.d.emojis.emerald}",
            value=f"`{ctx.prefix}top robos`",
        )

        embed.add_field(
            name=f"{ctx.l.econ.lb.cmds} :keyboard:", value=f"`{ctx.prefix}top comandos`"
        )

        await ctx.reply(embed=embed, mention_author=False)

    async def _lb_logic(
        self,
        ctx: Ctx,
        global_lb: list[dict[str, Any]],
        local_lb: list[dict[str, Any]],
        row_fmt: str,
        title: str,
    ):
        global_lb_str, local_lb_str = await craft_lbs(self.bot, global_lb, local_lb, row_fmt)

        embed = discord.Embed(color=self.bot.embed_color, title=title)

        embed.add_field(name=ctx.l.econ.lb.global_lb, value=global_lb_str)

        await ctx.reply(embed=embed, mention_author=False)

    @leaderboards.command(name="esmeraldas", aliases=["esmeralda"])
    async def leaderboard_emeralds(self, ctx: Ctx):
        async with SuppressCtxManager(ctx.typing()):
            global_lb = await self.db.fetch_global_lb_user("emeralds", ctx.author.id)
            local_lb = await self.db.fetch_local_lb_user(
                "emeralds", ctx.author.id, [m.id for m in ctx.guild.members if not m.bot]
            )

            await self._lb_logic(
                ctx,
                global_lb=global_lb,
                local_lb=local_lb,
                row_fmt=f"\n`{{}}.` **{{}}**{self.d.emojis.emerald} {{}}",
                title=ctx.l.econ.lb.lb_ems.format(self.d.emojis.emerald_spinn),
            )

    @leaderboards.command(name="robos", aliases=["robo"])
    async def leaderboard_pillages(self, ctx: Ctx):
        async with SuppressCtxManager(ctx.typing()):
            global_lb = await self.db.fetch_global_lb("pillaged_emeralds", ctx.author.id)
            local_lb = await self.db.fetch_local_lb(
                "pillaged_emeralds", ctx.author.id, [m.id for m in ctx.guild.members if not m.bot]
            )

            await self._lb_logic(
                ctx,
                global_lb=global_lb,
                local_lb=local_lb,
                row_fmt=f"\n`{{}}.` **{{}}**{self.d.emojis.emerald} {{}}",
                title=ctx.l.econ.lb.lb_pil.format(self.d.emojis.emerald),
            )

    @leaderboards.command(name="mobs", aliases=["mob"])
    async def leaderboard_mobkills(self, ctx: Ctx):
        async with SuppressCtxManager(ctx.typing()):
            global_lb = await self.db.fetch_global_lb("mobs_killed", ctx.author.id)
            local_lb = await self.db.fetch_local_lb(
                "mobs_killed", ctx.author.id, [m.id for m in ctx.guild.members if not m.bot]
            )

            await self._lb_logic(
                ctx,
                global_lb=global_lb,
                local_lb=local_lb,
                row_fmt=f"\n`{{}}.` **{{}}**{self.d.emojis.stevegun} {{}}",
                title=ctx.l.econ.lb.lb_kil.format(self.d.emojis.stevegun),
            )

    @leaderboards.command(name="comandos", aliases=["cmd", "cmds"])
    async def leaderboard_commands(self, ctx: Ctx):
        async with SuppressCtxManager(ctx.typing()):
            global_lb = await self.db.fetch_global_lb("commands", ctx.author.id)
            local_lb = await self.db.fetch_local_lb(
                "commands", ctx.author.id, [m.id for m in ctx.guild.members if not m.bot]
            )

            await self._lb_logic(
                ctx,
                global_lb=global_lb,
                local_lb=local_lb,
                row_fmt="\n`{}.` **{}** :keyboard: {}",
                title=ctx.l.econ.lb.lb_cmds.format(" :keyboard: "),
            )

    @leaderboards.command(name="pesca", aliases=["peces"])
    async def leaderboard_fish(self, ctx: Ctx):
        async with SuppressCtxManager(ctx.typing()):
            global_lb = await self.db.fetch_global_lb("fish_fished", ctx.author.id)
            local_lb = await self.db.fetch_local_lb(
                "fish_fished", ctx.author.id, [m.id for m in ctx.guild.members if not m.bot]
            )

            await self._lb_logic(
                ctx,
                global_lb=global_lb,
                local_lb=local_lb,
                row_fmt=f"\n`{{}}.` **{{}}**{self.d.emojis.fish.cod} {{}}",
                title=ctx.l.econ.lb.lb_fish.format(self.d.emojis.fish.rainbow_trout),
            )

    @leaderboards.command(name="agricultura", aliases=["cultivo"])
    async def leaderboard_farming(self, ctx: Ctx):
        async with SuppressCtxManager(ctx.typing()):
            global_lb = await self.db.fetch_global_lb("crops_planted", ctx.author.id)
            local_lb = await self.db.fetch_local_lb(
                "crops_planted", ctx.author.id, [m.id for m in ctx.guild.members if not m.bot]
            )

            await self._lb_logic(
                ctx,
                global_lb=global_lb,
                local_lb=local_lb,
                row_fmt=f"\n`{{}}.` **{{}}**{self.d.emojis.farming.seeds['wheat']} {{}}",
                title=ctx.l.econ.lb.lb_farming.format(f" {self.d.emojis.farming.normal['wheat']} "),
            )

    @leaderboards.command(name="minerales", aliases=["mineral"])
    async def leaderboard_trash(self, ctx: Ctx):
        async with SuppressCtxManager(ctx.typing()):
            global_lb = await self.db.fetch_global_lb("trash_emptied", ctx.author.id)
            local_lb = await self.db.fetch_local_lb(
                "trash_emptied", ctx.author.id, [m.id for m in ctx.guild.members if not m.bot]
            )

            await self._lb_logic(
                ctx,
                global_lb=global_lb,
                local_lb=local_lb,
                row_fmt=f"\n`{{}}.` **{{}}** {self.d.emojis.diamond} {{}}",
                title=ctx.l.econ.lb.lb_trash.format(f" {self.d.emojis.diamond} "),
            )

        await ctx.reply(embed=embed, mention_author=False)

    @commands.group(name="agricultura", case_insensitive=True)
    @commands.max_concurrency(1, per=commands.BucketType.user, wait=False)
    @commands.guild_only()
    async def farm(self, ctx: Ctx):
        if ctx.invoked_subcommand is not None:
            return

        db_farm_plots = await self.db.fetch_farm_plots(ctx.author.id)
        available = await self.db.count_ready_farm_plots(ctx.author.id)

        max_plots = self.d.farming.max_plots[await self.db.fetch_hoe(ctx.author.id)]

        emojis = [emojify_crop(self.d, r["crop_type"]) for r in db_farm_plots] + [
            emojify_crop(self.d, "dirt")
        ] * (max_plots - len(db_farm_plots))
        emoji_farm = "> " + "\n> ".join(
            "".join(r[::-1])
            for r in zip(*[emojis[i : i + 5] for i in range(0, len(emojis), 5)][::-1])
        )

        embed = discord.Embed(color=self.bot.embed_color)
        embed.set_author(
            name=ctx.l.econ.farm.s_farm.format(user=ctx.author.display_name),
            icon_url=getattr(ctx.author.avatar, "url", None),
        )

        embed.add_field(
            name=ctx.l.econ.farm.commands_title,
            value="\n".join(
                c.format(prefix=ctx.prefix) for c in ctx.l.econ.farm.commands.dict().values()
            ),
        )

        embed.description = (
            emoji_farm
            + "\n\n"
            + ctx.l.econ.farm.available.format(available=available, max=len(db_farm_plots))
        )

        await ctx.send(embed=embed)

    @farm.command(name="cultivar")
    async def farm_plant(self, ctx: Ctx, *, item: str):
        item = item.lower()
        split = item.split()

        try:
            amount = int(split[0])
            item = " ".join(split[1:])
        except (IndexError, ValueError):
            amount = 1

        if amount < 1:
            await ctx.reply_embed(ctx.l.econ.use.stupid_3)
            return

        if amount > 60:
            await ctx.reply_embed(ctx.l.econ.use.stupid_4)
            return

        db_item = await self.db.fetch_item(ctx.author.id, item)

        if db_item is None:
            await ctx.reply_embed(ctx.l.econ.use.stupid_2)
            return

        crop_type = self.d.farming.plantable.get(item.lower())

        if crop_type is None:
            await ctx.reply_embed(ctx.l.econ.farm.cant_plant)
            return

        max_plots = self.d.farming.max_plots[await self.db.fetch_hoe(ctx.author.id)]
        plots_count = await self.db.count_farm_plots(ctx.author.id)

        # check count of used farm plots from db
        if plots_count >= max_plots:
            await ctx.reply_embed(ctx.l.econ.farm.no_plots)
            return

        if db_item.amount < amount:
            await ctx.reply_embed(ctx.l.econ.use.stupid_5)
            return

        if amount > max_plots - plots_count:
            await ctx.reply_embed(ctx.l.econ.farm.no_plots_2)
            return

        # remove the item and plant it
        await self.db.remove_item(ctx.author.id, item, amount)
        await self.db.add_farm_plot(ctx.author.id, crop_type, amount)

        await ctx.reply_embed(
            ctx.l.econ.farm.planted.format(
                amount=amount, crop=emojify_item(self.d, self.d.farming.name_map[crop_type])
            )
        )

    @farm.command(name="cosechar")
    async def farm_harvest(self, ctx: Ctx):
        records = await self.db.fetch_ready_crops(ctx.author.id)
        await self.db.delete_ready_crops(ctx.author.id)

        if not records:
            await ctx.reply_embed(ctx.l.econ.farm.cant_harvest)
            return

        user_bees = await self.db.fetch_item(ctx.author.id, "Tarro de Abejas")
        user_bees = 0 if user_bees is None else user_bees.amount
        extra_yield_limit = round(max(0, math.log((user_bees + 0.0001) / 64)))

        amounts_harvested = defaultdict[str, int](int)

        for r in records:
            # amount of crop harvested
            crop_type_yield = self.d.farming.crop_yields[r["crop_type"]]
            amount = sum(
                random.randint(*crop_type_yield) for _ in range(r["count"])
            ) + random.randint(0, extra_yield_limit)

            await self.db.add_item(
                ctx.author.id,
                self.d.farming.name_map[r["crop_type"]],
                self.d.farming.emerald_yields[r["crop_type"]],
                amount,
            )

            amounts_harvested[r["crop_type"]] += amount

        harvest_str = ", ".join(
            [
                f"{amount} {self.d.emojis.farming.normal[crop_type]}"
                for crop_type, amount in amounts_harvested.items()
            ]
        )

        await ctx.reply_embed(ctx.l.econ.farm.harvested.format(crops=harvest_str))

    @commands.group(name="minerales")
    @commands.guild_only()
    async def trash(self, ctx: Ctx):
        if ctx.invoked_subcommand:
            return

        embed = discord.Embed(color=self.bot.embed_color)
        embed.set_author(
            name=ctx.l.econ.trash.s_trash.format(user=ctx.author.display_name),
            icon_url=getattr(ctx.author.avatar, "url", None),
        )

        items = await self.db.fetch_trashcan(ctx.author.id)

        if len(items) == 0:
            embed.description = ctx.l.econ.trash.no_trash
        else:
            items_formatted = "\n".join(
                [
                    f"> `{item['amount']}x` {item['item']} ({float(item['amount']) * item['value']:0.02f}{self.d.emojis.emerald})"
                    for item in items
                ]
            )

            total_ems = sum([float(item["amount"]) * item["value"] for item in items])
            total_ems *= (
                await self.db.fetch_item(ctx.author.id, "Trofeo de Dinero") is not None
            ) + 1
            total_ems *= (await self.db.fetch_item(ctx.author.id, "Reciclador") is not None) + 1

            embed.description = (
                ctx.l.econ.trash.total_contents.format(
                    ems=round(total_ems, 2), ems_emoji=self.d.emojis.emerald
                )
                + f"\n\n{items_formatted}\n\n"
                + ctx.l.econ.trash.how_to_empty.format(prefix=ctx.prefix)
            )

        await ctx.reply(embed=embed, mention_author=False)

    @trash.command(name="vender")
    async def trashcan_empty(self, ctx: Ctx):
        total_ems, amount = await self.db.empty_trashcan(ctx.author.id)

        total_ems = math.floor(total_ems)
        total_ems *= (await self.db.fetch_item(ctx.author.id, "Trofeo de Dinero") is not None) + 1
        total_ems *= (await self.db.fetch_item(ctx.author.id, "Reciclador") is not None) + 1

        await self.db.balance_add(ctx.author.id, total_ems)

        await self.db.update_lb(ctx.author.id, "trash_emptied", amount)
        await self.db.update_lb(ctx.author.id, "week_emeralds", total_ems)

        await ctx.reply_embed(
            ctx.l.econ.trash.emptied_for.format(ems=total_ems, ems_emoji=self.d.emojis.emerald)
        )

    # @commands.command(name="fight", aliases=["battle"])
    # @commands.is_owner()
    # @commands.cooldown(1, 1, commands.BucketType.user)
    # async def fight(self, ctx: Ctx, user_2: discord.Member, emerald_pool: int):
    #     user_1 = ctx.author
    #
    #     if user_1 == user_2:
    #         await ctx.reply_embed("You can't fight yourself!")
    #         return
    #
    #     await self.karen.econ_pause(user_1.id)
    #     await self.karen.econ_pause(user_2.id)
    #
    #     def attack_msg_check(message: discord.Message):
    #         return (
    #             message.channel == ctx.channel
    #             and (message.author == user_1 or message.author == user_2)
    #             and message.content.strip(ctx.prefix).lower() in self.d.mobs_mech.valid_attacks
    #         )
    #
    #     try:
    #         db_user_1, db_user_2 = await asyncio.gather(
    #             self.db.fetch_user(user_1.id), self.db.fetch_user(user_2.id)
    #         )
    #
    #         if db_user_1.emeralds < emerald_pool:
    #             await ctx.reply_embed(
    #                 f"You don't have {emerald_pool}{self.d.emojis.emerald} to bet."
    #             )
    #             return
    #
    #         if db_user_2.emeralds < emerald_pool:
    #             await ctx.reply_embed(
    #                 f"{user_2.mention} doesn't have {emerald_pool}{self.d.emojis.emerald} to bet."
    #             )
    #             return
    #
    #         user_1_sword: str
    #         user_2_sword: str
    #         user_1_items: list[Item]
    #         user_2_items: list[Item]
    #         user_1_sword, user_2_sword, user_1_items, user_2_items = await asyncio.gather(
    #             self.db.fetch_sword(user_1.id),
    #             self.db.fetch_sword(user_2.id),
    #             self.db.fetch_items(user_1.id),
    #             self.db.fetch_items(user_2.id),
    #         )
    #
    #         def get_item_count(items: list[Item], name: str) -> int:
    #             name = name.lower()
    #             filtered = [i for i in items if i.name.lower() == name]
    #             return filtered[0].amount if filtered else 0
    #
    #         user_1_health = db_user_1.health
    #         user_2_health = db_user_2.health
    #
    #         user_1_bees = get_item_count(user_1_items, "Tarro de Abejas")
    #         user_2_bees = get_item_count(user_2_items, "Tarro de Abejas")
    #
    #         user_1_sharpness = (
    #             2
    #             if get_item_count(user_1_items, "Libro Filo II")
    #             else 1
    #             if get_item_count(user_1_items, "Libro Filo I")
    #             else 0
    #         )
    #         user_2_sharpness = (
    #             2
    #             if get_item_count(user_2_items, "Libro Filo II")
    #             else 1
    #             if get_item_count(user_2_items, "Libro Filo I")
    #             else 0
    #         )
    #
    #         def attack_damage(sharp: int, sword: str) -> int:
    #             damage = random.randint(
    #                 *{
    #                     "Espada de Netherite": [7, 10],
    #                     "Espada de Diamante": [6, 7],
    #                     "Espada de Oro": [4, 5],
    #                     "Espada de Hierro": [2, 4],
    #                     "Espada de Piedra": [1, 3],
    #                     "Espada de Madera": [1, 2],
    #                 }[sword]
    #             )
    #
    #             damage += 0.25 * sharp
    #
    #             return math.ceil(damage / 1.3)
    #
    #         embed = discord.Embed(color=self.bot.embed_color)
    #
    #         embed.add_field(
    #             name=f"**{user_1.display_name}**",
    #             value=f"{user_1_health}/20 {self.d.emojis.heart_full} **|** {emojify_item(self.d, user_1_sword)} **|** {user_1_bees}{self.d.emojis.jar_of_bees} ",
    #         )
    #         embed.add_field(name="\uFEFF", value="\uFEFF")
    #         embed.add_field(
    #             name=f"**{user_2.display_name}**",
    #             value=f"{user_2_health}/20 {self.d.emojis.heart_full} **|** {emojify_item(self.d, user_2_sword)} **|** {user_2_bees}{self.d.emojis.jar_of_bees} ",
    #         )
    #
    #         challenge_msg = await ctx.send(
    #             f"{user_2.mention} react with {self.d.emojis.netherite_sword_ench} to accept the challenge!",
    #             embed=embed,
    #         )
    #         await challenge_msg.add_reaction(self.d.emojis.netherite_sword_ench)
    #
    #         try:
    #             await self.bot.wait_for(
    #                 "reaction_add",
    #                 check=(lambda r, u: r.message == challenge_msg and u == user_2),
    #                 timeout=60,
    #             )
    #         except asyncio.TimeoutError:
    #             await challenge_msg.edit(
    #                 embed=discord.Embed(
    #                     color=self.bot.embed_color,
    #                     description=f"{user_2.mention} didn't accept the challenge in time...",
    #                 )
    #             )
    #             return
    #
    #         try:
    #             await challenge_msg.clear_reaction(self.d.emojis.netherite_sword_ench)
    #         except discord.Forbidden:
    #             pass
    #
    #         msg: Optional[discord.Message] = None
    #
    #         while True:
    #             if user_1_health <= 0 or user_2_health <= 0:
    #                 break
    #
    #             try:
    #                 attack_msg = await self.bot.wait_for(
    #                     "message", check=attack_msg_check, timeout=10
    #                 )
    #                 last_user_who_attacked = attack_msg.author
    #             except asyncio.TimeoutError:
    #                 await ctx.send("Fight cancelled because no one was attacking...")
    #                 return
    #
    #             user_1_damage = attack_damage(user_1_sharpness, user_1_sword) + random.randint(
    #                 0, user_1_bees > user_2_bees
    #             )
    #             user_2_damage = attack_damage(user_2_sharpness, user_2_sword) + random.randint(
    #                 0, (user_2_bees > user_1_bees) * 2
    #             )
    #
    #             user_2_health -= user_1_damage
    #             user_1_health -= user_2_damage
    #
    #             embed = discord.Embed(
    #                 color=self.bot.embed_color,
    #                 description=f"user_1 ({user_1_health}hp) did {user_1_damage} dmg\nuser_2 ({user_2_health}hp) did {user_2_damage}",
    #             )
    #
    #             embed.add_field(
    #                 name=f"**{user_1.display_name}**",
    #                 value=make_health_bar(
    #                     max(user_1_health, 0),
    #                     20,
    #                     self.d.emojis.heart_full,
    #                     self.d.emojis.heart_half,
    #                     self.d.emojis.heart_empty,
    #                 ),
    #                 inline=False,
    #             )
    #
    #             embed.add_field(
    #                 name=f"**{user_2.display_name}**",
    #                 value=make_health_bar(
    #                     max(user_2_health, 0),
    #                     20,
    #                     self.d.emojis.heart_full,
    #                     self.d.emojis.heart_half,
    #                     self.d.emojis.heart_empty,
    #                 ),
    #                 inline=False,
    #             )
    #
    #             msg = await (ctx.send if msg is None else msg.edit)(embed=embed)
    #
    #             await asyncio.sleep(random.random() * 5)
    #
    #         await ctx.send("ding dong done L + ratio + nobitches")
    #     finally:
    #         await self.karen.econ_unpause(user_1.id)
    #         await self.karen.econ_unpause(user_2.id)


async def setup(bot: VillagerBotCluster) -> None:
    await bot.add_cog(Econ(bot))
