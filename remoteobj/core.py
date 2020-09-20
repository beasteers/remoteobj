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



class Proxy(View):
    '''Capture and apply operations to a remote object.

    Usage:


    '''
    _thread = None
    _delay = 0.1
    _poll_timeout = 1e-3
    def __init__(self, instance, *a, default=UNDEFINED, proxy_call=True, **kw):
        super().__init__(*a, **kw)
        self._obj = instance
        # cross-process objects
        self._manager = mp.Manager()
        self._requests = self._manager.Queue()
        self._results = self._manager.dict()

        self._local_name = mp.current_process().name
        self._listening = mp.Value('i', 0, lock=False)
        self._default = default
        self._proxy_call = proxy_call
        self._root = self  # isn't called when extending

    def __str__(self):
        return '<Remote {} : {}>'.format(self._obj, super().__str__())

    def __getstate__(self):
        '''Don't pickle queues, locks, and shared values.'''
        return dict(self.__dict__, _thread=None, _listening=False)

    @property
    def is_local(self):
        '''Is the current process the main process or a child one?'''
        return mp.current_process().name == self._local_name

    # internal view mechanics. These override RemoteView methods.

    def _extend(self, *keys, **kw):
        # Create a new remote proxy object. Don't call RemoteProxy.__init__
        obj = self.__class__.__new__(self.__class__)
        obj.__dict__.update(self.__dict__)
        View.__init__(obj, *self._keys, *keys, **kw)
        return obj

    def as_view(self, frozen=True):
        '''Convert to a view so we don't pickle the object instance, just the keys.'''
        return View(*self._keys, frozen=frozen)

    def __call__(self, *a, default=..., _proxy=None, **kw):
        '''Automatically retrieve when calling a function.'''
        val = super().__call__(*a, **kw)
        _proxy = self._proxy_call if _proxy is None else _proxy
        if _proxy:
            val = val.get_(default=default)
        return val

    def __setattr__(self, name, value):
        view = super().__setattr__(name, value)
        if view is not None:
            view.get_()

    def __setitem__(self, name, value):
        view = super().__setitem__(name, value)
        if view is not None:
            view.get_()

    # remote calling interface

    def process_requests(self):
        '''Poll until the command queue is empty.'''
        while self._remote.poll(self._poll_timeout):
            self.poll()

    def poll(self):
        '''Check for and execute the next command in the queue, if available.'''
        if not self._requests.empty():
            # get the called function
            result_id, view = self._requests.get()
            try:  # call the function and send the return value
                result = view.resolve_view(self._obj)
            except BaseException as e:  # send any exceptions
                print(
                    f'An exception was raised in {self}.',
                    traceback.format_exc(), flush=True)
                self._results[result_id] = None, e
            else:
                try:
                    if result is self._obj:  # solution for chaining
                        result = SELF
                    self._results[result_id] = result, None
                except RuntimeError as e:
                    if FAIL_UNPICKLEABLE:
                        warnings.warn(f'Return value of {view} is unpickleable.')
                        raise
                    warnings.warn(
                        f"You tried to send an unpickleable object returned by {view} "
                        "via a pipe. We'll assume this was an oversight and "
                        "will return `None`. The remote caller interface "
                        "is meant more for remote operations rather than "
                        "passing objects. Check the return value for any "
                        "unpickleable objects. "
                        f"The return value: {result}")
                    self._results[result_id] = None, None

    # parent calling interface

    def get_(self, default=UNDEFINED):
        if not self.is_local:  # if you're in the main thread, just run the function.
            return self.resolve_view(self._obj)
        if self.listening:  # if the remote process is listening, run
            # send command and wait for response
            result_id = random.randint(0, 10000000)
            view = self.as_view()

            self._requests.put((result_id, view))
            result = self._get_result(result_id)

            # if no result was returned, the queue was probably closed before
            # being able to execute the request.
            if result is not None:  # valid results are tuples
                # raise any exceptions returned
                x, exc = result
                if x == SELF:
                    x = self._root
                if exc is not None:
                    raise Exception('Remote exception in {}'.format(self)) from exc
                return x

        # if a default value is provided, then return that, otherwise return a default.
        default = self._default if default == UNDEFINED else default
        if default == UNDEFINED:
            raise RuntimeError('Remote instance is not running for {}'.format(self))
        return default

    def _get_result(self, result_id, wait=True, timeout=None):
        t0 = time.time()
        while self.listening:
            if result_id in self._results:
                return self._results.pop(result_id)

            if not wait:
                break
            if timeout is not None and time.time() - t0 > timeout:
                break
            time.sleep(self._delay)

    @property
    def __(self):
        return self.get_()

    ########################################################################
    # If we don't want to poll for commands in the background and we
    # want all commands to happen in the main thread, then we can remove
    # the methods below.
    ########################################################################

    # running state - to avoid dead locks, let the other process know if you will respond

    @property
    def listening(self):
        '''Is the remote instance listening?'''
        return bool(self._listening.value)

    # def set_listening(self, value):
    #     self._listening.value = int(value)

    @listening.setter
    def listening(self, value):
        self._listening.value = int(value)

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
    ...         self.poll()  # need to poll, otherwise they'll hang

    or (verbose, manual cleanup. just why..)
    >>> self.remote.listening = True  # manual
    ... while True:
    ...     self.poll()  # need to poll, otherwise they'll hang
    ... self.remote.listening = False

    '''

    def background_listen(self):
        '''Start listening. By default, this will launch in a background thread.'''
        if self._thread is None:
            self._thread = threading.Thread(target=self.run_listener, daemon=True)
            self._thread.start()
        return self

    def background_stop(self):
        self.listening = False
        if self._thread is not None:
            self._thread.join()
        self._thread = None
        return self

    def run_listener(self):
        self.listening = True
        while self.listening:
            self.process_messages()
            time.sleep(self._delay)
        self.listening = False
        time.sleep(0.1)
        self.process_messages()

    def wait_until_listening(self, timeout=None):
        t0 = time.time()
        while not self.listening:
            if timeout and time.time() - t0 > timeout:
                raise TimeoutError('Waiting for remote {} instance to listen timed out.'.format(self))
            time.sleep(self._delay)

    def __enter__(self):
        self.listening = True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.background_stop()
        self.listening = False
