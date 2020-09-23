# remoteobj
Interacting with objects across processes.

This uses multiprocessing pipes to send messages and operations from the main process to the remote process.

Basically this lets do things like call `.close()` or `.pause()`, or `.ready` on an object that was sent to another process. But it also supports more than that.

## Install

```bash
pip install remoteobj
```

## Basic Usage

```python
import remoteobj

# building some arbitrary object
class Idk(list):
    something = 5
    another = []

obj = Idk()

# creating a remote proxy to interact with
# we want to make sure that the proxy gets
# sent along with it so we can handle remote
# requests.
r_obj = obj.remote = remoteobj.Proxy(obj)

# ... now send obj to mp.Process and start listener thread ...

# then meanwhile back in the *main* process

# call a method
r_obj.append(5)
# now the remote object has 5 appended to it
assert r_obj.passto(len) == 1
# NOTE: this is equivalent to len(obj)


# getting an attribute returns a proxy so you can chain
assert isinstance(r_obj.another.append, remoteobj.Proxy)

# calling will automatically resolve a proxy
r_obj.another.append(6)
# now another == [6]

# you can access keys, but we still allow chaining
# so they're proxies too
assert isinstance(r_obj[0], remoteobj.Proxy)
assert isinstance(r_obj.another[0], remoteobj.Proxy)

# to make the request and get the value, do

assert remoteobj.get( r_obj[0] ) == 5
# or more concisely
assert r_obj[0].__ == 5
# or if you prefer a less witch-y way
assert r_obj[0].get_() == 5

# you can even set keys and attributes on remote objects
r_obj[0] = 6
r_obj.something = 10
```

Now on the remote side:

```python
def run(obj):
    # starts thread which handles main process requests.
    with obj.remote.background_listen():
        # do whatever nonsense you need
        value = 0
        while True:  # do nonsense
            for x in obj:
                value = x * obj.something
            for x, y in zip(obj, obj.another):
                value -= y / x * obj.something
            time.sleep(0.4)
    # after exiting, listening is set to false,
    # clients will fail or return their default
    # immediately because we have notified that
    # we will not be processing any more requests.


# or if you want(/need) to have message handling in the
# main thread, you can handle it manually like this:

def run(obj):
    # indicate that we're listening - no thread this time
    with obj.remote:
        while True:
            ...
            obj.remote.process_requests()

```


## Operations
These are the operations that a remote view can handle, which covers the main ways of accessing information from an object. Let me know if there are others that I'm missing.

NOTE: Any operation that returns a proxy can be chained.

 - **call** (`obj(*a, **kw)`): retrieves return value.
    - to return a proxy instead, do either `Proxy(obj, eager_proxy=True)` to get all as proxies or `obj.method(_proxy=True)` for a one-time thing
 - **getitem** (`obj[key]`): returns proxy
 - **getattr** (`obj.attr`): returns proxy
 - **setitem** (`obj[key] = value`): evaluates
 - **setattr** (`obj.attr = value`): evaluates
 - **passto** (`value(obj)`): pass object to a function
    - e.g. `obj.passto(str)` is equivalent to `str(obj)`
    - you can also pass args: `obj.passto(func, *a, **kw)`

To resolve a proxy, you can do one of three equivalent styles:
 - `remoteobj.get(obj.attr, default=False)` - makes it clearer that `obj.attr` is being sent to the main process
 - `obj.attr.get_(default='asdf')` - access via chaining - convenient, somewhat clear
 - `obj.attr.__` - an attempt at a minimalist interface, doesn't handle default value, not super clear. it's the easiest on the eyes once you know what it means, but I agree that the obscurity is a bit of an issue.

## How it works

We override basic python operators so that they return an object that represents a chain of operations (`Proxy`, `View` objects).
 - `View` objects represents a chain of operations
 - `Proxy` objects represents a chain of operations linked to an object.

When we go to resolve a chain of operations, we
 - first acquire a lock so that the listening state can't change and no other requests can be made at the same time.
 - check if the remote instance is listening
 - we send the set of operations over a pipe and then wait for the value to come out the other side
 - once it returns we check the return values, raise any exception, and return.

On the remote side, we:
 - poll the connection checking for op requests and once we find one:
 - acquire a write lock
 - evaluate the view on the proxy object
 - handle exceptions then place the result and exception in the pipe to be sent back

If there is no listening process, either a default value will be returned (if you provided one via `get_(default=False)`) or a `RuntimeError` will be raised.

It is useful to call `proxy.wait_until_listening()` while the remote process is starting up so that you don't get a `RuntimeError` due to the listener not having started up yet.

If a remote object gets called from the same process as the listening process then it will bypass the pipes and evaluate it directly. This means that if you use threads instead of processes, no data will be sent over pipes.

## Full Example

```python
import time
import multiprocessing as mp
import remoteobj

class SomeObject:
    '''Some object that you want to communicate with.'''
    def __init__(self):
        self.remote = remoteobj.Proxy(self)
        self.x = 0

    def inc(self):
        self.x += 1

    def toggle(self, state=None):
        self.is_on = not self.is_on if state is None else state


def run_remote_stuff(obj, event):
    '''Remote process.'''
    # We are incrementing a counter if a switch
    # is turned on.
    with obj.remote.background_listen():
        while not event.is_set():
            if obj.is_on:
                obj.inc()
            print(obj.x)
            time.sleep(0.1)

def run_local_stuff(obj, duration=10):
    '''Main process.'''
    # We're just switching something on and off.
    t0 = time.time()
    while time.time() - t0 < duration:
        obj.remote.toggle(True)
        time.sleep(2)
        obj.remote.toggle(False)
        time.sleep(2)

# create your object with the remote proxy
obj = SomeObject()

# start remote process
event = mp.Event()
p = mp.Process(target=run_remote_stuff, args=(obj, event))
p.start()
obj.remote.wait_until_listening()

# do things in the meantime
run_local_stuff(obj)
print('done')

# close remote
event.set()
p.join()
```

## Advanced

```python
import remoteobj

class A:
    def __init__(self):
        self.remote = remoteobj.Proxy(self)

    def asdf(self):
        return 5

class B(A):
    x = 0
    def asdf(self):
        return 6

    def chain(self):
        x += 1
        return self

obj = B()
```

#### Accessing super()
```python
# call super method
assert obj.remote.asdf() == 6
assert obj.remote.super.asdf() == 6
```

#### Remote methods that chain
A common pattern is to have a function return self so that you can chain methods together. But that doesn't work when you're sending an object back from another process because it'll get pickled and it'll no longer be the same object.

So there is a special-case - if the return value is self, it will mark it as such and on the other end, it will return the base proxy object.
```python
# remote chaining
assert obj.remote.x.__ == 0  # check start value
assert obj.remote.chain().chain().chain().x.__ == 3

# equivalent to doing this locally
assert obj.x == 0
assert obj.chain().chain().chain().x == 3
```
