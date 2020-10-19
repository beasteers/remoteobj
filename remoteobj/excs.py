import time
import collections
import functools
import traceback
import multiprocessing as mp

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
    def __init__(self, *types, raises=True, catch_once=True):
        self._local, self._remote = mp.Pipe()
        self.types = types or (Exception,)
        self.raises = raises
        self.catch_once = catch_once
        self._groups = {}

    def __str__(self):
        return '<{} raises={} types={}{}>'.format(
            self.__class__.__name__, self.raises, self.types,
            ''.join(
                '\n {:>15} [{} raised]{}'.format(
                    '*default*' if name is None else name, len(excs),
                    (' - last: ({}: {!r})'.format(type(excs[-1]).__name__, str(excs[-1]))
                     if excs else '')
                )
                for name, excs in self._groups.items()
            ) or ' - No exceptions raised.'
        )

    def __call__(self, name=None, raises=None, types=None, catch_once=None):
        return _ExceptContext(
            self, name,
            self.raises if raises is None else raises,
            self.types if types is None else types,
            self.catch_once if catch_once is None else catch_once)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self().__exit__(exc_type, exc_val, exc_tb)

    def __getitem__(self, key):
        return self.group(key)

    def set(self, exc, name=None, mark=True):
        '''Assign an exception to a group. Also handles the special cases
        of return and yield values.'''
        if name == '__return__':
            self._result = exc
            return
        if name == '__yield__':
            if self._result is None:
                self._result = collections.deque()
                self._is_yield = self._is_yielding = True
            self._result.append(exc)
            return
        if name == '__yield_stop__':
            self._is_yielding = False
            return

        # handle exceptions and grouping
        if name not in self._groups:
            self._groups[name] = []
        self._groups[name].append(exc)
        if self.first is None:
            self.first = exc
        self.last = exc
        if mark:
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

    def raise_any(self, name=...):
        '''Raise any exceptions that were collected. By default it will
        raise any exception. If `name` is provided, only exceptions from
        that group will be raised.
        '''
        exc = self.get(name)
        if exc is not None:
            raise exc

    def all(self):
        '''Get all exceptions (from all groups) as a list.'''
        return [e for es in self._groups.values() for e in es]

    def clear(self):
        '''Clear all exceptions and groups collected so far.'''
        self._groups.clear()
        self.first = self.last = None
        self._result = None
        self._is_yield = self._is_yielding = False

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
                    self.set(xi, '__yield__')
            finally:
                self.set(None, '__yield_stop__')
        else:
            self.set(x, '__return__')

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



class Except(LocalExcept):
    '''Catch exceptions in a remote process with their traceback and send them
    back to be raised properly in the main process.'''
    def __init__(self, *types, store_remote=True, **kw):
        self._local, self._remote = mp.Pipe()
        self._store_remote = store_remote
        super().__init__(*types, **kw)

    def __str__(self):
        self.pull()
        return super().__str__()

    def get(self, name=None):
        self.pull()
        return super().get(name)

    def group(self, name=None):
        self.pull()
        return super().group(name)

    def all(self):
        self.pull()
        return super().all()

    def set(self, exc, name=None, mark=True):
        self._remote.send((
            RemoteException(exc) if isinstance(exc, BaseException) else exc, name))
        # set exceptions on this side just in case
        if self._store_remote:
            super().set(exc, name, mark=mark)
        elif mark:
            exc.__remoteobj_caught__ = name

    def pull(self):
        '''Pull any exceptions through the pipe. Used internally.'''
        while self._local.poll():
            exc, name = self._local.recv()
            super().set(exc, name)

    def raise_any(self, name=...):
        self.pull()
        return super().raise_any(name)


class _ExceptContext:
    def __init__(self, catch, name=None, raises=False, types=(), catch_once=True):
        self.catch = catch
        self.name = name
        self.raises = raises or not catch_once
        self.types = types
        self.catch_once = catch_once

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_val is not None and isinstance(exc_val, self.types):
            self.catch.set(exc_val, self.name, self.catch_once)
            return not self.raises
