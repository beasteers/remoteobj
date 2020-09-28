import remoteobj
import pytest



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
