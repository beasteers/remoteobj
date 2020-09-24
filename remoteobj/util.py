import time
import ctypes
import pickle
import functools
from contextlib import contextmanager
import multiprocessing as mp



class AnyValue:
    '''Pass arbitrary values by pickling. Because of FIFO, it's inefficient to
    send big objects, especially if this value is being read across many processes.
    This is meant more for Exceptions and things like that.'''
    def __init__(self, initval=None):
        self._value = initval
        self._count = 0
        self._q = mp.SimpleQueue()
        self._q.put(self._value)
        self._qcount = mp.Value('i', self._count)

    @property
    def value(self):
        if self._count != self._qcount.value:
            self._value = self._q.get()
            self._count = self._qcount.value
            self._q.put(self._value)  # replace value
        return self._value

    @value.setter
    def value(self, value):
        while not self._q.empty():
            self._q.get()
        self._q.put(value)
        self._qcount.value += 1


class AnyValueProp(AnyValue):
    '''An alternative interface for AnyValue that uses class descriptors.'''
    def __init__(self, name=None):
        if not name:
            name = '_{}{}'.format(self.__class__.__name__, id(self))
        self.name = '_{}'.format(name) if not name.startswith('_') else name

    def __get__(self, instance, owner=None):
        return self._get(instance).value

    def __set__(self, instance, value):
        self._get(instance).value = value

    def _get(self, instance):
        try:
            value = getattr(instance, self.name)
        except KeyError:
            value = AnyValue()
            setattr(instance, self.name, value)
        return value


# Helpers for tests and what not


def _run_remote(obj, event, callback=None, init=None, cleanup=None, delay=1e-5):  # some remote job
    with obj.remote:
        it = range(10)
        init and init(obj)
        while not event.is_set():
            for _ in it:
                obj.remote.poll()
                callback and callback(obj)
                time.sleep(delay)
        cleanup and cleanup(obj)

def _run_remote_bg(obj, event, callback=None, delay=1e-5):  # some remote job
    with obj.remote.background_listen():
        while not event.is_set():
            callback and callback(obj)
            time.sleep(delay)


@contextmanager
def _remote_listener(obj, func, *a, wait=True, **kw):
    event = mp.Event()
    p = mp.Process(target=func, args=(obj, event,) + a, kwargs=kw, daemon=True)
    p.start()
    if wait:
        obj.remote.wait_until_listening()
    yield p
    event.set()
    p.join()


def dummy_listener(obj, bg=False, **kw):
    '''Start a background process with obj.remote listening.'''
    return _remote_listener(obj, bg if callable(bg) else _run_remote_bg if bg else _run_remote, **kw)


def listener_func(func):
    '''Wrap a function that get's called repeatedly in a remote process with
    remote object listening. Use as a contextmanager.
    '''
    @functools.wraps(func)
    def inner(obj, *a, **kw):
        return dummy_listener(obj, *a, callback=func, **kw)
    return inner




def _run_remote_func(callback, event, count, *a, delay=1e-5, **kw):
    while not event.is_set():
        if callback(*a, **kw) is False:
            return
        time.sleep(delay)
        count.value += 1

@contextmanager
def _remote_proc(func, callback, *a, **kw):
    count = mp.Value('i', 0)
    event = mp.Event()
    p = mp.Process(target=func, args=(callback, event, count) + a, kwargs=kw, daemon=True)
    p.start()
    yield p, count
    event.set()
    p.join()

def remote_func(callback, *a, **kw):
    '''Run a function repeatedly in a separate process.'''
    return _remote_proc(_run_remote_func, callback, *a, **kw)

@contextmanager
def process(func, *a, **kw):
    '''Run func in a separate process.'''
    p = mp.Process(target=func, args=a, kwargs=kw, daemon=True)
    p.start()
    yield p
    p.join()
