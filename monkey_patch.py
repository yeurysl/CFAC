# monkey_patch.py

import collections
import collections.abc

# Ensure these legacy attributes exist in the collections module.
if not hasattr(collections, 'MutableSet'):
    collections.MutableSet = collections.abc.MutableSet
if not hasattr(collections, 'Iterable'):
    collections.Iterable = collections.abc.Iterable
if not hasattr(collections, 'Mapping'):
    collections.Mapping = collections.abc.Mapping
import collections
import collections.abc

# Monkey patch for compatibility with Python 3.10+:
collections.MutableMapping = collections.abc.MutableMapping
collections.MutableSet = collections.abc.MutableSet