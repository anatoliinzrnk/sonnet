# Copyright 2019 The Sonnet Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or  implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================

"""Base Sonnet module."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import abc
import functools
import inspect
import pprint
import sys

import six
from sonnet.src import utils
import tensorflow as tf

NO_MODULE_NAME_SCOPE = "__no_module_name_scope__"
TFFunctionType = type(tf.function(lambda: None, autograph=False))  # pylint: disable=invalid-name


def no_name_scope(method):
  """Decorator to wrap a method, preventing automatic name scope wrapping.

  By default, any method on a module is considered as a forwards function, and
  so any variables / modules created by the method will be scoped as belonging
  to the module. In some cases this is undesirable, for example when
  implementing .clone() / .transpose(), as in those cases we want the new
  module to have the scope of wherever the .transpose() call is made. To
  allow this, decorate any methods with `no_module_name_scope`.

  This logic is tied to ModuleMetaclass.__new__, if anything is
  changed here corresponding changes will be needed there.

  Args:
    method: the method to wrap.

  Returns:
    The method, with a flag indicating no name scope wrapping should occur.
  """
  setattr(method, NO_MODULE_NAME_SCOPE, True)
  return method


class ModuleMetaclass(abc.ABCMeta):
  """Metaclass for `tf.Module`."""

  def __new__(mcs, name, bases, clsdict):
    methods = []

    for key, value in clsdict.items():
      if key == "name_scope":
        continue

      elif key.startswith("__") and key != "__call__":
        # Don't patch methods like `__getattr__` or `__del__`.
        continue

      elif isinstance(value, property):
        # TODO(tomhennigan) Preserve the type of property subclasses.
        clsdict[key] = property(
            value.fget if not value.fget else with_name_scope(value.fget),
            value.fset if not value.fset else with_name_scope(value.fset),
            value.fdel if not value.fdel else with_name_scope(value.fdel),
            doc=value.__doc__)

      elif inspect.isfunction(value) or isinstance(value, TFFunctionType):
        # We defer patching methods until after the type is created such that we
        # can trigger the descriptor binding them to the class.
        methods.append(key)

    clsdict.setdefault(
        "__repr__",
        lambda module: module._auto_repr)  # pylint: disable=protected-access

    cls = super(ModuleMetaclass, mcs).__new__(mcs, name, bases, clsdict)

    for method_name in methods:
      # Note: the below is quite subtle, we need to ensure that we're wrapping
      # the method bound to the class. In some cases (e.g. `wrapt`) this is
      # important since the method can trigger different behavior when it is
      # bound (e.g. in wrapt `FunctionWrapper.__get__(None, cls)` produces a
      # `BoundFunctionWrapper` which in turn populates the `instance` argument
      # to decorator functions using args[0]).
      # Equivalent to: `cls.__dict__[method_name].__get__(None, cls)`
      method = getattr(cls, method_name)
      method = with_name_scope(method)
      setattr(cls, method_name, method)

    return cls

  def __call__(cls, *args, **kwargs):
    # Call new such that we have an un-initialized module instance that we can
    # still reference even if there is an exception during __init__. This is
    # needed such that we can make sure the name_scope constructed in __init__
    # is closed even if there is an exception.
    module = cls.__new__(cls, *args, **kwargs)

    # Now attempt to initialize the object.
    try:
      module.__init__(*args, **kwargs)
    except:
      # We must explicitly catch so that in Python 2 sys.exc_info() is populated
      # before entering the finally block.
      raise
    else:
      module._auto_repr = auto_repr(cls, *args, **kwargs)  # pylint: disable=protected-access
    finally:
      # The base Module constructor enters the modules name scope before
      # returning such that other functionality in the ctor happens within the
      # modules name scope.
      scope = getattr(module, "_ctor_name_scope", None)
      exc_info = sys.exc_info()
      if scope is None:
        if exc_info[0] is None:
          raise ValueError(
              "Constructing a snt.Module without calling the super constructor "
              "is not supported. Add the following as the first line in your "
              "__init__ method:\n\n"
              "super(%s, self).__init__()" % cls.__name__)
      else:
        scope.__exit__(*exc_info)
        del module._ctor_name_scope

    return module


def auto_repr(cls, *args, **kwargs):
  """Derive a `__repr__` from constructor arguments of a given class.

  >>> class Foo(object):
  ...   def __init__(self, x, y=42):
  ...      pass
  ...
  >>> auto_repr(Foo, "x")
  "Foo(x='x')"

  >>> auto_repr(Foo, "x", 21)
  "Foo(x='x', y=21)"

  Args:
    cls: a class to derive `__repr__` for.
    *args: positional arguments.
    **kwargs: keyword arguments.

  Returns:
    A string representing a call equivalent to `cls(*args, **kwargs)`.
  """
  argspec = inspect.getargspec(cls.__init__)
  arg_names = argspec.args
  # Keep used positionals minus self.
  arg_names = arg_names[1:(len(args) + 1)]
  # Keep used kwargs in the order they appear in argspec.
  arg_names.extend(n for n in argspec.args if n in kwargs)
  arg_values = inspect.getcallargs(cls.__init__, None, *args, **kwargs)

  names_and_values = [(name + "=", arg_values[name]) for name in arg_names]
  # Add varargs.
  names_and_values.extend(("", arg) for arg in args[len(argspec.args) - 1:])
  # Add varkwargs.
  names_and_values.extend(
      (name + "=", kwargs[name]) for name in kwargs if name not in argspec.args)

  single_line = cls.__name__ + "({})".format(", ".join(
      name + repr(value) for name, value in names_and_values))
  if len(single_line) <= 80:
    return single_line
  else:
    return "{}(\n{},\n)".format(
        cls.__name__,
        indent(4, ",\n".join(fancy_repr(n, v) for n, v in names_and_values)))


def fancy_repr(name, value):
  repr_value = pprint.pformat(value)
  if name:
    repr_value = indent(len(name), repr_value).strip()
  return name + repr_value


def indent(amount, s):
  """Indents `s` with `amount` spaces."""
  prefix = amount * " "
  return "\n".join(prefix + line for line in s.splitlines())


@utils.decorator
def wrap_with_name_scope(method, instance, args, kwargs):
  """Decorator that calls the given function in the module name scope.

  Args:
    method: The bound method to call.
    instance: Module instance.
    args: Positional arguments to `method`.
    kwargs: Keyword arguments to `method`.

  Returns:
    `with instance.name_scope: return method(*args, **kwargs)`
  """
  if instance is None:
    instance = args[0]
    args = args[1:]
    method = functools.partial(method, instance)

  try:
    module_name_scope = instance.name_scope
  except AttributeError as exc_value_from:
    exc_value = AttributeError(
        "The super constructor must be called before any other methods in "
        "your constructor. If this is not possible then annotate all the "
        "methods called with `@snt.no_module_name_scope`.")
    six.raise_from(exc_value, exc_value_from)

  with module_name_scope:
    # snt.Module enters the module name scope for all methods. To disable this
    # for a particular method annotate it with `@snt.no_module_name_scope`.
    return method(*args, **kwargs)


@utils.decorator
def wrap_with_name_scope_no_exception(method, instance, args, kwargs):
  """Patches the given method so it enters the modules name scope."""
  if instance is None:
    instance = args[0]
    args = args[1:]
    method = functools.partial(method, instance)

  with instance.name_scope:
    # snt.Module enters the module name scope for all methods. To disable this
    # for a particular method annotate it with `@snt.no_module_name_scope`.
    return method(*args, **kwargs)


def with_name_scope(method):
  """Patches the given method so it enters the modules name scope."""
  if getattr(method, NO_MODULE_NAME_SCOPE, False):
    # The function has been annotated to say that no autoscoping should be
    # applied, so do not patch it.
    return method

  if isinstance(method, TFFunctionType):
    # Autograph cannot convert functions that have try/catch.
    method._decorate(wrap_with_name_scope_no_exception)  # pylint: disable=protected-access
    return method
  else:
    return wrap_with_name_scope(method)  # pylint: disable=no-value-for-parameter


class Module(six.with_metaclass(ModuleMetaclass, tf.Module)):
  """Base class for Sonnet modules.

  A Sonnet module is a lightweight container for variables and other modules.
  Modules typically define one or more "forward" methods (e.g. `__call__`) which
  apply operations combining user input and module parameters. For example:

  >>> class MultiplyModule(snt.Module):
  ...   def __call__(self, x):
  ...     if not hasattr(self, 'w'):
  ...       self.w = tf.Variable(2., name='w')
  ...     return x * self.w

  >>> mod = MultiplyModule()
  >>> mod(1.)
  <tf.Tensor: ... numpy=2.0>
  """

  def __init__(self, name=None):
    super(Module, self).__init__(name=name)

    # Enter the name scope so subsequent code in the contructor (e.g. creating
    # submodules) happens inside the modules name scope. This is exited when
    # the subclass __init__ returns (this is implemented in ModuleMetaclass).
    self._ctor_name_scope = self.name_scope
    self._ctor_name_scope.__enter__()
