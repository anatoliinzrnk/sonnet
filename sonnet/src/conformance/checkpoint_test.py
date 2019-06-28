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

"""Tests checkpointing with Sonnet."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os

from absl import logging
from absl.testing import absltest
from absl.testing import parameterized
from sonnet.src import replicator as snt_replicator
from sonnet.src import test_utils
from sonnet.src.conformance import goldens
import tensorflow as tf


class TestCheckpoint(object):
  """Wraps a tf.train.Checkpoint to make it more convenient for testing."""

  def __init__(self, golden=None, **kwargs):
    if golden is None:
      root = absltest.get_default_test_tmpdir()
    else:
      root = os.path.join(
          "sonnet/src/conformance/checkpoints/",
          golden.name)
    self._root = root
    self._prefix = os.path.join(self._root, "checkpoint")
    self._checkpoint = tf.train.Checkpoint(**kwargs)

  def save(self):
    self._checkpoint.save(file_prefix=self._prefix)

  def restore_latest(self, assert_consumed):
    status = self._checkpoint.restore(tf.train.latest_checkpoint(self._root))
    if assert_consumed:
      # Ensures that all values in the checkpoint have been consumed by some
      # checkpointable Python object.
      status.assert_consumed()
    return status


# TODO(petebu) Fix these tests for `TpuReplicator`.
def replicator_all_devices(device_type):
  # NOTE: The explicit device list is required since currently Replicator
  # only considers CPU and GPU devices. This means on TPU by default we only
  # mirror on the local CPU.
  devices = tf.config.experimental.list_logical_devices(device_type=device_type)
  devices = [d.name for d in devices]
  logging.info("Replicating over %s", devices)
  return snt_replicator.Replicator(devices=devices)


def with_soft_placement(f):
  """Wraps `f` such that it runs with soft device placement."""
  def wrapper(*a, **k):
    with tf.device(None):
      return f(*a, **k)
  return wrapper


class GoldenCheckpointsTest(test_utils.TestCase, parameterized.TestCase):
  """Adds test methods running standard checkpointing tests."""

  @goldens.all_goldens
  def test_save_load(self, golden):
    """Test a basic save/load cycle."""
    module = golden.create_module()
    checkpoint = TestCheckpoint(module=module)
    all_variables = golden.create_all_variables(module)

    # Save zeros into the checkpoint.
    self.assertNotEmpty(all_variables)
    self.assertEqual(set(all_variables), set(module.variables))
    for variable in all_variables:
      # TODO(tomhennigan) Perhaps limit the range/switch to random to avoid
      # overflow/underflow in the forward pass?
      variable.assign(goldens.range_like(variable))
    checkpoint.save()
    old_y = golden.forward(module)

    # Overwrite zeros with ones.
    for variable in all_variables:
      variable.assign(tf.ones_like(variable))

    # Check restored values match the saved values.
    checkpoint.restore_latest(assert_consumed=True)
    for variable in all_variables:
      self.assertAllClose(variable.read_value(), goldens.range_like(variable),
                          msg=variable.name)

    # Test the output from the module remains stable.
    # TODO(tomhennigan) Handle modules with nested outputs.
    if golden.deterministic:
      self.assertAllClose(golden.forward(module), old_y)

  @goldens.all_goldens
  def test_save_then_load_new_instance(self, golden):
    """Checks that a checkpoint created for one instance can restore another."""
    module_1 = golden.create_module()
    checkpoint_1 = TestCheckpoint(module=module_1)
    variables_1 = golden.create_all_variables(module_1)

    module_2 = golden.create_module()
    checkpoint_2 = TestCheckpoint(module=module_2)
    variables_2 = golden.create_all_variables(module_2)

    for v1, v2 in zip(variables_1, variables_2):
      v1.assign(goldens.range_like(v1))
      v2.assign(tf.ones_like(v2))

    checkpoint_1.save()
    checkpoint_2.restore_latest(assert_consumed=True)

    # Assert the parameters in both modules are the same.
    for variable in variables_2:
      self.assertAllClose(variable.read_value(), goldens.range_like(variable),
                          msg=variable.name)

    # Assert the output from both modules are the same.
    # TODO(tomhennigan) Handle modules with nested outputs.
    if golden.deterministic:
      self.assertAllClose(golden.forward(module_1), golden.forward(module_2))

  @goldens.all_goldens
  def test_restore_on_create(self, golden):
    """Tests that Variable values are restored on creation."""
    # Create a module, set its variables to sequential values and save.
    module_1 = golden.create_module()
    checkpoint_1 = TestCheckpoint(module=module_1)
    variables_1 = golden.create_all_variables(module_1)
    for variable in variables_1:
      variable.assign(goldens.range_like(variable))
    checkpoint_1.save()
    golden.forward(module_1)

    # Create a different module, restore from a checkpoint, create parameters
    # and assert their values are sequential.
    module_2 = golden.create_module()
    checkpoint_2 = TestCheckpoint(module=module_2)
    status = checkpoint_2.restore_latest(assert_consumed=False)
    variables_2 = golden.create_all_variables(module_2)
    status.assert_consumed()
    for var1, var2 in zip(variables_1, variables_2):
      self.assertAllEqual(var1.read_value(), var2.read_value(),
                          msg=var1.name)

    # Assert the output from both modules is the same.
    # TODO(tomhennigan) Handle modules with nested outputs.
    if golden.deterministic:
      self.assertAllClose(golden.forward(module_1), golden.forward(module_2))

  @goldens.all_goldens
  def test_restore_golden(self, golden):
    """Test restoring from a golden checkpoint still works."""
    module = golden.create_module()
    checkpoint = TestCheckpoint(golden=golden, module=module)
    variables = golden.create_all_variables(module)
    for variable in variables:
      variable.assign(tf.zeros_like(variable))
    checkpoint.restore_latest(assert_consumed=True)
    for variable in variables:
      self.assertAllEqual(variable.read_value(), goldens.range_like(variable),
                          msg=variable.name)


class ReplicatorCheckpointTest(test_utils.TestCase, parameterized.TestCase):

  @goldens.all_goldens
  def test_checkpoint_replicator(self, golden):
    replicator = replicator_all_devices(self.primary_device)
    self.assertCheckpointWithReplicator(golden, replicator, use_function=False)

  @goldens.all_goldens
  def test_checkpoint_replicator_function(self, golden):
    replicator = replicator_all_devices(self.primary_device)
    self.assertCheckpointWithReplicator(golden, replicator, use_function=True)

  @goldens.all_goldens
  def test_checkpoint_tpu_replicator(self, golden):
    if self.primary_device != "TPU":
      self.skipTest("Test requires a TPU")

    replicator = snt_replicator.TpuReplicator()
    self.assertCheckpointWithReplicator(golden, replicator, use_function=True)

  def assertCheckpointWithReplicator(self, golden, replicator, use_function):
    self.assertSaveRestore(golden, replicator, use_function)
    self.assertRestoreFromGolden(golden, replicator)
    self.assertRestoreFromNonDistributed(golden, replicator, use_function)
    self.assertRestoreOnCreate(golden, replicator)
    if self.primary_device != "TPU":
      # TODO(b/130555244) Enable on TPU when functions can create variables.
      self.assertRestoreOnCreateInReplicaContext(golden, replicator,
                                                 use_function)

  def assertSaveRestore(self, golden, replicator, use_function):
    with replicator.scope():
      module = golden.create_module()
      variables = golden.create_all_variables(module)

    def forward():
      per_replica = replicator.experimental_run_v2(
          lambda: golden.forward(module))
      return tf.stack(replicator.unwrap(per_replica), axis=0)

    if use_function:
      forward = tf.function(forward)
      if self.primary_device == "TPU":
        # TODO(b/132329316) Remove when `xla.compile` allows tf.device(TPU).
        forward = with_soft_placement(forward)

    # Assign sequential values to the weights.
    for index, variable in enumerate(variables):
      variable.assign(goldens.range_like(variable, start=index))

    # Create a checkpoint and save the weights.
    checkpoint = TestCheckpoint(module=module)
    checkpoint.save()

    # Compute a forward pass of the previously saved module.
    before_save_ys = forward()

    # Assign different values into the weights and do another forward pass. The
    # result should be different.
    for variable in variables:
      variable.assign(-tf.ones_like(variable))

    if golden.deterministic:
      y = forward()
      self.assertNotAllClose(y, before_save_ys)

    # Restore from the checkpoint and assert the module is in the same state.
    checkpoint.restore_latest(assert_consumed=True)

    for index, variable in enumerate(variables):
      # Parameters should be restored to their previous values.
      self.assertAllEqual(variable.read_value(),
                          goldens.range_like(variable, start=index),
                          msg=variable.name)

    if golden.deterministic:
      self.assertAllEqual(forward(), before_save_ys)

  def assertRestoreFromGolden(self, golden, replicator):
    with replicator.scope():
      module = golden.create_module()
      variables = golden.create_all_variables(module)
    checkpoint = TestCheckpoint(golden=golden, module=module)
    checkpoint.restore_latest(assert_consumed=True)
    for variable in variables:
      self.assertAllEqual(variable.read_value(), goldens.range_like(variable),
                          msg=variable.name)

  def assertRestoreFromNonDistributed(self, golden, replicator, use_function):
    # Save a checkpoint from a non-distributed model.
    module = golden.create_module()
    normal_variables = golden.create_all_variables(module)
    for index, variable in enumerate(normal_variables):
      variable.assign(goldens.range_like(variable, start=(index + 1)))
    checkpoint = TestCheckpoint(module=module)
    checkpoint.save()

    # Create the same model (new params) in the replicator scope.
    with replicator.scope():
      module2 = golden.create_module()
      replicator_variables = golden.create_all_variables(module2)

    # Ensure the distributed params are != the values in the checkpoint.
    for normal, distributed in zip(normal_variables, replicator_variables):
      distributed.assign(tf.zeros_like(distributed))
      self.assertNotAllClose(normal.read_value(), distributed.read_value())

    # Restore the checkpoint and ensure the parameters are the same.
    checkpoint = TestCheckpoint(module=module2)
    checkpoint.restore_latest(assert_consumed=True)

    for normal, distributed in zip(normal_variables, replicator_variables):
      self.assertAllEqual(normal.read_value(), distributed.read_value(),
                          msg=normal.name)

    if golden.deterministic:

      def run_forward(module):
        forward = lambda: golden.forward(module)
        if use_function:
          forward = tf.function(forward)
          if self.primary_device == "TPU":
            # TODO(b/132329316) Remove when `xla.compile` allows tf.device(TPU).
            forward = with_soft_placement(forward)
        return forward()

      y_before = run_forward(module)
      y_after = run_forward(module2)
      self.assertAllEqual(y_before, y_after)

  def assertRestoreOnCreate(self, golden, replicator):
    # Save a checkpoint from a non-distributed model.
    module = golden.create_module()
    normal_variables = golden.create_all_variables(module)
    for index, variable in enumerate(normal_variables):
      variable.assign(goldens.range_like(variable, start=(index + 1)))
    checkpoint = TestCheckpoint(module=module)
    checkpoint.save()
    golden.forward(module)

    # Create the same model (new params) in the replicator scope.
    with replicator.scope():
      module = golden.create_module()
      checkpoint = TestCheckpoint(module=module)
      status = checkpoint.restore_latest(assert_consumed=False)
      golden.forward(module)
      status.assert_consumed()
      replicator_variables = module.variables

    for normal, distributed in zip(normal_variables, replicator_variables):
      self.assertAllEqual(normal.read_value(), distributed.read_value(),
                          msg=normal.name)

  def assertRestoreOnCreateInReplicaContext(self, golden, replicator,
                                            use_function):
    if self.primary_device == "GPU":
      self.skipTest("Currently not working as expected on multiple devices")
      # TODO(b/134376796) renable this once bug is fixed

    # Save a checkpoint from a non-distributed model.
    module = golden.create_module()
    normal_variables = golden.create_all_variables(module)
    for index, variable in enumerate(normal_variables):
      variable.assign(goldens.range_like(variable, start=(index + 1)))
    checkpoint = TestCheckpoint(module=module)
    checkpoint.save()
    golden.forward(module)

    with replicator.scope():
      module = golden.create_module()

    def forward():
      return replicator.experimental_run_v2(lambda: golden.forward(module))

    if use_function:
      forward = tf.function(forward)
      if self.primary_device == "TPU":
        # TODO(b/132329316) Remove when `xla.compile` allows tf.device(TPU).
        forward = with_soft_placement(forward)

    checkpoint = TestCheckpoint(module=module)
    status = checkpoint.restore_latest(assert_consumed=False)
    result = forward()
    status.assert_consumed()

    if golden.deterministic:
      result_iter = iter(replicator.experimental_local_results(result))
      first_replica = next(result_iter)
      for next_replica in result_iter:
        self.assertAllEqual(first_replica, next_replica)

    replicator_variables = module.variables
    for normal, distributed in zip(normal_variables, replicator_variables):
      self.assertAllEqual(normal.read_value(), distributed.read_value(),
                          msg=normal.name)


def setUpModule():
  # If a physical GPU is available make sure TF sees at least two.
  gpus = tf.config.experimental.list_physical_devices(device_type="GPU")
  if len(gpus) == 1:
    logging.info("Splitting one physical GPU into two logical GPUs.")
    tf.config.experimental.set_virtual_device_configuration(
        gpus[0],
        [tf.config.experimental.VirtualDeviceConfiguration(memory_limit=1024),
         tf.config.experimental.VirtualDeviceConfiguration(memory_limit=1024)])

if __name__ == "__main__":
  # tf.enable_v2_behavior()
  tf.test.main()
