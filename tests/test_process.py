import pytest
import remoteobj



def _error():
    raise KeyError('errorrr')

def test_process_error():
    '''Test that the remote error is raised in the main thread.'''
    p = remoteobj.util.process(_error)
    p.start()
    with pytest.raises(KeyError):
        p.join()


def test_process_context_error():
    '''Test which error takes precidence when both an error in the main thread
    and an error in the remote thread are raised.

    FIXME: I'm not sure if this is the right precidence, in fact it may be the wrong one.

    But this is just to give a definitive/predictable answer to which one it is.
    '''
    with pytest.raises(KeyError):
        with remoteobj.util.process(_error):
            raise IndexError('error')


def test_process_bad_func():
    '''Test how it reacts when a bad function is passed.
    '''
    with pytest.raises(TypeError):
        with remoteobj.util.process(True):
            pass


def _return(x, y):
    return x + y

def test_process_return():
    '''Test that we get the process return value.'''
    with remoteobj.util.process(_return, 5, 6) as p:
        pass
    assert p.result == 11

def _yield(x, y):
    for i in range(x, y):
        yield i

def _yield2(x, y):
    return iter(range(x, y))


@pytest.mark.parametrize("func", [_yield, _yield2])
def test_process_yield(func):
    '''Test that we get the expected yield values from both a generator function
    and a normal function that returns an iterator.'''
    with remoteobj.util.process(func, 5, 10) as p:
        pass
    with pytest.raises(TypeError):
        _ = p.result[0]
    assert list(p.result) == list(range(5, 10))
