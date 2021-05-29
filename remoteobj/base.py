import time
import ctypes
# import signal
import warnings
import multiprocessing as mp
from .excs import RemoteException
from . import util


def make_token(name):
    '''Generate a sentinel token. Used in places where `None` may be a valid input.'''
    return '|{}.{}|'.format(__name__.rsplit('.', 1)[0], name)


FAIL_UNPICKLEABLE = False
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


class BaseListener:
    _thread = None
    _delay = 1e-5
    _listener_proc = None
    # _listener_process_name = None
    _NOCOPY = ['_local', '_remote', '_llock', '_rlock', '_listener_ident']  # , '_listening_val'
    def __init__(self, fulfill_final=True, default=UNDEFINED, __new=True, **kw):
        # cross-process objects
        # self._listening_val = mp.Value('i', 0, lock=False)
        self._listener_ident = mp.Value('i', 0, lock=False)
        self._llock, self._rlock = mp.Lock(), mp.Lock()
        self._local, self._remote = mp.Pipe()
        self._root = self  # isn't called when extending
        self._fulfill_final = fulfill_final
        self._default = default

        # orig_handler = signal.getsignal(signal.SIGSEGV)
        # def sig_handler(signum, frame):
        #     self._listener_ident.value = 0
        #     orig_handler(signum, frame)
        # signal.signal(signal.SIGSEGV, sig_handler)
        super().__init__(**kw)

    def __getstate__(self):
        # NOTE: So we don't pickle queues, locks, and shared values.
        return dict(self.__dict__, _thread=None, **{k: None for k in self._NOCOPY})

    # core inner workings

    def _process(self, data):
        '''process a request and return the result'''
        return data

    def _form_result(self, result):
        return result

    def _parse_response(self, x):
        x, exc = x
        if exc is not None:
            raise exc
        return x

    def _handle_no_listener(self, default=UNDEFINED):
        # if a default value is provided, then return that, otherwise return a default.
        default = self._default if default == UNDEFINED else default
        if default == UNDEFINED:
            raise RuntimeError('Remote instance is not running for {}'.format(self))
        elif callable(default):
            default = default()
        return default

    # remote calling interface

    def process_requests(self):
        '''Poll until the command queue is empty.'''
        n = 0
        while self._remote.poll():
            self.poll()
            time.sleep(self._delay)
            n += 1
        return n

    def cancel_requests(self):
        n = 0
        while self._remote.poll():
            _ = self._remote.recv()
            self._remote.send(None)
            time.sleep(self._delay)
            n += 1
        return n

    def poll(self, wait=False):
        '''Check for and execute the next command in the queue, if available.'''
        if self._remote.poll():
            with self._rlock:
                request = self._remote.recv()
                try:
                    result = self._form_result(self._process(request))
                except BaseException as e:
                    self._remote.send((None, RemoteException(e)))
                    return

                # result came out fine
                try:
                    self._remote.send((result, None))
                except RuntimeError as e:
                    # handle exception that happens during serialization
                    if FAIL_UNPICKLEABLE:
                        raise RuntimeError(
                            'Return value of {} is unpickleable.'.format(request)) from e
                    warnings.warn(UNPICKLEABLE_WARNING.format(view=request, result=result))
                    self._remote.send((None, None))
            return True
        return False

    # parent calling interface

    def _evaluate(self, request, default=UNDEFINED, default_local=False):
        '''Request the remote object to evaluate the proxy and return the value.
        If you are in the same process as the remote object, it will evaluate
        directly.

        Args:
            default (any): the value to return if the remote instance isn't listening.
        '''
        if self._local_listener:  # if you're in the remote process, just run the function.
            return self._process(request)
        if self.listening_:  # there's no way to disable a lock, so we need to check twice in order to avoid race conditions on closing
            with self._llock:
                if self.listening_:  # if the remote process is listening, run
                    # send and wait for a result
                    self._local.send(request)
                    x = self._local.recv()
                    if x is not None:
                        return self._parse_response(x)

        if default_local:
            return self._process(request)
        return self._handle_no_listener(default=default)

    @property
    def _local_listener(self):
        '''Is the current process the main process or a child one?'''
        p = mp.current_process()
        try:  # XXX: should I be worried about this changing?
            current_ident = getattr(p, '_cached_ident')
        except AttributeError:
            current_ident = p._cached_ident = p.ident
        return current_ident == self._listener_ident.value

    # running state - to avoid dead locks, let the other process know if you will respond
    @property
    def listening_(self):
        '''Is the remote instance listening?'''
        ident = self._listener_ident.value
        return ident > 0
        # if ident <= 0:
        #     return False
        # if self._listener_proc is None:
        #     # util.mprint(type(ident), [type(p.ident) for p in mp.active_children()])
        #     try:
        #         self._listener_proc = next((p for p in mp.active_children() if p.ident == ident))
        #     except StopIteration:
        #         pass
        # return bool(self._listener_proc is not None and self._listener_proc.is_alive())
        # # return bool(self._listening_val.value)

    @listening_.setter
    def listening_(self, value):
        # set first so no one else can
        prev = self._listener_ident.value > 0
        if value:
            self._listener_proc = p = mp.current_process()
            self._listener_ident.value = p.ident
        else:
            self._listener_proc = None
            self._listener_ident.value = 0

            # make sure no one is left waiting.
            if prev:
                # there's a slight race condition between checking if we're still listening and sending the request
                while is_locked(self._llock):
                    if self._fulfill_final:
                        self.process_requests()
                    else:
                        self.cancel_requests()

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

    def listen_(self, bg=False):
        '''Start a background thread to handle requests.'''
        if not bg:
            self.listening_ = True
            return self

        if self._thread is None:
            self._thread = util.thread(self._run_listener, raises_=False).start()
        return self

    def stop_listen_(self):
        '''Set listening to False. If a thread is running, close it.'''
        self.listening_ = False
        if self._thread is not None:
            self._thread.join()
            self._thread = None
        return self

    def _run_listener(self):
        '''Run the listener loop. This is what is run in the thread.'''
        try:
            self.listening_ = True
            while self.listening_:
                self.process_requests()
                time.sleep(self._delay)
        finally:
            self.listening_ = False

    def wait_until_listening(self, proc=None, fail=True, timeout=None):
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
        t0 = time.time()
        while not self.listening_:
            if proc is not None and not proc.is_alive():
                if fail:
                    raise RuntimeError('Process is dead and the proxy never started listening.')
                return False
            time.sleep(self._delay)
            if timeout and time.time() - t0 >= timeout:
                raise TimeoutError('Remote listener never started listening.')
        return True

    def __enter__(self):
        self.listening_ = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop_listen_()


def is_locked(lock):
    locked = lock.acquire(block=False)
    if locked:
        lock.release()
    return not locked
