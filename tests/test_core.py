import time
import remoteobj
import pytest


class ObjectA:
    x = 10
    term = False
    def __init__(self, **kw):
        self.remote = remoteobj.Proxy(self, **kw)

    def __str__(self):
        return f'<A x={self.x} terminated={self.term}>'

    def asdf(self):
        self.x *= 2
        return self

    def inc(self):
        self.x += 1
        return self.x

    @property
    def zxcv(self):
        return self.x / 5.

    def terminate(self):
        self.term = True
        return self

    def start(self):
        self.term = False
        return self

    def error(self):
        raise ValueError('hii')

class ObjectB(ObjectA):
    @property
    def zxcv(self):
        return self.x / 10.


def test_attribute_access_and_update():
    obj = ObjectB()
    with remoteobj.util.dummy_listener(obj):
        # attribute access
        assert obj.x == 10 and obj.remote.x.get_() == 10
        # local update
        obj.asdf()
        assert obj.x == 20 and obj.remote.x.get_() == 10
        # remote update
        obj.remote.asdf()
        assert obj.x == 20 and obj.remote.x.get_() == 20
        # property
        assert obj.zxcv == obj.remote.zxcv.get_() == 20/10


@pytest.mark.parametrize("bg", [False, True])
def test_bg_listener(bg):
    obj = ObjectB()
    with remoteobj.util.dummy_listener(obj, bg=bg):
        assert obj.remote.x.get_() == 10


def test_chaining():
    obj = ObjectB()
    with remoteobj.util.dummy_listener(obj):
        assert obj.remote.asdf() is obj.remote
        assert obj.remote.asdf().asdf() is obj.remote


def test_super():
    obj = ObjectB()
    with remoteobj.util.dummy_listener(obj):
        assert super(type(obj), obj).zxcv == obj.remote.super.zxcv.get_() == obj.x/5


def test_passto():
    obj = ObjectB()
    with remoteobj.util.dummy_listener(obj):
        assert str(obj) == obj.remote.passto(str) == '<A x={} terminated={}>'.format(obj.x, obj.term)


def test_state_toggle():
    obj = ObjectB()
    with remoteobj.util.dummy_listener(obj):
        # local terminate
        obj.terminate()
        assert obj.remote.term.__ == False and obj.term == True
        obj.start()
        assert obj.remote.term.__ == False and obj.term == False

        # remote terminate
        obj.remote.terminate()
        assert obj.remote.term.__ == True and obj.term == False
        obj.remote.start()
        assert obj.remote.term.__ == False and obj.term == False


def test_setattr():
    obj = ObjectB()
    with remoteobj.util.dummy_listener(obj):
        # remote setattr
        obj.remote.term = True
        assert isinstance(obj.remote.term, remoteobj.Proxy)
        assert obj.remote.term.get_() == True and obj.term == False
        obj.remote.term = False
        assert obj.remote.term.get_() == False and obj.term == False

        # local setattr
        obj.term = True
        assert obj.remote.term.get_() == False and obj.term == True
        obj.term = False
        assert obj.remote.term.get_() == False and obj.term == False



def _up_and_down(obj):
    with obj.remote:
        time.sleep(0.05)

def _exit_early(obj):
    pass


def test_wait_until_listening():
    obj = ObjectB()
    with remoteobj.util.process(_up_and_down, obj) as p:
        assert obj.remote.wait_until_listening(p)

    with remoteobj.util.process(_exit_early, obj) as p:
        with pytest.raises(RuntimeError):
            obj.remote.wait_until_listening(p)


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
    with remoteobj.util.dummy_listener(obj):
        assert isinstance(obj.remote.inc(), int)

    obj = ObjectB(eager_proxy=False)
    with remoteobj.util.dummy_listener(obj):
        assert isinstance(obj.remote.inc(), remoteobj.Proxy)



def _state_toggle_test(obj):
    with obj.catch_:
        # local terminate
        obj.terminate()
        assert obj.remote.term.get_() == False and obj.term == True
        obj.start()
        assert obj.remote.term.get_() == False and obj.term == False

        # remote terminate
        obj.remote.terminate()
        assert obj.remote.term.get_() == True and obj.term == False
        obj.remote.start()
        assert obj.remote.term.get_() == False and obj.term == False


def test_remote_clients():
    '''Determine if the remote instance can get data.'''
    obj = ObjectB()
    obj.catch_ = remoteobj.Except()

    with remoteobj.util.dummy_listener(obj):
        with remoteobj.util.remote_func(_state_toggle_test, obj) as (p, c1):
            time.sleep(0.1)
        assert c1.value > 0
        print(obj.catch_)
        obj.catch_.raise_any()




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
    with obj.catch_:
        xs = [isinstance(obj.remote.attrs_(k).get_(), type_) for _ in range(n)]
        return True
    return False


def test_remote_exception():
    '''Test that remote exceptions are thrown and that the original traceback is displayed.'''
    obj = Types()
    obj.catch_ = remoteobj.Except()

    assert obj.remote._listening == False
    with remoteobj.util.dummy_listener(obj):
        assert obj.remote._listening == True

        obj.catch_.raise_any()  # nothing
        with remoteobj.util.remote_func(_do_work, obj, 'doesntexist', bool):
            time.sleep(0.1)
        print(obj.catch_)
        with pytest.raises(AttributeError):
            obj.catch_.raise_any()



def test_dueling_threads():
    '''Determine if two threads making requests at the same time causes problems.'''
    obj = Types()
    obj.catch_ = remoteobj.Except()

    assert obj.remote._listening == False
    with remoteobj.util.dummy_listener(obj):
        assert obj.remote._listening == True

        with remoteobj.util.remote_func(_do_work, obj, 'boolean', bool) as (p, c1):
            with remoteobj.util.remote_func(_do_work, obj, 'string', str) as (p, c2):
                with remoteobj.util.remote_func(_do_work, obj, 'integer', int) as (p, c3):
                    time.sleep(0.2)
                    _do_work(obj, 'tuple', tuple)
                    time.sleep(0.5)
        print('duel counts', c1.value, c2.value, c3.value)
        assert c1.value > 0
        assert c2.value > 0
        assert c3.value > 0

        obj.catch_.raise_any()









def _raise_stuff(catch):
    with catch('overall'):
        with catch:
            raise AttributeError('a')
        with catch():
            raise KeyError('a')
        with catch('init'):
            raise ValueError('b')
        for _ in range(5):
            with catch('process'):
                raise IndexError('c')
        with catch('finish'):
            raise RuntimeError('d')
        with pytest.raises(AttributeError):
            with catch(raises=True):
                raise AttributeError('e')
        with pytest.raises(AttributeError):
            with catch(types=TypeError):
                raise AttributeError('e')

        with catch:
            with catch(catch_once=False, raises=True):
                raise TypeError('q')

ALL_RAISED_ = {
    None: [AttributeError('a'), KeyError('a'), AttributeError('e'), TypeError('q'), TypeError('q')],
    'init': [ValueError('b')],
    'process': [IndexError('c')]*5,
    'finish': [RuntimeError('d')],
    'overall': [],
}
N_RAISED_ = sum(1 for es in ALL_RAISED_.values() for e in es)

def compare_excs(excs1, excs2):
    return all(
        type(e1) == type(e2) and str(e1) == str(e2)
        for e1, e2 in zip(excs1 or (), excs2 or ()))

def test_remote_named_exceptions():
    catch = remoteobj.Except(raises=False)

    with remoteobj.util.process(_raise_stuff, catch):
        pass
    print(catch)
    for name, excs in ALL_RAISED_.items():
        assert compare_excs(catch.group(name), excs)
    assert len(catch.all()) == N_RAISED_

def test_local_exceptions():
    catch = remoteobj.LocalExcept(raises=False)

    _raise_stuff(catch)
    print(catch)
    for name, excs in ALL_RAISED_.items():
        assert compare_excs(catch.group(name), excs)
    assert len(catch.all()) == N_RAISED_
