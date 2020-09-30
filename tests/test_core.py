import time
from contextlib import contextmanager
import remoteobj
import pytest
import multiprocessing as mp


class ObjectA:
    x = 10
    def __init__(self, **kw):
        self.remote = remoteobj.Proxy(self, **kw)
        self.data = {'a': 5}

    def __str__(self):
        return f'<A x={self.x}>'

    def asdf(self):
        self.x *= 2
        return self

    def chain(self):
        return self

    def error(self):
        raise KeyError('error!')

    def inc(self):
        self.x += 1
        return self.x

    @property
    def zxcv(self):
        return 8

    def override(self):
        return 2


class ObjectB(ObjectA):
    def override(self):
        return 10


def test_get():
    '''Test remote get commands return the expected value.

    Checks: remoteobj.get(o), o.get_(), o.get_(default=...), o.__
    '''
    obj = ObjectB()
    with remoteobj.util.listener(obj):
        assert remoteobj.get(obj.remote.x) == obj.x
        assert obj.remote.x.get_() == obj.x
        assert obj.remote.x.__ == obj.x

    # test after remote listener has closed.
    with pytest.raises(RuntimeError):
        obj.remote.x.get_()
    assert obj.remote.x.get_(default=True) == True


@pytest.mark.parametrize("bg", [False, True])
def test_bg_listener(bg):
    '''Test that the background listener can respond to calls.

    Checks: Proxy.background_listen()
    '''
    obj = ObjectB()
    with remoteobj.util.listener(obj, bg=bg):
        assert obj.remote.x.__ == 10

    with pytest.raises(KeyError):
        with remoteobj.util.listener(obj, bg=bg):
            obj.remote.error()


def test_attr():
    '''Test get, set, and del attribute.

    Checks: o.x, o.x = y, del o.x, o.passto(hasattr, 'x'), o.prop
    '''
    obj = ObjectB()
    obj.y = 5
    with remoteobj.util.listener(obj):
        # remote setattr
        obj.remote.y = 6
        assert isinstance(obj.remote.y, remoteobj.Proxy)
        assert obj.remote.y.__ == 6 and obj.y == 5
        obj.remote.y = 5
        assert obj.remote.y.__ == 5 and obj.y == 5

        # local setattr
        obj.y = 6
        assert obj.remote.y.__ == 5 and obj.y == 6
        obj.y = 5
        assert obj.remote.y.__ == 5 and obj.y == 5

        # delattr, hasattr
        attrs = lambda: [
            hasattr(obj, 'x'),
            hasattr(obj, 'y'),
            obj.remote.passto(hasattr, 'x'),
            obj.remote.passto(hasattr, 'y')]
        assert attrs() == [True, True, True, True]
        del obj.remote.y
        assert attrs() == [True, True, True, False]
        del obj.y
        assert attrs() == [True, False, True, False]
        obj.remote.y = 2
        assert attrs() == [True, False, True, True]

        # property
        assert obj.remote.zxcv.__ == 8


def test_getset_item():
    '''Test get, set, and del attribute.

    Checks: o[x], o[x] = y, del o[x], x in o, len(o)
    '''
    obj = ObjectB()
    with remoteobj.util.listener(obj):
        assert 'a' in obj.remote.data
        assert obj.remote.data.passto(list) == ['a']
        assert obj.remote.data['a'].__ == 5
        assert 'b' not in obj.remote.data
        assert len(obj.remote.data) == 1


        obj.remote.data['b'] = 8
        assert 'b' in obj.remote.data
        assert len(obj.remote.data) == 2
        del obj.remote.data['a']
        assert 'a' not in obj.remote.data
        assert 'b' in obj.remote.data
        assert len(obj.remote.data) == 1


def test_chaining():
    '''Test that a remote object returning self will translate to returning the
    proxy object.

    Checks: return self -> value = SELF -> self if value == SELF
    '''
    obj = ObjectB()
    with remoteobj.util.listener(obj):
        assert obj.remote.chain() is obj.remote
        assert obj.remote.chain().chain() is obj.remote


def test_super():
    '''Test that super attribute will call subsequent attributes on the super obj.

    Checks: o.super.asdf()

    TODO: test multiple supers. I don't think this will work atm.
    '''
    obj = ObjectB()
    with remoteobj.util.listener(obj):
        assert obj.override() == obj.remote.override() == 10
        assert super(type(obj), obj).override() == obj.remote.super.override() == 2


def test_call():
    '''Test calling object as a function and passing obj to a function.

    Checks: o(x), o.passto(x) (-> x(o))
    '''
    obj = ObjectB()
    with remoteobj.util.listener(obj):
        assert str(obj) == obj.remote.passto(str) == '<A x={}>'.format(obj.x)



def _up_and_down(obj):
    with obj.remote:
        time.sleep(0.05)

def _exit_early(obj):
    pass


def test_wait_until_listening():
    obj = ObjectB()
    with remoteobj.util.process(_up_and_down, obj) as p:
        assert obj.remote.wait_until_listening(p)

def test_wait_until_listening_fail():
    obj = ObjectB()
    with remoteobj.util.process(_exit_early, obj) as p:
        with pytest.raises(RuntimeError):
            print('listening', obj.remote.wait_until_listening(p))


def test_fulfill_final():
    obj = ObjectB()
    with remoteobj.util.process(_up_and_down, obj) as p:
        assert obj.remote.wait_until_listening(p)
        assert obj.remote.x.get_(default=None) == 10
        time.sleep(0.3)
        assert not p.is_alive()  # should have exited on its own

    obj = ObjectB(fulfill_final=False)
    with remoteobj.util.process(_up_and_down, obj) as p:
        assert obj.remote.wait_until_listening(p)
        assert obj.remote.x.get_(default=None) == None
        time.sleep(0.3)
        assert not p.is_alive()  # should have exited on its own


def test_eager_proxy():
    obj = ObjectB()
    with remoteobj.util.listener(obj):
        assert isinstance(obj.remote.inc(), int)

    obj = ObjectB(eager_proxy=False)
    with remoteobj.util.listener(obj):
        assert isinstance(obj.remote.inc(), remoteobj.Proxy)



def _state_toggle_test(obj):
    # attribute access
    assert obj.remote.x.__ == 10
    obj.remote.asdf()
    assert obj.remote.x.__ == 20
    obj.remote.asdf().asdf()
    assert obj.remote.x.__ == 80


def test_remote_clients():
    '''Determine if the remote instance can get data.'''
    obj = ObjectB()
    with remoteobj.util.listener(obj):
        assert obj.remote.x.__ == 10
        with remoteobj.util.process(_state_toggle_test, obj) as p:
            pass
        assert obj.remote.x.__ == 80




class Types:
    def __init__(self):
        self.remote = remoteobj.Proxy(self)

    def boolean(self):
        return True

    def integer(self):
        return 5

    def tuple(self):
        return ()

    def string(self):
        return 'asdfasdfasdf'


def _do_work(obj, k, type_, n=20):
    xs = [obj.remote.attrs_(k)() for _ in range(n)]
    print(xs, k, type_)
    assert all(isinstance(x, type_) for x in xs)



@contextmanager
def remote_func(callback, *a, **kw):
    '''Run a function repeatedly in a separate process.

    '''
    count = mp.Value('i', 0)
    event = mp.Event()
    with remoteobj.util.process(_run_remote_func, callback, event, count, *a, **kw) as p:
        try:
            yield p, count
        finally:
            event.set()

def _run_remote_func(callback, event, count, *a, delay=1e-3, **kw):
    while not event.is_set():
        if callback(*a, **kw) is False:
            return
        time.sleep(delay)
        count.value += 1



def test_dueling_threads():
    '''Determine if two threads making requests at the same time causes problems.'''
    obj = Types()
    obj.catch_ = remoteobj.Except()

    assert obj.remote.listening_ == False
    with remoteobj.util.listener(obj):
        assert obj.remote.listening_ == True

        with remote_func(_do_work, obj, 'boolean', bool) as (p, c1):
            with remote_func(_do_work, obj, 'string', str) as (p, c2):
                with remote_func(_do_work, obj, 'integer', int) as (p, c3):
                    time.sleep(0.2)
                    _do_work(obj, 'tuple', tuple)
                    time.sleep(0.5)
        print('duel counts', c1.value, c2.value, c3.value)
        assert c1.value > 0
        assert c2.value > 0
        assert c3.value > 0

        obj.catch_.raise_any()
