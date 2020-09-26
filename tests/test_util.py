import time
import remoteobj

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
