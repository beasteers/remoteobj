import time
import remoteobj
import pytest


# def sleepy(t=3):
#     time.sleep(t)

def short_sleepy(t=3, n=100):
    for i in range(n):
        time.sleep(1.*t/n)

@pytest.mark.parametrize("func", [short_sleepy])  # sleepy, 
def test_raise_thread(func, duration=3):
    t0 = time.time()
    with pytest.raises(ValueError):
        with remoteobj.util.thread(func, duration) as t:
            t.throw(ValueError)
    assert time.time() - t0 < duration
