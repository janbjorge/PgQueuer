from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import timedelta
from itertools import count

from PgQueuer.cli import querier
from PgQueuer.db import dsn
from PgQueuer.models import Job
from PgQueuer.qm import QueueManager
from PgQueuer.queries import Queries
from tqdm.asyncio import tqdm


async def consumer(
    qm: QueueManager,
    batch_size: int,
    bar: tqdm,
) -> None:
    @qm.entrypoint("asyncfetch")
    async def asyncfetch(job: Job) -> None:
        bar.update()

    @qm.entrypoint("syncfetch")
    def syncfetch(job: Job) -> None:
        bar.update()

    await qm.run(batch_size=batch_size)


async def producer(
    alive: asyncio.Event,
    queries: Queries,
    batch_size: int,
    cnt: count,
) -> None:
    assert batch_size > 0
    entrypoints = ["syncfetch", "asyncfetch"] * batch_size
    while not alive.is_set():
        await queries.enqueue(
            random.sample(entrypoints, k=batch_size),
            [f"{next(cnt)}".encode() for _ in range(batch_size)],
            [0] * batch_size,
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description="PGQueuer benchmark tool.")

    parser.add_argument(
        "-d",
        "--driver",
        default="apg",
        help="Postgres driver to be used asyncpg (apg) or psycopg (psy).",
        choices=["apg", "psy"],
    )

    parser.add_argument(
        "-t",
        "--timer",
        type=lambda x: timedelta(seconds=float(x)),
        default=timedelta(seconds=10),
        help="Run the benchmark for a specified number of seconds. Default is 10.",
    )

    parser.add_argument(
        "-dq",
        "--dequeue",
        type=int,
        default=5,
        help="Number of concurrent dequeue tasks. Default is 5.",
    )
    parser.add_argument(
        "-dqbs",
        "--dequeue-batch-size",
        type=int,
        default=10,
        help="Batch size for dequeue tasks. Default is 10.",
    )

    parser.add_argument(
        "-eq",
        "--enqueue",
        type=int,
        default=1,
        help="Number of concurrent enqueue tasks. Default is 1.",
    )
    parser.add_argument(
        "-eqbs",
        "--enqueue-batch-size",
        type=int,
        default=10,
        help="Batch size for enqueue tasks. Default is 10.",
    )
    args = parser.parse_args()

    print(f"""Settings:
Timer:                  {args.timer.total_seconds()} seconds
Dequeue:                {args.dequeue}
Dequeue Batch Size:     {args.dequeue_batch_size}
Enqueue:                {args.enqueue}
Enqueue Batch Size:     {args.enqueue_batch_size}
""")

    # await (await querier(args.driver, dsn())).clear_log()
    # await (await querier(args.driver, dsn())).clear_queue()

    alive = asyncio.Event()
    qms = list[QueueManager]()

    async def enqueue(alive: asyncio.Event) -> None:
        cnt = count()
        producers = [
            producer(
                alive,
                await querier(args.driver, dsn()),
                int(args.enqueue_batch_size),
                cnt,
            )
            for _ in range(args.enqueue)
        ]
        await asyncio.gather(*producers)

    async def dequeue(qms: list[QueueManager]) -> None:
        queries = [await querier(args.driver, dsn()) for _ in range(args.dequeue)]
        for q in queries:
            qms.append(QueueManager(q.driver))

        with tqdm(
            ascii=True,
            unit=" job",
            unit_scale=True,
            file=sys.stdout,
        ) as bar:
            consumers = [consumer(q, int(args.dequeue_batch_size), bar) for q in qms]
            await asyncio.gather(*consumers)

    async def dequeue_alive_timer(
        qms: list[QueueManager],
        alive: asyncio.Event,
    ) -> None:
        await asyncio.sleep(args.timer.total_seconds())
        # Stop producers
        alive.set()
        # Stop consumers
        for q in qms:
            q.alive = False

    await asyncio.gather(
        dequeue(qms),
        enqueue(alive),
        dequeue_alive_timer(qms, alive),
    )

    qsize = sum(x.count for x in await (await querier(args.driver, dsn())).queue_size())
    print(f"Queue size: {qsize}")


if __name__ == "__main__":
    asyncio.run(main())
