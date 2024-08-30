from __future__ import annotations

import asyncio
import importlib
import signal
from concurrent.futures import Future, ProcessPoolExecutor
from datetime import timedelta
from typing import Awaitable, Callable, TypeAlias

from . import logconfig, qm

QM_FACTORY: TypeAlias = Callable[[], Awaitable[qm.QueueManager]]


def load_queue_manager_factory(factory_path: str) -> QM_FACTORY:
    """
    Load the QueueManager factory function from a given module path.

    Dynamically imports the specified module and retrieves the factory function
    used to create a QueueManager instance. The factory function should be an
    asynchronous callable that returns a QueueManager.

    Args:
        factory_path (str): The full module path to the factory function,
            e.g., 'myapp.create_queue_manager'.

    Returns:
        QM_FACTORY: A callable that returns an awaitable QueueManager instance.
    """
    module_name, factory_name = factory_path.rsplit(".", 1)
    module = importlib.import_module(module_name)
    return getattr(module, factory_name)


async def __runit(
    factory_fn: str,
    dequeue_timeout: timedelta,
    batch_size: int,
    retry_timer: timedelta | None,
    worker_id: int,
) -> None:
    qm_factory = load_queue_manager_factory(factory_fn)
    qm = await qm_factory()  # Create the QueueManager instance

    def graceful_shutdown(signum: int, frame: object) -> None:
        """
        Handle incoming signals that require a graceful shutdown of the application.
        """
        logconfig.logger.info(
            "Received signal %s, shutting down worker %s",
            signum,
            worker_id,
        )
        qm.alive = False

    # Setup signal handlers for graceful shutdown of the QueueManager.
    signal.signal(signal.SIGINT, graceful_shutdown)  # Handle Ctrl-C
    signal.signal(signal.SIGTERM, graceful_shutdown)  # Handle termination request

    # Start the QueueManager's operation
    await qm.run(
        dequeue_timeout=dequeue_timeout,
        batch_size=batch_size,
        retry_timer=retry_timer,
    )


def _runit(
    factory_fn: str,
    dequeue_timeout: timedelta,
    batch_size: int,
    retry_timer: timedelta | None,
    worker_id: int,
) -> None:
    asyncio.run(
        __runit(
            factory_fn=factory_fn,
            dequeue_timeout=dequeue_timeout,
            batch_size=batch_size,
            retry_timer=retry_timer,
            worker_id=worker_id,
        ),
    )


async def runit(
    factory_fn: str,
    dequeue_timeout: timedelta,
    batch_size: int,
    retry_timer: timedelta | None,
    workers: int,
) -> None:
    """
    Instantiate and run a QueueManager using the provided factory function.

    This function handles the setup and lifecycle management of the QueueManager,
    including signal handling for graceful shutdown. It loads the QueueManager
    factory, creates an instance, sets up signal handlers, and starts the
    QueueManager's run loop with the specified parameters.

    Args:
        factory_fn (str): The module path to the QueueManager factory function,
            e.g., 'myapp.create_queue_manager'.
        dequeue_timeout (timedelta): The timeout duration for dequeuing jobs.
        batch_size (int): The number of jobs to retrieve in each batch.
        retry_timer (timedelta | None): The duration after which to retry 'picked' jobs
            that may have stalled. If None, retry logic is disabled.
    """

    def graceful_shutdown(signum: int, frame: object) -> None:
        """
        Handle incoming signals to perform a graceful shutdown.

        When a termination signal is received (e.g., SIGINT or SIGTERM), this function
        sets the 'alive' event in the QueueManager to initiate a controlled shutdown
        process, allowing tasks to complete cleanly.

        Args:
            signum (int): The signal number received.
            frame (object): The current stack frame (unused).
        """
        print(f"Received signal {signum}, shutting down...")
        qm.alive.set()

    # Setup signal handlers for graceful shutdown of the QueueManager.
    signal.signal(signal.SIGINT, graceful_shutdown)  # Handle Ctrl-C
    signal.signal(signal.SIGTERM, graceful_shutdown)  # Handle termination request

    # Start the QueueManager's operation
    await qm.run(
        dequeue_timeout=dequeue_timeout,
        batch_size=batch_size,
        retry_timer=retry_timer,
    )

    def log_unhandled_exception(f: Future) -> None:
        if e := f.exception():
            logconfig.logger.critical(
                "Unhandled exception: worker shutdown!",
                exc_info=e,
            )

    futures = set[Future]()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for wid in range(workers):
            f = pool.submit(
                _runit,
                factory_fn,
                dequeue_timeout,
                batch_size,
                retry_timer,
                wid,
            )
            f.add_done_callback(log_unhandled_exception)
            futures.add(f)
