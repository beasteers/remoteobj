import time
import functools
from contextlib import contextmanager
import threading
import multiprocessing as mp
import remoteobj



class _BackgroundMixin:
    _EXC_CLASS = remoteobj.Except
    def __init__(self, func, *a, results_=True, timeout_=None, raises_=True,
                 name_=None, group_=None, daemon_=True, **kw):
        self.exc = self._EXC_CLASS()
        self.join_timeout = timeout_
        self.join_raises = raises_

        super().__init__(
            target=self.exc.wrap(func, result=results_),
            args=a, kwargs=kw, name=name_,
            group=group_, daemon=daemon_)


    def start(self):
        super().start()
        return self

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.join()

    def join(self, timeout=None, raises=None):
        super().join(self.join_timeout if timeout is None else timeout)
        self.exc.pull()
        if (self.join_raises if raises is None else raises):
            self.exc.raise_any()

    def raise_any(self):
        self.exc.raise_any()

    @property
    def result(self):
        return self.exc.get_result()


class process(_BackgroundMixin, mp.Process):
    '''multiprocessing.Process, but easier and more Pythonic.

    What this provides:
     - has a cleaner signature - `process(func, *a, **kw)`
     - can be used as a context manager `with process(...):`
     - pulls the process name from the function name by default
     - defaults to `daemon=True`
     - will raise the remote exception (using `remoteobj.Except()`)

     Arguments:
        func (callable): the process target function.
        *args: the positional args to pass to `func`
        results_ (bool): whether to pickle the return/yield values and send them
            back to the main process.
        timeout_ (float or None): how long to wait while joining?
        raises_ (bool): Whether or not to raise remote exceptions after joining.
            Default is True.
        name_ (str): the process name. If None, the process name will use the
            target function's name.
        group_ (str): the process group name.
        daemon_ (bool): whether or not the process should be killed automatically
            when the main process exits. Default True.
        **kwargs: the keyword args to pass to `func`
    '''
    def __init__(self, func, *a, name_=None, **kw):
        super().__init__(func, *a, name_=name_, **kw)
        # set a default name - _identity is set in __init__ so we have to
        # run it after
        if not name_:
            self._name = '-'.join([
                getattr(func, '__name__', None) or self.__class__.__name__,
                'process', ':'.join(str(i) for i in self._identity)])



class thread(_BackgroundMixin, threading.Thread):
    _EXC_CLASS = remoteobj.LocalExcept
    def __init__(self, func, *a, name_=None, **kw):
        super().__init__(func, *a, name_=name_, **kw)
        # set a default name
        if not name_:
            self._name = '-'.join([
                getattr(func, '__name__', None) or self.__class__.__name__,
                'thread', ':'.join(str(i) for i in self._name.split('-')[1:])])


def job(*a, threaded_=True, **kw):
    return (thread if threaded_ else process)(*a, **kw)

# Helpers for tests and what not


@contextmanager
def listener(obj, bg=None, wait=True, callback=None, **kw):
    if bg is None:
        bg = callable(callback)
    func = (
        bg if callable(bg) else
        _run_remote_bg if bg else
        _run_remote)
    event = mp.Event()
    with process(func, obj, event, callback=callback, **kw) as p:
        try:
            if wait:
                obj.remote.wait_until_listening()
            yield p
        finally:
            event.set()

dummy_listener = listener

def listener_func(func):
    '''Wrap a function that get's called repeatedly in a remote process with
    remote object listening. Use as a contextmanager.
    '''
    @functools.wraps(func)
    def inner(obj, *a, **kw):
        return listener(obj, *a, callback=func, **kw)
    return inner


def _run_remote(obj, event, callback=None, delay=1e-5):  # some remote job
    with obj.remote:
        while not event.is_set():
            obj.remote.poll()
            callback and callback(obj)
            time.sleep(delay)

def _run_remote_bg(obj, event, callback=None, delay=1e-5):  # some remote job
    with obj.remote.listen_(bg=True):
        while not event.is_set() and obj.remote.listening_:
            callback and callback(obj)
            time.sleep(delay)
