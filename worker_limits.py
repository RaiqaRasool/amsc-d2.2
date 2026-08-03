import logging
import multiprocessing
import os
import signal
from queue import Empty


class OutputLimitExceeded(Exception):
    pass


class LimitedTextWriter:
    def __init__(self, output_file, maximum_bytes):
        self.output_file = output_file
        self.maximum_bytes = maximum_bytes
        self.bytes_written = 0

    def write(self, value):
        byte_count = len(value.encode(self.output_file.encoding or "utf-8"))
        if self.bytes_written + byte_count > self.maximum_bytes:
            raise OutputLimitExceeded
        written = self.output_file.write(value)
        self.bytes_written += byte_count
        return written

    def __getattr__(self, name):
        return getattr(self.output_file, name)


def _run_and_report(result_queue, ready, target, args):
    if hasattr(os, "setsid"):
        os.setsid()
    ready.set()
    try:
        result_queue.put(("complete", target(*args)))
    except OutputLimitExceeded:
        result_queue.put(("output_limit", None))
    except Exception:
        logging.exception("Background MYA execution failed.")
        result_queue.put(("failed", None))


def run_with_timeout(target, args, timeout_seconds):
    result_queue = multiprocessing.Queue(maxsize=1)
    ready = multiprocessing.Event()
    process = multiprocessing.Process(
        target=_run_and_report,
        args=(result_queue, ready, target, args),
    )
    process.start()
    ready.wait(timeout=1)
    process.join(timeout_seconds)

    if process.is_alive():
        if hasattr(os, "killpg") and ready.is_set():
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join()
        result = ("timeout", None)
    else:
        try:
            result = result_queue.get(timeout=1)
        except Empty:
            result = ("failed", None)

    process.close()
    result_queue.close()
    result_queue.join_thread()
    return result
