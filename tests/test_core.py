import time
import remoteobj
import multiprocessing as mp


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
    with obj.remote:
        while not event.is_set():
            obj.remote.poll()
            time.sleep(0.0001)

def _run_remote_bg(obj, event):  # some remote job
    with obj.remote.background_listen():
        while not event.is_set():
            time.sleep(0.0001)


def test_remote():
    obj = ObjectB()

    assert obj.remote.listening == False
    event = mp.Event()
    p = mp.Process(target=_run_remote, args=(obj, event), daemon=True)
    p.start()
    obj.remote.wait_until_listening()
    assert obj.remote.listening == True

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

    assert p.is_alive()
    event.set()
    p.join()
    assert not obj.remote.listening
