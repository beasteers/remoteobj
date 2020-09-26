import time
import functools
from contextlib import contextmanager
import multiprocessing as mp
import remoteobj




class process(mp.Process):
    def __init__(self, func, *a, process_kw=None, **kw):
        self.exc = remoteobj.Except()
        process_kw = process_kw or {}
        process_kw.setdefault('daemon', True)
        super().__init__(
            target=self.exc.wrap(func),
            args=a, kwargs=kw, **process_kw)

        # set a default name - _identity is set in __init__ so we have to
        # run it after
        if 'name' not in process_kw:
            self._name = '{}-{}'.format(
                func.__name__, ':'.join(str(i) for i in self._identity))

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.join()

    def join(self, raises=True):
        super().join()
        if raises:
            self.exc.raise_any()



# Helpers for tests and what not



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


def _run_remote(obj, event, callback=None, init=None, cleanup=None, delay=1e-5):  # some remote job
    with obj.remote:
        it = range(10)
        init and init(obj)
        while not event.is_set():
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
def _remote_listener(obj, bg=True, wait=True, **kw):
    func = bg if callable(bg) else _run_remote_bg if bg else _run_remote
    event = mp.Event()
    with process(func, obj, event, **kw) as p:
        if wait:
            obj.remote.wait_until_listening()
        yield p
        event.set()




# Passing single values between processes




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
