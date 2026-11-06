# -*- coding: utf-8 -*-
"""ClientGraph AI evidence normalization layer."""
from .merge import merge
from .normalize import normalize
from .pipeline import collect

__all__ = ["normalize", "merge", "collect"]
