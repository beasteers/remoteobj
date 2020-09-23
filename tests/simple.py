import time
import random
import multiprocessing as mp


class BaseProxy:
    _delay = 1e-6
    NOCOPY = ['_local', '_remote']
    def __init__(self, obj):
        self._obj = obj
        self._listening = mp.Value('i', 0, lock=False)

    def __getstate__(self):
        '''Don't pickle queues, locks, and shared values.'''
        return dict(self.__dict__, _thread=None, _listening=False, **{k: None for k in self.NOCOPY})

    #

    def remote(self, func, *a, **kw):
        self._local_send(self._prep_send(func, *a, **kw))
        ret, err = self._local_recv()
        if ret == 'SELF!!':
            ret = self._obj
        if err:
            raise Exception("Remote exception") from err
        return ret

    def poll(self):
        try:
            if self._do_poll():
                ret = self._do_process(self._remote_recv())
                if ret is self._obj:
                    ret = 'SELF!!'
                self._remote_send((ret, None))
        except Exception as e:
            self._remote_send((None, e))

    #

    def _prep_send(self, func, *a, **kw):
        name = func if isinstance(func, str) else func.__name__
        return name, a, kw

    def _do_process(self, x):
        func, args, kwargs = x
        return getattr(self._obj, func)(*args, **kwargs)

    #

    def _do_poll(self):
        raise NotImplementedError

    def _local_recv(self):
        raise NotImplementedError

    def _local_send(self, x):
        raise NotImplementedError

    def _remote_recv(self):
        raise NotImplementedError

    def _remote_send(self, x):
        raise NotImplementedError

    #

    def wait_until_listening(self):
        while not self.listening:
            time.sleep(1e-5)

    @property
    def listening(self):
        return bool(self._listening.value)

    @listening.setter
    def listening(self, value):
        self._listening.value = int(value)

    def __enter__(self):
        self.listening = True

    def __exit__(self, *a):
        self.listening = False



class PipeProxy(BaseProxy):
    def __init__(self, obj):
        super().__init__(obj)
        self._local, self._remote = mp.Pipe()

    def _do_poll(self):
        return self._remote.poll()

    def _local_recv(self):
        return self._local.recv()

    def _local_send(self, x):
        return self._local.send(x)

    def _remote_recv(self):
        return self._remote.recv()

    def _remote_send(self, x):
        return self._remote.send(x)


class QueueProxy(BaseProxy):
    def __init__(self, obj):
        super().__init__(obj)
        self._local, self._remote = mp.Queue(), mp.Queue()

    def _do_poll(self):
        return not self._remote.empty()

    def _local_recv(self):
        return self._local.get()

    def _local_send(self, x):
        return self._remote.put(x)

    def _remote_recv(self):
        return self._remote.get()

    def _remote_send(self, x):
        return self._local.put(x)


class SimpleQueueProxy(QueueProxy):
    def __init__(self, obj):
        super(QueueProxy, self).__init__(obj)
        self._local, self._remote = mp.SimpleQueue(), mp.SimpleQueue()

class ManagerQueueProxy(QueueProxy):
    def __init__(self, obj):
        super(QueueProxy, self).__init__(obj)
        manager = mp.Manager()
        self._local, self._remote = manager.Queue(), manager.Queue()


class BaseIdProxy(BaseProxy):
    def __init__(self, obj):
        super().__init__(obj)
        manager = mp.Manager()
        self._local, self._remote = manager.dict(), manager.Queue()

    def _do_poll(self):
        return not self._remote.empty()

    def _local_recv(self, xid):
        while self.listening and xid not in self._local:
            time.sleep(self._delay)
        return self._local.pop(xid, None)

    def _local_send(self, x):
        return self._remote.put(x)

    def _remote_recv(self):
        return self._remote.get()

    def _remote_send(self, x, xid):
        self._local[xid] = x

    def remote(self, func, *a, **kw):
        xid = random.randint(0, 10000)
        self._local_send(self._prep_send(xid, func, *a, **kw))
        ret, err = self._local_recv(xid)
        if err:
            raise Exception("Remote exception") from err
        return ret

    def _prep_send(self, xid, func, *a, **kw):
        return (xid,) + super()._prep_send(func, *a, **kw)

    def poll(self):
        try:
            if self._do_poll():
                x = self._remote_recv()
                ret = self._do_process(x[1:])
                self._remote_send((ret, None), x[0])
        except Exception as e:
            self._remote_send((None, e), x[0])


class DictQueueProxy(BaseIdProxy):
    def __init__(self, obj):
        super().__init__(obj)
        manager = mp.Manager()
        self._local, self._remote = manager.dict(), manager.Queue()
