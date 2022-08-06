from collections import defaultdict
from functools import cached_property
import time
from typing import Optional
import asyncio

import psutil
import asyncpg

from common.coms.packet_handling import PacketHandlerRegistry, handle_packet
from common.coms.packet_type import PacketType
from common.coms.server import Server
from common.models.data import Data
from common.utils.code import execute_code, format_exception
from karen.utils.cooldowns import CooldownManager, MaxConcurrencyManager
from common.utils.recurring_tasks import RecurringTasksMixin, recurring_task
from common.utils.setup import setup_database_pool
from karen.models.secrets import Secrets
from karen.utils.setup import setup_logging

logger = setup_logging()


class Share:
    """Class which holds any data that clients can access (excluding exec packet)"""

    def __init__(self, data: Data):
        self.command_cooldowns = CooldownManager(data.cooldown_rates)
        self.command_concurrency = MaxConcurrencyManager()
        self.econ_paused_users = dict[int, float]()  # user_id: time paused
        self.mine_commands = defaultdict[int, int]()  # user_id: cmd_count, used for fishing as well
        self.trivia_commands = defaultdict[int, int]()  # user_id: cmd_count
        self.command_counts = defaultdict[int, int]()  # user_id: cmd_count
        self.active_fx = defaultdict[int, set[str]]()  # user_id: set[fx]


class MechaKaren(PacketHandlerRegistry, RecurringTasksMixin):
    def __init__(self, secrets: Secrets, data: Data):
        self.secrets = secrets

        self.db: Optional[asyncpg.Pool] = None

        self.server = Server(
            secrets.karen.host,
            secrets.karen.port,
            secrets.karen.auth,
            self.get_packet_handlers(),
            logger,
        )

        self.current_cluster_id = 0

        self.v = Share(data)
        
        # must be last
        RecurringTasksMixin.__init__(self, logger)

    @cached_property
    def chunked_shard_ids(self) -> list[list[int]]:
        shard_ids = list(range(self.secrets.shard_count))
        shards_per_cluster = self.secrets.shard_count // self.secrets.cluster_count + 1
        return [shard_ids[i : i + shards_per_cluster] for i in range(self.secrets.cluster_count)]

    async def start(self) -> None:
        self.db = await setup_database_pool(self.secrets.database)

        self.start_recurring_tasks()

        # nothing past this point
        await self.server.serve()

    async def stop(self) -> None:
        self.cancel_recurring_tasks()

        if self.db is not None:
            await self.db.close()

    ###### loops ###############################################################

    @recurring_task(minutes=2)
    async def loop_clear_dead(self):
        self.v.command_cooldowns.clear_dead()

    @recurring_task(minutes=1)
    async def loop_dump_command_counts(self):
        if not self.v.command_counts:
            return

        commands_dump = list(self.v.command_counts.items())
        user_ids = [(user_id,) for user_id in self.v.command_counts.keys()]
        self.v.command_counts.clear()

        # ensure users are in db first
        await self.db.executemany(
            'INSERT INTO users (user_id) VALUES ($1) ON CONFLICT ("user_id") DO NOTHING', user_ids
        )
        
        await self.db.executemany(
            'INSERT INTO leaderboards (user_id, commands, week_commands) VALUES ($1, $2, $2) ON CONFLICT ("user_id") DO UPDATE SET "commands" = leaderboards.commands + $2, "week_commands" = leaderboards.week_commands + $2 WHERE leaderboards.user_id = $1',
            commands_dump,
        )

    @recurring_task(seconds=32)
    async def loop_heal_users(self):
        await self.db.execute("UPDATE users SET health = health + 1 WHERE health < 20")

    @recurring_task(minutes=10)
    async def loop_clear_trivia_commands(self):
        self.v.trivia_commands.clear()

    @recurring_task(seconds=5)
    async def loop_remind_reminders(self):
        reminders = await self.db.fetch(
            "DELETE FROM reminders WHERE at <= NOW() RETURNING channel_id, user_id, message_id, reminder"
        )

        broadcast_coros = [self.server.broadcast(PacketType.REMINDER, {**r}) for r in reminders]

    ###### packet handlers #####################################################

    @handle_packet(PacketType.GET_SHARD_IDS)
    async def packet_get_shard_ids(self):
        shard_ids = self.chunked_shard_ids[self.current_cluster_id]
        self.current_cluster_id += 1
        return shard_ids

    @handle_packet(PacketType.EXEC)
    async def packet_exec(self, code: str):
        try:
            result = await execute_code(code, {"karen": self, "v": self.v})
            success = True
        except Exception as e:
            result = format_exception(e)
            success = False
        
            logger.error("An error occurred while handling an EXEC packet", exc_info=True)
        
        return {"result": result, "success": success}

    @handle_packet(PacketType.COOLDOWN_CHECK_ADD)
    async def packet_cooldown(self, command: str, user_id: int):
        can_run, remaining = self.v.command_cooldowns.check_add_cooldown(command, user_id)
        return {"can_run": can_run, "remaining": remaining}

    @handle_packet(PacketType.COOLDOWN_ADD)
    async def packet_cooldown_add(self, command: str, user_id: int):
        self.v.command_cooldowns.add_cooldown(command, user_id)
    
    @handle_packet(PacketType.COOLDOWN_RESET)
    async def packet_cooldown_reset(self, command: str, user_id: int):
        self.v.command_cooldowns.clear_cooldown(command, user_id)

    @handle_packet(PacketType.DM_MESSAGE)
    async def packet_dm_message(self, user_id: int, message_id: int, content: Optional[str]):
        await self.server.broadcast(PacketType.DM_MESSAGE, {"user_id": user_id, "message_id": message_id, "content": content})

    @handle_packet(PacketType.MINE_COMMAND)
    async def packet_mine_command(self, user_id: int, addition: int):
        self.v.mine_commands[user_id] += addition
        return self.v.mine_commands[user_id]

    @handle_packet(PacketType.MINE_COMMANDS_RESET)
    async def packet_mine_commands_reset(self, user_id: int):
        self.v.mine_commands.pop(user_id, None)

    @handle_packet(PacketType.CONCURRENCY_CHECK)
    async def packet_concurrency_check(self, command: str, user_id: int):
        return self.v.command_concurrency.check(command, user_id)

    @handle_packet(PacketType.CONCURRENCY_ACQUIRE)
    async def packet_concurrency_acquire(self, command: str, user_id: int):
        self.v.command_concurrency.acquire(command, user_id)

    @handle_packet(PacketType.CONCURRENCY_RELEASE)
    async def packet_concurrency_release(self, command: str, user_id: int):
        self.v.command_concurrency.release(command, user_id)
    
    @handle_packet(PacketType.COMMAND_RAN)
    async def packet_command_ran(self, user_id: int):
        self.v.command_counts[user_id] += 1

    @handle_packet(PacketType.FETCH_STATS)
    async def handle_fetch_stats_packet(self):
        proc = psutil.Process()
        with proc.oneshot():
            mem_usage = proc.memory_full_info().uss
            threads = proc.num_threads()

        return [mem_usage, threads, len(asyncio.all_tasks())] + [0] * 7

    @handle_packet(PacketType.ECON_PAUSE_CHECK)
    async def packet_econ_pause_check(self, user_id: int):
        return user_id in self.v.econ_paused_users

    @handle_packet(PacketType.ECON_PAUSE)
    async def packet_econ_pause(self, user_id: int):
        self.v.econ_paused_users[user_id] = time.time()
        
    @handle_packet(PacketType.ECON_PAUSE_UNDO)
    async def packet_econ_pause_undo(self, user_id: int):
        self.v.econ_paused_users.pop(user_id, None)

    @handle_packet(PacketType.ACTIVE_FX_CHECK)
    async def packet_active_fx_check(self, user_id: int, fx: str):
        return fx.lower() in self.v.active_fx[user_id]

    @handle_packet(PacketType.ACTIVE_FX_ADD)
    async def packet_active_fx_add(self, user_id: int, fx: str):
        self.v.active_fx[user_id].add(fx)

    @handle_packet(PacketType.ACTIVE_FX_REMOVE)
    async def packet_active_fx_remove(self, user_id: int, fx: str):
        self.v.active_fx[user_id].remove(fx.lower())
