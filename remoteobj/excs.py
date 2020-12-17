import time
import collections
import functools
import traceback
import multiprocessing as mp
import logging

log_ = log = logging.getLogger(__name__)


__all__ = ['Except', 'LocalExcept', 'RemoteException']


# https://github.com/python/cpython/blob/5acc1b5f0b62eef3258e4bc31eba3b9c659108c9/Lib/concurrent/futures/process.py#L127
class _RemoteTraceback(Exception):
    def __init__(self, tb):
        self.tb = tb
    def __str__(self):
        return self.tb

class RemoteException:
    '''A wrapper for exceptions that will preserve their tracebacks
    when pickling. Once unpickled, you will have the original exception
    with __cause__ set to the formatted traceback.'''
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


RETURN, YIELD, YIELDRETURN = '__return__', '__yield__', '__yield_return__'
RESULT_KEYS = RETURN, YIELD, YIELDRETURN


# class PipeQueue(mp.Pipe):
#     def empty(self):
#         return not self.poll()
#
#     def put(self, X):
#         return self.send(X)
#
#     def get(self, X):
#         return self.recv(X)


class LocalExcept:
    '''Catch exceptions and store them in groups.

    Args:
        *types: Specific exceptions you want to catch. Defaults to `Exception`.
        raises (bool): If True, the object is taking a bookkeeping role and tracking
            where exceptions are raised, but will allow the original try, finally
            flow to take place. If False, it will swallow the exception.
        catch_once (bool): If True, when context managers are nested, the exception
            will only be recorded by the first (inner-most) context and higher contexts
            will ignore that exception. If False, every context up the chain
            will record the exception.
    '''
    first = last = None
    _result = None
    _is_yield = _is_yielding = False
    def __init__(self, *types, raises=True, catch_once=True, log=False, log_tb=False):
        self.types = types or (Exception,)
        self.raises = raises
        self.catch_once = catch_once
        if log is True:
            log = log_
        self.log, self.log_tb = log, log_tb
        self._groups = {}

    def __str__(self):
        return '<{} raises={} types={} {}{}>'.format(
            self.__class__.__name__, self.raises, self.types,
            'result=None' if self._result is None else
            'yield' if self._is_yield else
            'result type={}'.format(type(self._result)),
            ''.join(
                '\n {:>15} [{} raised]{}'.format(
                    '*default*' if name is None else name, len(excs),
                    (' - last: ({}: {!r})'.format(type(excs[-1]).__name__, str(excs[-1]))
                     if excs else '')
                )
                for name, excs in self._groups.items()
            ) or ' - No exceptions raised.'
        )

    def __call__(self, name=None, raises=None, types=None, catch_once=None, log=None, log_tb=None):
        return _ExceptContext(
            self, name,
            self.raises if raises is None else raises,
            self.types if types is None else types,
            catch_once=self.catch_once if catch_once is None else catch_once,
            log=self.log if log else None,
            log_tb=self.log_tb if log_tb is None else log_tb)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self().__exit__(exc_type, exc_val, exc_tb)

    def __getitem__(self, key):
        return self.group(key)

    def __nonzero__(self):
        return len(self.all())

    def __iter__(self):
        return iter(self.all())

    def set(self, exc, name=None, mark=True):
        '''Assign an exception to a group. Also handles the special cases
        of return and yield values.'''
        if name == RETURN:
            self._result = exc
            return
        if name == YIELD:
            if self._result is None:
                self._result = collections.deque()
                self._is_yield = self._is_yielding = True
            self._result.append(exc)
            return
        if name == YIELDRETURN:
            self._is_yield = True
            self._is_yielding = False
            return

        # handle exceptions and grouping
        if getattr(exc, '__remoteobj_caught__', name) != name:
            return
        if name not in self._groups:
            self._groups[name] = []
        self._groups[name].append(exc)
        if self.first is None:
            self.first = exc
        self.last = exc
        if mark:
            self._mark(exc, name)

    def _mark(self, exc, name=None):
        exc.__remoteobj_caught__ = name

    def get(self, name=None, latest=True):
        '''Get the last exception in the specified group, `name`.'''
        if name == ...:
            return self.last
        excs = self.group(name)
        return excs[-1 if latest else 0] if excs else None

    def group(self, name=None):
        '''Get all exceptions in a group, `name`.'''
        return self._groups.get(name) or []

    def raise_any(self, name=..., latest=True):
        '''Raise any exceptions that were collected. By default it will
        raise any exception. If `name` is provided, only exceptions from
        that group will be raised.
        '''
        exc = self.get(name, latest=latest)
        if exc is not None:
            raise exc

    def log_tracebacks(self, name=..., logger=log, all=True, latest=True):
        for e in self.all() if all else [self.get(name, latest=latest)]:
            logger.exception(e)

    def log_error(self, name=..., logger=log, all=True, latest=True):
        for e in self.all() if all else [self.get(name, latest=latest)]:
            logger.error('(%s) %s', e.__class__.__name__, e)

    def all(self):
        '''Get all exceptions (from all groups) as a list.'''
        return [e for es in self._groups.values() for e in es]

    def clear(self):
        '''Clear all exceptions and groups collected so far.'''
        self._groups.clear()
        self.first = self.last = None
        self._result = None
        self._is_yield = self._is_yielding = False

    def pull(self):
        pass  # noop

    def wrap(self, func, result=True):
        '''Wrap a function to catch any exceptions raised. To re-raise the
        exception, run self.raise_any(). By default, it will also capture the
        return and yield values.'''
        return functools.wraps(func)(
            functools.partial(self._func_wrapper, func, result=result))

    def _func_wrapper(self, func, *a, result=True, **kw):
        with self(raises=False):
            x = func(*a, **kw)
            if result:
                self.set_result(x)
            return x

    def set_result(self, x):
        '''Set a function's result.'''
        if hasattr(x,'__iter__') and not hasattr(x,'__len__'):
            try:
                for xi in x:
                    self.set(xi, YIELD)
            finally:
                self.set(None, YIELDRETURN)
        else:
            self.set(x, RETURN)

    def get_result(self, delay=1e-6):
        '''Retrieve a function's result.'''
        if self._is_yield:
            def results():
                while True:
                    if len(self._result):
                        yield self._result.popleft()
                    elif not self._is_yielding:
                        return
                    time.sleep(delay)
            return results()
        return self._result

    def clear_result(self):
        self._result = collections.deque() if self._is_yield else None

    def pop_result(self):
        result = self.get_result()
        self.clear_result()
        return result


# def blah(obj):
#     look = {}
#     def __init__(self, *a, **kw):
#         look[id(self)] = self
#         super().__init__(*a, **kw)
#     def __getstate__(self):
#         return dict(_id=id(self))
#     def __setstate__(self, state):
#         self.__dict__ = look[state['_id']].__dict__
#
#     obj.__class__ = type(obj.__class__.__name__, (obj.__class__,), {
#         '__lookup': look, '__getstate__': __getstate__, '__setstate__': __setstate__
#     })

class Except(LocalExcept):
    '''Catch exceptions in a remote process with their traceback and send them
    back to be raised properly in the main process.'''
    __Qs = {}
    def __init__(self, *types, store_remote=True, **kw):
        # self._local, self._remote = mp.Pipe()
        self._q = mp.Queue()
        self._q_id = id(self._q)
        self.__Qs[self._q_id] = self._q
        self._store_remote = store_remote
        # self._local_name = mp.current_process().name
        super().__init__(*types, **kw)

    ### these methods are to prevent queues from being pickled

    def __getstate__(self):
        return dict(self.__dict__, _q=None)

    def __setstate__(self, state):
        self.__dict__ = state
        self._q = self.__Qs[self._q_id]

    def __del__(self):
        self.__Qs.pop(self._q_id, None)

    #########

    def __str__(self):
        self.pull()
        return super().__str__()

    def get(self, name=None, *a, **kw):
        self.pull()
        return super().get(name, *a, **kw)

    def group(self, name=None):
        self.pull()
        return super().group(name)

    def all(self):
        self.pull()
        return super().all()

    def set(self, exc, name=None, mark=True): #, store=None
        r_exc = RemoteException(exc) if isinstance(exc, BaseException) else exc
        self._q.put((r_exc, name))
        # self._remote.send((r_exc, name))
        # set exceptions on this side just in case
        if self._store_remote:
            super().set(exc, name, mark=mark)
        elif mark and name not in RESULT_KEYS:
            self._mark(exc, name)

    def get_result(self, **kw):
        self.pull()
        return super().get_result(**kw)

    def pull(self):
        '''Pull any exceptions through the pipe. Used internally.'''
        try:
            while not self._q.empty():
                x = self._q.get(block=False)
            # while self._local.poll():
                # exc, name = self._local.recv()
                if x:
                    super().set(*x)
        except (EOFError, FileNotFoundError, ConnectionRefusedError) as e:
            log.exception(e)

    def raise_any(self, name=...):
        self.pull()
        return super().raise_any(name)

    def log_tracebacks(self, name=..., *a, **kw):
        self.pull()
        return super().log_tracebacks(name, *a, **kw)

    def log_error(self, name=..., *a, **kw):
        self.pull()
        return super().log_error(name, *a, **kw)


class _ExceptContext:
    def __init__(self, catch, name=None, raises=False, types=(), catch_once=True, log=False, log_tb=False):
        self.catch = catch
        self.name = name
        self.raises = raises or not catch_once
        self.types = types
        self.catch_once = catch_once
        self.log = log
        self.log_tb = log_tb

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val is not None and isinstance(exc_val, self.types):
            self.catch.set(exc_val, self.name, self.catch_once)
            if self.log:
                if self.log_tb:
                    self.log.exception(exc_val)
                else:
                    self.log.error('({}) {}'.format(exc_type, exc_val))
            return not self.raises
