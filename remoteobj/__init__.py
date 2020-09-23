from .view import *
from .core import *
from .util import *


def get(view, **kw):
    return view.get_(**kw)
