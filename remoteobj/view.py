
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
    def __init__(self, *keys, frozen=False):
        self._keys = keys
        self._frozen = frozen

    def __str__(self):
        '''Return a string representation of the Op.'''
        x = '?'
        for kind, k in self._keys:
            if kind == '.':
                if k == 'super':
                    x = 'super({})'.format(x)
                else:
                    x = '{}.{}'.format(x, k)
            elif kind == '[]':
                x = '{}[{!r}]'.format(x, k)
            elif kind == '.=':
                x = '{}.{} = {}'.format(x, k[0], k[1])
            elif kind == '[]=':
                x = '{}[{}] = {}'.format(x, k[0], k[1])
            elif kind == '()':
                x = '{}({})'.format(x, _fmt_args(*k[0], **k[1]))
            elif kind == 'f()':
                x = '{}({})'.format(k[0].__name__, _fmt_args(x, *k[1], **k[2]))
        return '({})'.format(x)

    def resolve_view(self, obj):
        '''Given an object, apply the view - get nested attributes, keys, call, etc.'''
        for kind, k in self._keys:
            if kind == '.':
                if k == 'super':
                    obj = super(type(obj), obj)
                else:
                    obj = getattr(obj, k)
            elif kind == '[]':
                obj = obj[k]
            elif kind == '()':
                obj = obj(*k[0], **k[1])
            elif kind == '.=':
                setattr(obj, k[0], k[1])
            elif kind == '[]=':
                obj[k[0]] = k[1]
            elif kind == 'f()':
                obj = k[0](obj, *k[1], **k[2])
        return obj

    def _extend(self, *keys, **kw):
        '''Return a copy of self with additional keys.'''
        return View(*self._keys, *keys, **kw)

    def __getattr__(self, name):
        '''Append a x.y op.'''
        if name.startswith('_') or self._frozen:
            raise AttributeError(name)
        return self._extend(('.', name))

    def _setattr(self, name, value):
        '''Append a x.y = z op'''
        if self._frozen:
            raise AttributeError(name)
        return self._extend(('.=', (name, value)), frozen=True)

    def __getitem__(self, index):
        '''Append a x[1] op.'''
        if self._frozen:
            raise KeyError(index)
        return self._extend(('[]', index))

    def _setitem(self, index, value):
        '''Append a x[1] op.'''
        if self._frozen:
            raise KeyError(index)
        return self._extend(('[]=', (index, value)), frozen=True)

    def __call__(self, *a, **kw):
        '''Append a x(1, 2) op.'''
        if self._frozen:
            raise TypeError(f'{self} is frozen and is not callable.')
        return self._extend(('()', (a, kw)))

    def passto(self, func, *a, **kw):
        return self._extend(('f()', (func, a, kw)))

    @classmethod
    def attrs_(self, *keys):
        '''Access nested attributes using strings.
        e.g.
            x.attrs_('adsf') == x.asdf
            x.attrs_('adsf.zxcv', 'sdfg', 'sdfg.sfg') == x.adsf.zxcv.sdfg.sdfg.sfg
        '''
        return self._extend(*(('.', k) for ks in keys for k in ks.split('.')))
