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
