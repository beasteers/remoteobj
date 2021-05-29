## Feature Proposals
 - equivalent `util.process().throw()` like what we have for threads
 - `util.raise_thread` doesn't work with I/O e.g. `time.sleep(long_time)`
 - sorting exceptions by emit order (while still storing by group?)
 - fix reserved parameter consistency because it can be confusing
 - Have proxy object be segfault safe !!!
   - In order to do this, Proxy objects would need access to the current_process inside the listener process in order to know if the process is still alive.
   - could we use a lookup table by ident?
   - what about the case where a proxy object gets sent to another child process first and then a listener is spawned in a sibling process. how would we access the current_process() object?

# 0.4.0
 - Fixed (hopefully) garbage collection bug for Except's queue objects
 - added utility to create segfaults - used for tests so we can be sure of how it will behave
 - fixed deadlock where large items in queue would cause `util.process.join()` to hang
   - this included adding a `mp.Event` that will wait for the process to return before joining.
 - Proxy objects now identify the current process using the process ID (`.ident`) and set it using a mp.Value object.
   - the reason for this is that storing strings in `mp.Value` was being such a hassle
 - If `tblib` is installed, then it will be used to pickle exceptions passed by Except objects (which is used for exception handling and return values of `util.process` objects)
   - also decided last minute to just add `tblib` as a dependency (it's small)
 - add param: `Proxy.wait_until_listening(timeout=None)`
 - added tests for large return values to `util.process`
 - added segfault return test for `util.process`

# 0.3.1
 - fix another race condition when closing a remote listener (wasn't preventing requesting processes from acquiring the lock if the process is no longer listening) god this is exhausting

# 0.3.0
 - fix race condition when closing a remote listener (wasn't checking if a requesting process had locked, but not sent yet)

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
