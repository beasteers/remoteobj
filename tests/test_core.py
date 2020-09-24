import time
import remoteobj
import pytest


class ObjectA:
    x = 10
    term = False
    def __init__(self):
        self.remote = remoteobj.Proxy(self)

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

def _run_remote(obj, event):  # some remote job
    with obj.catch_:
        with obj.remote:
            while not event.is_set():
                obj.remote.poll()
                time.sleep(0.0001)
        raise ValueError('blah')


def test_remote():
    obj = ObjectB()
    obj.catch_ = remoteobj.Except()

    assert obj.remote._listening == False
    with remoteobj.util.dummy_listener(obj, _run_remote):
        assert obj.remote._listening == True

        X = obj.x
        i_l, i_r = 0, 0

        # attribute access
        assert obj.x == X*(2**i_l)
        assert obj.remote.x.get_() == X*(2**i_r)

        # local update
        obj.asdf()
        i_l += 1
        assert obj.x == X*(2**i_l)
        assert obj.remote.x.get_() == X*(2**i_r)

        # remote update
        obj.remote.asdf()
        i_r += 1
        assert obj.x == X*(2**i_l)
        assert obj.remote.x.get_() == X*(2**i_r)

        # remote property
        assert obj.zxcv == X*(2**i_l)/10
        assert obj.remote.zxcv.get_() == X*(2**i_r)/10

        assert super(type(obj), obj).zxcv == X*(2**i_l)*2/10
        assert obj.remote.super.zxcv.get_() == X*(2**i_r)*2/10

        # remote update
        i_r += 3
        assert obj.remote.asdf().asdf().asdf() is obj.remote
        assert obj.x == X*(2**i_l)
        assert obj.remote.x.get_() == X*(2**i_r)

        # terminate

        # local terminate
        obj.terminate()
        assert obj.remote.term.get_() == False
        assert obj.term == True

        obj.start()
        assert obj.remote.term.get_() == False
        assert obj.term == False

        # remote terminate
        obj.remote.terminate()
        assert obj.remote.term.get_() == True
        assert obj.term == False

        obj.remote.start()
        assert obj.remote.term.get_() == False
        assert obj.term == False

        # setattr

        # remote setattr
        obj.remote.term = True
        assert obj.remote.term.get_() == True
        assert obj.term == False

        obj.remote.term = False
        assert obj.remote.term.get_() == False
        assert obj.term == False

        # local setattr
        obj.term = True
        assert obj.remote.term.get_() == False
        assert obj.term == True

        obj.term = False
        assert obj.remote.term.get_() == False
        assert obj.term == False

        # passto

        x = obj.remote.passto(str)
        assert x == '<A x={} terminated={}>'.format(X*(2**i_r), False)

    assert not obj.remote._listening

    exc = obj.catch_.get()
    assert isinstance(exc, ValueError)
    assert str(exc) == 'blah'
    assert 'in _run_remote' in str(exc.__cause__)
    with pytest.raises(ValueError):
        obj.catch_.raise_any()





def _state_toggle_test(obj):
    with obj.catch_:
        # local terminate
        obj.terminate()
        assert obj.remote.term.get_() == False
        assert obj.term == True

        obj.start()
        assert obj.remote.term.get_() == False
        assert obj.term == False

        # remote terminate
        obj.remote.terminate()
        assert obj.remote.term.get_() == True
        assert obj.term == False

        obj.remote.start()
        assert obj.remote.term.get_() == False
        assert obj.term == False


def test_remote_clients():
    '''Determine if the remote instance can get data.'''
    obj = ObjectB()
    obj.catch_ = remoteobj.Except()

    assert obj.remote._listening == False
    with remoteobj.util.dummy_listener(obj):
        assert obj.remote._listening == True
        with remoteobj.util.remote_func(_state_toggle_test, obj) as (p, c1):
            time.sleep(0.1)
        assert c1.value > 0
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
        with pytest.raises(AttributeError):
            obj.catch_.raise_any()



def _raise_stuff(obj):
    with obj.catch_('overall'):
        with obj.catch_:
            raise AttributeError('a')
        with obj.catch_():
            raise KeyError('a')
        with obj.catch_('init'):
            raise ValueError('b')
        for _ in range(5):
            with obj.catch_('process'):
                raise IndexError('c')
        with obj.catch_('finish'):
            raise RuntimeError('d')
        with pytest.raises(AttributeError):
            with obj.catch_(raises=True):
                raise AttributeError('e')
        with pytest.raises(AttributeError):
            with obj.catch_(types=TypeError):
                raise AttributeError('e')

def compare_excs(excs1, excs2):
    return all(
        type(e1) == type(e2) and str(e1) == str(e2)
        for e1, e2 in zip(excs1 or (), excs2 or ()))

def test_remote_named_exceptions():
    obj = Types()
    obj.catch_ = remoteobj.Except(raises=False)

    with remoteobj.util.process(_raise_stuff, obj):
        pass
    print(obj.catch_)
    assert compare_excs(
        obj.catch_.groups.get(None),
        [AttributeError('a'), KeyError('a'), AttributeError('e')])
    assert compare_excs(obj.catch_.groups.get('init'), [ValueError('b')])
    assert compare_excs(obj.catch_.groups.get('process'), [IndexError('c')]*5)
    assert compare_excs(obj.catch_.groups.get('finish'), [RuntimeError('d')])
    assert compare_excs(obj.catch_.groups.get('overall'), [])
    assert len(obj.catch_.all) == 10


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








class PropObj:
    exc2 = remoteobj.util.AnyValueProp('exc2')
    def __init__(self):
        self.counter = remoteobj.util.AnyValue(0)
        self.exc = remoteobj.util.AnyValue()

    def run(self):
        try:
            for _ in range(10):
                self.counter.value += 1
                time.sleep(0.05)
            raise ValueError('something')
        except Exception as exc:
            e = remoteobj.RemoteException(exc)
            self.exc.value = e
            self.exc = e


def test_anyvalue():
    obj = PropObj()
    with remoteobj.util.remote_func(obj.run):
        results = []
        while True:
            x = obj.counter.value
            results.append(x)
            time.sleep(0.001)
            if x >= 9:
                break
    assert set(results) == set(range(10))
    exc = obj.exc.value
    assert isinstance(exc, ValueError)
    assert str(exc) == 'something'
    assert 'in run' in str(exc.__cause__)
