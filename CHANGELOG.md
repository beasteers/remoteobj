## Feature Proposals
 - equivalent `util.process().throw()` like what we have for threads
 - `util.raise_thread` doesn't work with I/O e.g. `time.sleep(long_time)`
 - sorting exceptions by emit order (while still storing by group?)
 - fix reserved parameter consistency because it can be confusing

# 0.2.9
 - add `close_` argument which takes a function that will be called before joining. Useful for passing a function that sets a flag.

# 0.2.8
 - switched from mp.Pipe to mp.Queue - more reliable. sometimes with pipes the data (especially function return), wouldn't go thru
 - can set per-context logger/tog_tb flag - e.g. `with exc(log=logger, log_tb=True):`

# 0.2.7
 - add `LocalExcept.log_tracebacks()` which calls `log.exception` for all exceptions
 - add `exc.logline()` which does `log.error(f'({e.__class__.__name__}) {e}')`
 - add `util.raise_thread()` which raises an exception in the thread
    - similarly, added `util.thread().throw(ValueError)` as a convenience method
 - add `Proxy().get_(default_local=True)` which will resolve the view locally if no remote instance is found.
 - added `LocalExcept.__iter__` method to iterate over exceptions
 - added `LocalExcept.clear_result()`
 - added `LocalExcept.pop_result()` which gets the result and then clears it

# 0.2.6a1
 - fix Except pipe hang

# 0.2.5
 - added `util.process/thread.raise_any()`
 - rename `util.job(threaded=True)` => `util.job(threaded_=True)`
 - refactored BaseListener out of Proxy
 - fixed bad call default argument
 - default value can be a callable that will be evaluated lazily

# 0.2.4
 - added `util.thread` for a threaded equivalent to `util.process`
 - added `util.job(threaded=True)` / `util.job(threaded=False)` for a parameterized interface for thread / process respectively.

# 0.2.3
 - added super simple examples for each at the top of the README to illustrate
 - fixed unpickleable bug TODO add test
 - fixed bug when using except on a generator, then a function.
 - removing second dict from Except that stored the latest exception - redundant, let's us allow customization
 - renaming `util.dummy_listener` => `util.listener` for possible public use
 - fix listener bg=True potential hang on background exception
 - started on api doc generation

# 0.2.2
 - fix `listen_(bg=False)` bug causing deadlock

# 0.2.1
 - move `Proxy.__str__` to `Proxy.__repr__` - for pytest debugging

# 0.2.0
 - added changelog :p
 - test reorganize so that tests are more isolated/targeted/organized
 - moved exception classes to their own file
 - changed `background_listen` => `listen_(bg=True)`
 - changed `stop_listening` => `stop_listen_()`
 - deprecating `with obj.remote:` in favor of `with obj.remote.listen_():`
 - added ops: `delitem`, `delattr`, `contains`, `len`.
    - What about context managers?? Allowing proxy `__enter__/__exit__` may change how the listener interface is currently written...
 - change `Proxy._listening` => `Proxy.listening_` so that it's public for ppl to use when using `listen_(bg=True)`
 - added return/yield handling for `util.process`
 - `util.process.start()` returns `self` for chaining/autostart
 - added more doc strings
 - `View._extend` is now aware of `self._frozen` and will throw a general `TypeError` if frozen.
