import time
from contextlib import contextmanager
import multiprocessing as mp



def _run_remote(obj, event, delay=1e-5):  # some remote job
    with obj.remote:
        it = range(10)
        while not event.is_set():
            for _ in it:
                obj.remote.poll()
                time.sleep(delay)

def _run_remote_bg(obj, event, delay=1e-5):  # some remote job
    with obj.remote.background_listen():
        while not event.is_set():
            time.sleep(delay)

@contextmanager
def _remote_listener(obj, func, delay=1e-5, wait=True):
    event = mp.Event()
    p = mp.Process(target=func, args=(obj, event, delay), daemon=True)
    p.start()
    if wait:
        obj.remote.wait_until_listening()
    yield
    event.set()
    p.join()


def dummy_listener(obj, bg=False, **kw):
    return _remote_listener(obj, _run_remote_bg if bg else _run_remote, **kw)
