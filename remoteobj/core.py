import time
import random
import collections
import threading
import traceback
import warnings
import multiprocessing as mp
from .view import View


__all__ = ['Proxy']


def make_token(name):
    return '|(((( {} {} ))))|'.format(__name__.rsplit('.', 1)[0], name)

Result = collections.namedtuple('Result', 'result exception')


FAIL_UNPICKLEABLE = False
SELF = make_token('self')
UNDEFINED = make_token('undefined')

UNPICKLEABLE_WARNING = (
    "You tried to send an unpickleable object returned by {view} "
    "via a pipe. We'll assume this was an oversight and "
    "will return `None`. The remote caller interface "
    "is meant more for remote operations rather than "
    "passing objects. Check the return value for any "
    "unpickleable objects. "
    "The return value: {result}"
)


# https://github.com/python/cpython/blob/5acc1b5f0b62eef3258e4bc31eba3b9c659108c9/Lib/concurrent/futures/process.py#L127
class _RemoteTraceback(Exception):
    def __init__(self, tb):
        self.tb = tb
    def __str__(self):
        return self.tb

class _RemoteException:
    def __init__(self, exc):
        self.exc = exc
        self.tb = '\n"""\n{}"""'.format(''.join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ))
    def __reduce__(self):
        return _rebuild_exc, (self.exc, self.tb)

def _rebuild_exc(exc, tb):
    exc.__cause__ = _RemoteTraceback(tb)
    return exc


class Proxy(View):
    '''Capture and apply operations to a remote object.

    Usage:


    '''
    _thread = None
    _delay = 1e-5
    _listener_process_name = None
    NOCOPY = ['_local', '_remote', '_llock', '_rlock']
    def __init__(self, instance, *a, default=UNDEFINED, eager_proxy=True, **kw):
        super().__init__(*a, **kw)
        self._obj = instance

        # cross-process objects
        self._llock, self._rlock = mp.Lock(), mp.Lock()
        self._local, self._remote = mp.Pipe()

        self._listening_val = mp.Value('i', 0, lock=False)
        self._default = default
        self._eager_proxy = eager_proxy
        self._root = self  # isn't called when extending

    def __str__(self):
        return '<Remote {} : {}>'.format(self._obj, super().__str__())

    def __getstate__(self):
        # NOTE: So we don't pickle queues, locks, and shared values.
        return dict(self.__dict__, _thread=None, _listening=False, **{k: None for k in self.NOCOPY})

    # remote calling interface

    def process_requests(self):
        '''Poll until the command queue is empty.'''
        while self._remote.poll():
            self.poll()
            time.sleep(self._delay)

    def poll(self):
        '''Check for and execute the next command in the queue, if available.'''
        if self._remote.poll():
            with self._rlock:
                view = self._remote.recv()
                view = View(*view)

                try:
                    result = view.resolve_view(self._obj)
                except BaseException as e:
                    self._remote.send((None, _RemoteException(e)))
                    return

                # result came out fine

                if result is self._obj:  # solution for chaining
                    result = SELF
                try:
                    self._remote.send((result, None))
                except RuntimeError as e:
                    # handle exception that happens during serialization
                    if FAIL_UNPICKLEABLE:
                        raise RuntimeError(
                            'Return value of {} is unpickleable.'.format(view)) from e
                    warnings.warn(UNPICKLEABLE_WARNING.format(view=view, result=result))
                    self._remote.send((result, None))

    # parent calling interface

    def get_(self, default=UNDEFINED):
        if self._local_listener:  # if you're in the remote thread, just run the function.
            return self.resolve_view(self._obj)
        with self._llock:
            if self._listening:  # if the remote process is listening, run
                # send and wait for a result
                self._local.send(self._keys)
                x, exc = self._local.recv()
                if x == SELF:
                    x = self._root  # root remote object without any ops
                if exc is not None:
                    raise exc
                return x

        # if a default value is provided, then return that, otherwise return a default.
        default = self._default if default == UNDEFINED else default
        if default == UNDEFINED:
            raise RuntimeError('Remote instance is not running for {}'.format(self))
        return default

    @property
    def __(self):
        '''Get value from remote object. Alias for self.get_()'''
        return self.get_()


    @property
    def _local_listener(self):
        '''Is the current process the main process or a child one?'''
        return mp.current_process().name == self._listener_process_name

    # internal view mechanics. These override RemoteView methods.

    def _extend(self, *keys, **kw):
        # Create a new remote proxy object while **bypassing RemoteProxy.__init__**
        # Basically, we don't want to recreate pipes, locks, etc.
        obj = self.__class__.__new__(self.__class__)
        obj.__dict__.update(self.__dict__)
        View.__init__(obj, *self._keys, *keys, **kw)
        return obj

    def __call__(self, *a, _default=..., _proxy=None, **kw):
        '''Automatically retrieve when calling a function.'''
        val = super().__call__(*a, **kw)
        if (self._eager_proxy if _proxy is None else _proxy):
            val = val.get_(default=_default)
        return val

    def __setattr__(self, name, value):
        '''Support setting attributes on remote objects. This makes me uncomfy lol.'''
        if (name.startswith('_') or name in self.__dict__ or
                name in self.__class__.__dict__):
            return super().__setattr__(name, value)
        self._setattr(name, value).get_()

    def __setitem__(self, name, value):
        '''Set item on remote object.'''
        self._setitem(name, value).get_()

    def passto(self, func, *a, _default=None, _proxy=None, **kw):
        val = super().passto(func, *a, **kw)
        if (self._eager_proxy if _proxy is None else _proxy):
            val = val.get_(default=_default)
        return val


    # running state - to avoid dead locks, let the other process know if you will respond

    @property
    def _listening(self):
        '''Is the remote instance listening?'''
        return bool(self._listening_val.value)

    @_listening.setter
    def _listening(self, value):
        with self._llock:
            self._listening_val.value = int(value)
        self._listener_process_name = mp.current_process().name if value else None

    # remote background listening interface
    '''

    do (clean, easy, runs in background)
    >>> with self.remote.background_listen():  # automatic
    ...     ...  # don't have to poll

    or (runs in background, manual cleanup)
    >>> self.remote.background_listen()  # automatic
    >>> ...  # don't have to poll
    >>> self.remote.background_stop()

    or (clean, easy, more control)
    >>> with self.remote:  # manual
    ...     while True:
    ...         self.remote.poll()  # need to poll, otherwise they'll hang

    or when you've got nothing else to do
    >>> self.remote.run_listener()

    '''

    def background_listen(self):
        '''Start listening. By default, this will launch in a background thread.'''
        if self._thread is None:
            self._thread = threading.Thread(target=self.run_listener, daemon=True)
            self._thread.start()
        return self

    def background_stop(self):
        self._listening = False
        if self._thread is not None:
            self._thread.join()
        self._thread = None
        return self

    def run_listener(self):
        try:
            self._listening = True
            while self._listening:
                self.process_messages()
                time.sleep(self._delay)
        finally:
            self._listening = False
            self.process_messages()


    def wait_until_listening(self):
        while not self._listening:
            time.sleep(self._delay)

    def __enter__(self):
        self._listening = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.background_stop()
        self._listening = False
