import time
import ctypes
import functools
from contextlib import contextmanager
import threading
import multiprocessing as mp
import remoteobj



class _BackgroundMixin:
    _EXC_CLASS = remoteobj.Except
    _wait_for_return = False
    def __init__(self, func, *a, results_=True, timeout_=None, raises_=True,
                 name_=None, group_=None, daemon_=True, exc_=None, close_=None, **kw):
        self.exc = self._EXC_CLASS() if exc_ is None else exc_
        self.join_timeout = timeout_
        self.join_raises = raises_
        self._closer = close_
        if self._wait_for_return is not False:
            self._wait_for_return = mp.Event()

        super().__init__(
            target=self._wrap(func, result=results_),
            args=a, kwargs=kw, name=name_,
            group=group_, daemon=daemon_)

        # set a default name - _identity is set in __init__ so we have to
        # run it after
        if not name_:
            self._name = '-'.join((s for s in (
                getattr(func, '__name__', None),
                self.__class__.__name__,
                ':'.join(str(i) for i in self._identity)
            ) if s))


    def start(self):
        super().start()
        return self

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.join()

    _wait_timeout_interval = 0.1
    _min_partial_timeout = 0.3
    def join(self, timeout=None, raises=None):
        timeout = self.join_timeout if timeout is None else timeout

        # this lets someone pass a function that will, say, do self.closing.set()
        if callable(self._closer):
            self._closer()
        
        # for multiprocessing there is a scenario where we could experience a deadlock.
        # Basically, OS Pipes are not infinitely big - so if a queue item is larger than 
        # the Pipe limit, then there is a thread on the child process that will wait for 
        # the main process to call get() so it can feed the (too large) object through.
        # But if we call join without clearing the queue, then we'll just be forever waiting 
        # for each other.
        # So - this uses a multiprocessing event to 
        t0 = time.time()
        if self._wait_for_return:
            while self.is_alive() and (not timeout or (time.time() - t0) < timeout) and not self._wait_for_return.is_set():
                self._wait_for_return.wait(timeout=self._wait_timeout_interval)
            timeout = max(self._min_partial_timeout, timeout - (time.time() - t0)) if timeout else None

        self.exc.pull()
        super().join(timeout=timeout)
        self.exc.pull()

        if (self.join_raises if raises is None else raises):
            self.exc.raise_any()

    def raise_any(self):
        self.exc.raise_any()

    @property
    def result(self):
        return self.exc.get_result()

    def _wrap(self, func, *a, **kw):
        wrapped = self.exc.wrap(func, *a, **kw)
        @functools.wraps(func)
        def wrapped_wait(*a, **kw):
            try:
                return wrapped(*a, **kw)
            finally:
                if self._wait_for_return:
                    self._wait_for_return.set()
        return wrapped_wait



class process(_BackgroundMixin, mp.Process):
    '''multiprocessing.Process, but easier and more Pythonic.

    What this provides:
     - has a cleaner signature - `process(func, *a, join_timeout_=True, **kw)`
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
    _EXC_CLASS = remoteobj.Except
    _wait_for_return = True


class thread(_BackgroundMixin, threading.Thread):
    _EXC_CLASS = remoteobj.LocalExcept

    @property
    def _identity(self):
        return self._name.split('-')[1:]

    def throw(self, exc):
        raise_thread(exc, self)



def job(*a, threaded_=True, **kw):
    return (thread if threaded_ else process)(*a, **kw)

# Helpers for tests and what not

def mprint(*a, end='\n', **kw):
    '''A print statement that won't interleave with each other over multiprocessing.'''
    print(' '.join(map(str, a)) + (end or ''), end='', **kw)


def segfault(dumps=None):
    '''Create a segfault. This can happen sometimes with multiprocessing so this let's us 
    simulate it in a controlled environment and test out how we handle it.'''
    # https://gist.github.com/coolreader18/6dbe0be2ae2192e90e1a809f1624c694
    set_faulthandler(dumps)
    class E(BaseException):
        def __new__(cls, *a, **kw):
            return cls
    def a(): yield
    a().throw(E)

def set_faulthandler(dumps=None):  # TODO make context manager - but how to restore the previous enable() args?? (file&all_threads)
    if dumps is not None:
        import faulthandler
        if dumps:
            faulthandler.is_enabled() or faulthandler.enable()
        else:
            faulthandler.is_enabled() and faulthandler.disable()

# wrappers


@contextmanager
def listener(obj, bg=None, wait=True, callback=None, wait_timeout=10, join_timeout=10, **kw):
    if bg is None:
        bg = callable(callback)
    func = (
        bg if callable(bg) else
        _run_remote_bg if bg else
        _run_remote)
    event = mp.Event()
    with process(func, obj, event, callback=callback, timeout_=join_timeout, **kw) as p:
        try:
            if wait:
                obj.remote.wait_until_listening(p, timeout=wait_timeout)
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


def raise_thread(exc, name='MainThread'):
    '''Raise an exception on another thread.

    https://gist.github.com/liuw/2407154
    # ref: http://docs.python.org/c-api/init.html#PyThreadState_SetAsyncExc

    Apparently this doesn't work in some cases:
    | if the thread to kill is blocked at some I/O or sleep(very_long_time)
    Maybe we can retry it or something?
    '''
    tid = ctypes.c_long(find_thread(name, require=True).ident)
    ret = ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, ctypes.py_object(exc))
    if ret == 0:
        raise ValueError("Invalid thread ID")
    if ret > 1:  # Huh? we punch a hole into C level interpreter, so clean up the mess.
        ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, 0)  # null
        raise SystemError("Raising in remote thread failed.")


def find_thread(name, require=False):
    if isinstance(name, threading.Thread):
        return name
    try:
        return next((t for t in threading.enumerate() if t.name == name), None)
    except StopIteration:
        if require:
            raise ValueError("Couldn't find thread matching: {}".format(name)) from None
