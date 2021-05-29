import time
import pytest
import remoteobj

# class KeyboardInterrupt2(BaseException): pass

# @pytest.fixture(autouse=True)
# def i_want_to_see_what_we_interrupt_damnit(tmpdir):
#     """Fixture to execute asserts before and after a test is run"""
#     try:
#         yield 
#     except KeyboardInterrupt as e:
#         raise KeyboardInterrupt2(str(e)) from e

def _error():
    print('hi im in your traceback!')
    raise KeyError('errorrr')

def _nested_err1():
    _nested_err2()

def _nested_err2():
    _nested_err3()

def _nested_err3():
    _error()

def test_process_traceback():
    try:
        import tblib
        with remoteobj.util.process(_nested_err1, raises_=False) as p:
            pass
        print(p.exc.all())
        try:
            p.exc.raise_any()
        except KeyError:
            import traceback
            tbstr = traceback.format_exc()
            for name in ['_nested_err1', '_nested_err2', '_nested_err3', '_error']:
                assert name in tbstr
    except ImportError:
        pass

@pytest.mark.parametrize("threaded", [False, True])
def test_process_error(threaded):
    '''Test that the remote error is raised in the main thread.'''
    p = remoteobj.util.job(_error, threaded_=threaded)
    p.start()
    with pytest.raises(KeyError):
        p.join()


@pytest.mark.parametrize("threaded", [False, True])
def test_process_context_error(threaded):
    '''Test which error takes precidence when both an error in the main thread
    and an error in the remote thread are raised.

    FIXME: I'm not sure if this is the right precidence, in fact it may be the wrong one.

    But this is just to give a definitive/predictable answer to which one it is.
    '''
    with pytest.raises(KeyError):
        with remoteobj.util.job(_error, threaded_=threaded):
            raise IndexError('error')


@pytest.mark.parametrize("threaded", [False, True])
def test_process_bad_func(threaded):
    '''Test how it reacts when a bad function is passed.
    '''
    with pytest.raises(TypeError):
        with remoteobj.util.job(True, threaded_=threaded):
            pass


def _return(x, y):
    return x + y

@pytest.mark.parametrize("threaded", [False, True])
def test_process_return(threaded):
    '''Test that we get the process return value.'''
    with remoteobj.util.job(_return, 5, 6, threaded_=threaded) as p:
        pass
    print(p.exc)
    assert p.result == 11


def _return_big(i=100, n=1000, nstr=20):
    return [{i: str(i)*nstr for i in range(i)} for _ in range(n)]

@pytest.mark.parametrize("threaded", [False, True])
def test_process_return_big(threaded):
    '''Test that we get the process return value.'''
    with remoteobj.util.job(_return_big, threaded_=threaded) as p:
        pass
    print(p.exc)
    assert p.result == _return_big()



def segfault_after(secs=0):
    secs and time.sleep(secs)
    remoteobj.util.segfault(dumps=False)


def test_process_join_segfault():
    '''Test that we get the process return value.'''
    with remoteobj.util.process(segfault_after, 0.5) as p:
        pass
    assert p.result is None


def delay_return(delay=0.1):
    time.sleep(delay)
    return 10

def test_process_return_after():
    '''Test that we get the process return value.'''
    p = remoteobj.util.job(delay_return)
    p.start()
    while p.is_alive():
        time.sleep(0.1)
    time.sleep(2)
    print(p.exc)
    assert p.result == delay_return(0)


@pytest.mark.parametrize("after_delay", [0.1, 0.5, 1])
@pytest.mark.parametrize("threaded", [False, True])
def test_process_return_sleep(after_delay, threaded):
    '''Test that we get the process return value.'''
    with remoteobj.util.job(_return, 5, 6, threaded_=threaded) as p:
        time.sleep(0.5)
    time.sleep(after_delay)
    print(p.exc)
    assert p.result == 11

def _yield(x, y):
    for i in range(x, y):
        yield i

def _yield2(x, y):
    return iter(range(x, y))


@pytest.mark.parametrize("func", [_yield, _yield2])
@pytest.mark.parametrize("threaded", [False, True])
def test_process_yield(func, threaded):
    '''Test that we get the expected yield values from both a generator function
    and a normal function that returns an iterator.'''
    with remoteobj.util.job(func, 5, 10, threaded_=threaded) as p:
        pass
    with pytest.raises(TypeError):
        _ = p.result[0]
    assert list(p.result) == list(range(5, 10))


def some_function():
    return

@pytest.mark.parametrize("threaded", [False, True])
def test_process_name(threaded):
    '''Make sure the process name is what we want'''
    name = 'some_function-{}'.format('thread' if threaded else 'process')
    with remoteobj.util.job(some_function, threaded_=threaded) as p:
        first_part, i = p.name.rsplit('-', 1)
        i = int(i)
        assert first_part == name

        # check that name increments
        with remoteobj.util.job(some_function, threaded_=threaded) as p:
            assert p.name == '{}-{}'.format(name, i+1)

        with remoteobj.util.job(some_function, threaded_=threaded) as p:
            assert p.name == '{}-{}'.format(name, i+2)

        # test that mp and thread name increments are independent
        with remoteobj.util.job(some_function, threaded_=not threaded) as p:
            pass

        with remoteobj.util.job(some_function, threaded_=threaded) as p:
            assert p.name == '{}-{}'.format(name, i+3)
