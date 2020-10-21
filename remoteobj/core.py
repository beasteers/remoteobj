from .base import BaseListener, make_token, UNDEFINED
from .view import View


__all__ = ['get', 'Proxy']


def get(view, **kw):
    '''Resolve a Proxy object and get its return value.'''
    return view.get_(**kw)


SELF = make_token('self')


class Proxy(View, BaseListener):
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
    _ALLOWED_ATTRS = {'listening_'}
    def __init__(self, instance, eager_proxy=True, **kw):
        super().__init__(**kw)
        self._obj = instance
        self._eager_proxy = eager_proxy
        self._root = self  # isn't called when extending

    def __repr__(self):
        return '<Remote {} : {}>'.format(self._obj, super().__str__())

    def __str__(self):
        return self.passto(str, _default=self.__repr__)

    # remote calling interface

    def _process(self, request):
        return View(*request).resolve_view(self._obj)

    def _form_result(self, result):
        if result is self._obj:  # solution for chaining
            result = SELF
        return result

    def _parse_response(self, x):
        x = super()._parse_response(x)
        if x == SELF:
            x = self._root  # root remote object without any ops
        return x

    # parent calling interface

    def get_(self, **kw):
        return self._evaluate(self._keys, **kw)

    @property
    def __(self):
        '''Get value from remote object. Alias for self.get_().'''
        return self.get_()

    # internal view mechanics. These override RemoteView methods.

    def _extend(self, *keys, **kw):
        # Create a new remote proxy object while **bypassing BaseListener.__init__**
        # Basically, we don't want to recreate pipes, locks, etc.
        obj = super()._extend(*keys, **kw)
        obj.__class__ = self.__class__
        obj.__dict__ = dict(self.__dict__, **obj.__dict__)
        return obj

    def __call__(self, *a, _default=UNDEFINED, _proxy=None, **kw):
        '''Automatically retrieve when calling a function.'''
        val = super().__call__(*a, **kw)
        if (self._eager_proxy if _proxy is None else _proxy):
            val = val.get_(default=_default)
        return val

    # attribute

    def _check_attr(self, name):
        '''Determine if an attribute is one we should override.'''
        return (name.startswith('_') or name in self._ALLOWED_ATTRS or name in self.__dict__)

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

    def passto(self, func, *a, _default=UNDEFINED, _proxy=None, **kw):
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
