import time
import collections
import threading
import warnings
import multiprocessing as mp
from .view import View
from .excs import RemoteException


__all__ = ['get', 'Proxy']


def get(view, **kw):
    '''Resolve a Proxy object and get its return value.'''
    return view.get_(**kw)


def make_token(name):
    '''Generate a sentinel token. Used in places where `None` may be a valid input.'''
    return '|{}.{}|'.format(__name__.rsplit('.', 1)[0], name)

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


class Proxy(View):
    '''Capture and apply operations to a remote object.

    Args:
        instance (any): the object that you want to proxy.
        default (any): the default value to return if no remote listener is
            running and if the proxy call doesn't specify its own default.
            If omitted, it will raise a RuntimeError (default). This is most likely
            the expected behavior in a general sense so if you want default
            values, it is recommended that you override them on a per-call
            basis.
        eager_proxy (bool): whether certain ops should evaluate automatically.
            These include: __call__, and passto. Default True.
        fulfill_final (bool): If when closing the remote listener, there are pending
            requests, should the remote listener fulfill the requests or should it
            cancel them. By default, it will fulfill them, but if there are problems
            with that, you can disable that.

    Usage:
    >>> proxy = Proxy(list)
    >>> # send to remote process ...
    >>> proxy.append(5)
    >>> assert proxy.passto(len) == 1  # len(proxy)
    >>> assert proxy[0].get_() == 5    # proxy[0]
    >>> proxy[0] = 6
    >>> assert proxy[0].__ == 6        # proxy[0] - same as get_()
    >>> proxy.another = []
    >>> assert isinstance(proxy.another, Proxy)
    >>> assert isinstance(proxy.append, Proxy)
    >>> assert isinstance(proxy.another.append, Proxy)
    >>> assert proxy.another.append(6) is None
    '''
    _thread = None
    _delay = 1e-5
    _listener_process_name = None
    _NOCOPY = ['_local', '_remote', '_llock', '_rlock', '_listening_val']
    def __init__(self, instance, default=UNDEFINED, eager_proxy=True, fulfill_final=True, **kw):
        super().__init__(**kw)
        self._obj = instance

        # cross-process objects
        self._listening_val = mp.Value('i', 0, lock=False)
        self._llock, self._rlock = mp.Lock(), mp.Lock()
        self._local, self._remote = mp.Pipe()

        self._default = default
        self._eager_proxy = eager_proxy
        self._fulfill_final = fulfill_final
        self._root = self  # isn't called when extending

    def __repr__(self):
        return '<Remote {} : {}>'.format(self._obj, super().__str__())

    def __str__(self):
        return self.__repr__()

    def __getstate__(self):
        # NOTE: So we don't pickle queues, locks, and shared values.
        return dict(self.__dict__, _thread=None, **{k: None for k in self.NOCOPY})

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
                    self._remote.send((None, RemoteException(e)))
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
                    self._remote.send((None, None))

    # parent calling interface

    def get_(self, default=UNDEFINED):
        '''Request the remote object to evaluate the proxy and return the value.
        If you are in the same process as the remote object, it will evaluate
        directly.

        Args:
            default (any): the value to return if the remote instance isn't listening.
        '''
        if self._local_listener:  # if you're in the remote process, just run the function.
            return self.resolve_view(self._obj)
        with self._llock:
            if self.listening_:  # if the remote process is listening, run
                # send and wait for a result
                self._local.send(self._keys)
                x = self._local.recv()
                if x is not None:
                    x, exc = x
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
        '''Get value from remote object. Alias for self.get_().'''
        return self.get_()

    @property
    def _local_listener(self):
        '''Is the current process the main process or a child one?'''
        return mp.current_process().name == self._listener_process_name

    # internal view mechanics. These override RemoteView methods.

    def _extend(self, *keys, **kw):
        # Create a new remote proxy object while **bypassing RemoteProxy.__init__**
        # Basically, we don't want to recreate pipes, locks, etc.
        if self._frozen:
            raise TypeError(f'{self} is frozen and is not extendable.')
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

    # attribute

    def _check_attr(self, name):
        '''Determine if an attribute is one we should override.'''
        return (name.startswith('_') or name in self.__dict__ or
                name in self.__class__.__dict__)

    def __setattr__(self, name, value):
        '''Support setting attributes on remote objects. This makes me uncomfy lol.'''
        if self._check_attr(name):
            return super().__setattr__(name, value)
        self._setattr(name, value).get_()

    def __delattr__(self, name):
        '''Support deleting attributes on remote objects. This makes me uncomfy too lol.'''
        if self._check_attr(name):
            return super().__delattr__(name)
        self._delattr(name).get_()

    # keys

    def __setitem__(self, name, value):
        '''Set item on remote object.'''
        self._setitem(name, value).get_()

    def __delitem__(self, name):
        '''Delete item on remote object.'''
        self._delitem(name).get_()

    # other

    def passto(self, func, *a, _default=None, _proxy=None, **kw):
        '''Pass the object to a function as the first argument.
        e.g. `obj.remote.passto(str) => len(str)`
        '''
        val = super().passto(func, *a, **kw)
        if (self._eager_proxy if _proxy is None else _proxy):
            val = val.get_(default=_default)
        return val

    def __contains__(self, key):
        return super().__contains__(key).get_()

    def __len__(self):
        return self._len().get_()

    # running state - to avoid dead locks, let the other process know if you will respond

    @property
    def listening_(self):
        '''Is the remote instance listening?'''
        return bool(self._listening_val.value)

    @listening_.setter
    def listening_(self, value):
        # set first so no one else can
        prev = self.listening_
        self._listening_val.value = int(value)
        self._listener_process_name = mp.current_process().name if value else None
        # make sure no one is left waiting.
        if prev and not value:
            if self._fulfill_final:
                self.process_requests()
            else:
                while self._remote.poll():
                    _ = self._remote.recv()
                    self._remote.send(None)  # cancel

    # remote background listening interface
    '''

    do (clean, easy, runs in background)
    >>> with self.remote.listen_(bg=True):  # automatic
    ...     ...  # don't have to poll

    or (runs in background, manual cleanup)
    >>> self.remote.listen_(bg=True)  # automatic
    >>> ...  # don't have to poll
    >>> self.remote.stop_listen_()

    or (clean, easy, more control)
    >>> with self.remote.listen_():  # manual
    ...     while True:
    ...         self.remote.poll()  # need to poll, otherwise they'll hang

    or when you've got nothing else to do
    >>> self.remote._run_listener()

    '''

    _thread_exception = None
    def listen_(self, bg=False):
        '''Start a background thread to handle requests.'''
        self._thread_exception = None
        if not bg:
            self.listening_ = True
            return self

        if self._thread is None:
            self._thread = threading.Thread(
                target=self._run_listener, kwargs={'_catch_exc': True}, daemon=True)
            self._thread.start()
        return self

    def stop_listen_(self):
        '''Set listening to False. If a thread is running, close it.'''
        self.listening_ = False
        if self._thread is not None:
            self._thread.join()
        self._thread = None
        if self._thread_exception is not None:
            raise self._thread_exception
        return self

    def _run_listener(self, _catch_exc=True):
        '''Run the listener loop. This is what is run in the thread.'''
        try:
            self.listening_ = True
            while self.listening_:
                self.process_requests()
                time.sleep(self._delay)
        except Exception as e:
            if not _catch_exc:
                raise
            self._thread_exception = e
        finally:
            self.listening_ = False

    def wait_until_listening(self, proc=None, fail=True):
        '''Wait until the remote instance is listening.

        Args:
            proc (mp.Process): If passed and the process dies, raise an error.
            fail (bool): Should it raise an exception if the process dies?
                Otherwise it would just return `False`.

        Returns:
            Whether the process is listening.

        Raises:
            `RuntimeError if fail == True and not proc.is_alive()`
        '''
        while not self.listening_:
            if proc is not None and not proc.is_alive():
                if fail:
                    raise RuntimeError('Process is dead and the proxy never started listening.')
                return False
            time.sleep(self._delay)
        return True

    def __enter__(self):
        self.listening_ = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_listen_()
