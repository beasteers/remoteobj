import time
import timeit
from contextlib import contextmanager
import remoteobj
import simple
# import reip

class Obj:
    def __init__(self, proxycls=remoteobj.Proxy):
        self.remote = proxycls(self)

    def boolean(self):
        return True

    def integer(self):
        return 5

    def number(self):
        return 5.5

    def string(self):
        return 'asdfasdfasdf'

    @property
    def prop(self):
        return True

    def me(self):
        return self



# calls = [
#     'obj.remote.boolean()',
#     'obj.remote.integer()',
#     'obj.remote.number()',
#     'obj.remote.string()',
#     # 'obj.remote.prop.__',
#     'obj.remote.me()',
# ]

calls = [
    'boolean',
    'integer',
    'number',
    'string',
    'me',
]

# @contextmanager
# def _profile():
#     try:
#         import cProfile
#         prof = cProfile.Profile()
#         prof.enable()
#         yield
#     finally:
#         prof.disable()
#         prof.print_stats(sort='cumtime')


@contextmanager
def _profile():
    try:
        import pyinstrument
        prof = pyinstrument.Profiler()
        prof.start()
        yield
    finally:
        prof.stop()
        print(prof.output_text(unicode=True, color=True, show_all=True))


def _profile_func(func):
    def inner(*a, catch=None, **kw):
        with catch:
            with _profile():
                print('profiling', func.__name__, a, kw)
                return func(*a, **kw)
    return inner


remoteobj.util._run_remote = _profile_func(remoteobj.util._run_remote)

def run_test(obj, calls, n=100):
    catch = remoteobj.Except()
    for obj in objs:
        print(obj.remote.__class__.__name__)
        with remoteobj.util.dummy_listener(obj, catch=catch):
            with _profile():
                for _ in range(n):
                    for k in calls:
                        yield obj, k
        catch.raise_any()




objs = [
    Obj(simple.PipeProxy),
    Obj(simple.QueueProxy),
    Obj(simple.SimpleQueueProxy),
    # Obj(simple.ManagerQueueProxy),
    # Obj(simple.DictQueueProxy),
]

# calls_ = [k.split('.')[-1].strip('()') for k in calls]
for obj, k in run_test(objs, calls):
    _ = obj.remote.remote(k)
    # print(k, _, getattr(obj, k)())
    assert _ == getattr(obj, k)() or _ == obj.remote
    # print(k, timeit.timeit('obj.remote.remote("{}")'.format(k), number=1, globals=globals()))



objs = [
    Obj(remoteobj.Proxy),
    # Obj(reip.util.remote.RemoteProxy),
]

for obj, k in run_test(objs, calls):
    # _ = eval(k, globals())
    _ = getattr(obj.remote, k)()
    assert _ == getattr(obj, k)() or _ == obj.remote
    # print(k, _)
    # cProfile.runctx('obj.remote.{}()'.format(k), globals(), locals())
    # print(k, timeit.timeit('obj.remote.{}()'.format(k), number=1, globals=globals()))
