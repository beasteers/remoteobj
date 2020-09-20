from .view import *
from .core import *


def get(view, **kw):
    return view.get_(**kw)
