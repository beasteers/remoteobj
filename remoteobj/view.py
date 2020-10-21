import operator


def _fmt_args(*a, **kw):
    return ', '.join(
        ['{!r}'.format(x) for x in a] +
        ['{}={!r}'.format(k, v) for k, v in kw.items()])


class View:
    '''Represents a set of operations that can be captured, pickled, and
    applied to a remote object.

    This supports things like:
        - `view.some_attribute`
            NOTE: this doesn't work with private or magic attributes
        - `view['some key']`
        - `view(1, 2, x=10)`
        - `view.some_method(1, 2)`
        - `view.super.some_method(1, 2)`
                (translates to `super(type(obj), obj).some_method(1, 2)`)

    '''
    _keys, _frozen = (), False
    def __init__(self, *keys, frozen=False, **kw):
        self._keys = keys
        self._frozen = frozen
        super().__init__(**kw)

    def __str__(self):
        '''Return a string representation of the Op.'''
        x = '?'
        for kind, k in self._keys:
            # attribute
            if kind == '.':
                if k == 'super':
                    x = 'super({})'.format(x)
                else:
                    x = '{}.{}'.format(x, k)
            elif kind == '.=':
                x = '{}.{} = {}'.format(x, k[0], k[1])
            elif kind == 'del.':
                x = 'del {}.{}'.format(x, k)
            # keys
            elif kind == '[]':
                x = '{}[{!r}]'.format(x, k)
            elif kind == '[]=':
                x = '{}[{}] = {}'.format(x, k[0], k[1])
            elif kind == 'del[]':
                x = 'del {}.{}'.format(x, k)
            # call
            elif kind == '()':
                x = '{}({})'.format(x, _fmt_args(*k[0], **k[1]))
            elif kind == 'f()':
                x = '{}({})'.format(k[0].__name__, _fmt_args(x, *k[1], **k[2]))
            # misc
            elif kind == 'len':
                x = 'len({})'.format(x)
            elif kind == 'in':
                x = '{} in {}'.format(k, x)
            # # context
            # elif kind == 'enter':
            #     x = '{}.__enter__()'.format(x)
            # elif kind == 'exit':
            #     x = '{}.__exit__({}, {}, ...)'.format(x, k[0], k[1])
        return '({})'.format(x)

    def resolve_view(self, obj):
        '''Given an object, apply the view - get nested attributes, keys, call, etc.'''
        for kind, k in self._keys:
            # attribute
            if kind == '.':
                if k == 'super':
                    obj = super(type(obj), obj)
                else:
                    obj = getattr(obj, k)
            elif kind == '.=':
                setattr(obj, k[0], k[1])
                obj = None
            elif kind == 'del.':
                delattr(obj, k)
                obj = None
            # keys
            elif kind == '[]':
                obj = obj[k]
            elif kind == '[]=':
                obj[k[0]] = k[1]
                obj = None
            elif kind == 'del[]':
                del obj[k]
                obj = None
            # call
            elif kind == '()':
                obj = obj(*k[0], **k[1])
            elif kind == 'f()':
                obj = k[0](obj, *k[1], **k[2])
            # misc
            elif kind == 'in':
                obj = k in obj
            elif kind == 'len':
                obj = len(obj)
            # # context
            # elif kind == 'enter':
            #     obj = obj.__enter__()
            # elif kind == 'exit':
            #     obj = obj.__exit__(*k)
        return obj

    def _extend(self, *keys, **kw):
        '''Return a copy of self with additional keys.'''
        if self._frozen:
            raise TypeError(f'{self} is frozen and is not extendable.')
        return View(*self._keys, *keys, **kw)

    # attribute

    def __getattr__(self, name):
        '''Append a x.y op.'''
        if name.startswith('_') or self._frozen:
            raise AttributeError(name)
        return self._extend(('.', name))

    def _setattr(self, name, value):
        '''Append a x.y = z op'''
        return self._extend(('.=', (name, value)), frozen=True)

    def _delattr(self, name):
        '''Append a del x.y op'''
        return self._extend(('del.', name), frozen=True)

    # keys

    def __getitem__(self, index):
        '''Append a x[1] op.'''
        return self._extend(('[]', index))

    def _setitem(self, index, value):
        '''Append a x[1] op.'''
        return self._extend(('[]=', (index, value)), frozen=True)

    def _delitem(self, index):
        '''Append a del x[1] op.'''
        return self._extend(('del[]', index), frozen=True)

    # call

    def __call__(self, *a, **kw):
        '''Append a x(1, 2) op.'''
        if self._frozen:
            raise TypeError(f'{self} is frozen and is not callable.')
        return self._extend(('()', (a, kw)))

    # misc

    def __contains__(self, key):
        if self._frozen:
            raise TypeError(f'{self} is frozen and is not extendable.')
        return self._extend(('in', key))

    def _len(self):
        if self._frozen:
            raise TypeError(f'{self} is frozen and is not extendable.')
        return self._extend(('len', None))

    # __iter__

    # def __enter__(self):
    #     return self._extend(('enter', None))
    #
    # def __exit__(self, exc_type, exc_value, exc_tb):
    #     return self._extend(('enter', (exc_type, exc_value, exc_tb)))


    def passto(self, func, *a, **kw):
        return self._extend(('f()', (func, a, kw)))

    def attrs_(self, *keys):
        '''Access nested attributes using strings.
        e.g.
         - `x.attrs_('adsf') == x.asdf`
         - `x.attrs_('adsf.zxcv', 'sdfg', 'sdfg.sfg') == x.adsf.zxcv.sdfg.sdfg.sfg`
        '''
        return self._extend(*(('.', k) for ks in keys for k in ks.split('.')))
