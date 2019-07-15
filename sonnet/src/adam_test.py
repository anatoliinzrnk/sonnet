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

"""Tests for sonnet.v2.src.adam."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from absl.testing import parameterized
from sonnet.src import adam
from sonnet.src import test_utils
import tensorflow as tf


@parameterized.parameters(adam.Adam, adam.FastAdam)
class AdamTest(test_utils.TestCase, parameterized.TestCase):

  def testDense(self, opt_class):
    parameters = [tf.Variable([1., 2.]), tf.Variable([3., 4.])]
    updates = [tf.constant([5., 5.]), tf.constant([3., 3.])]
    optimizer = opt_class(learning_rate=0.001)
    # Step 1 of Adam
    optimizer.apply(updates, parameters)
    self.assertAllClose([[0.999, 1.999], [2.999, 3.999]],
                        [x.numpy() for x in parameters])
    # Step 2 of Adam
    optimizer.apply(updates, parameters)
    self.assertAllClose([[0.998, 1.998], [2.998, 3.998]],
                        [x.numpy() for x in parameters])
    # Step 3 of Adam
    optimizer.apply(updates, parameters)
    self.assertAllClose([[0.997, 1.997], [2.997, 3.997]],
                        [x.numpy() for x in parameters])

  def testSparse(self, opt_class):
    if self.primary_device in ("GPU", "TPU"):
      self.skipTest("IndexedSlices not supported on {}.".format(
          self.primary_device))

    parameters = [tf.Variable([[1.], [2.]]), tf.Variable([[3.], [4.]])]
    tf_parameters = [tf.Variable([[1.], [2.]]), tf.Variable([[3.], [4.]])]
    updates = [tf.IndexedSlices(tf.constant([0.1], shape=[1, 1]),
                                tf.constant([0]), tf.constant([2, 1])),
               tf.IndexedSlices(tf.constant([0.01], shape=[1, 1]),
                                tf.constant([1]), tf.constant([2, 1]))]
    optimizer = opt_class(learning_rate=0.001)
    # FastAdam doesn't use a raw_op for IndexedSlices so compare against Keras
    tf_optimizer = tf.keras.optimizers.Adam(learning_rate=0.001)
    # Step 1 of Adam
    optimizer.apply(updates, parameters)
    self.assertAllClose([[0.999], [2.0]], parameters[0].numpy())
    self.assertAllClose([[3.0], [3.999]], parameters[1].numpy())
    tf_optimizer.apply_gradients(zip(updates, tf_parameters))
    self.assertAllClose(tf_parameters[0].numpy(), parameters[0].numpy())
    self.assertAllClose(tf_parameters[1].numpy(), parameters[1].numpy())
    # Step 2 of Adam
    optimizer.apply(updates, parameters)
    self.assertAllClose([[0.998], [2.0]], parameters[0].numpy())
    self.assertAllClose([[3.0], [3.998]], parameters[1].numpy())
    tf_optimizer.apply_gradients(zip(updates, tf_parameters))
    self.assertAllClose(tf_parameters[0].numpy(), parameters[0].numpy())
    self.assertAllClose(tf_parameters[1].numpy(), parameters[1].numpy())
    # Step 3 of Adam
    optimizer.apply(updates, parameters)
    self.assertAllClose([[0.997], [2.0]], parameters[0].numpy())
    self.assertAllClose([[3.0], [3.997]], parameters[1].numpy())
    tf_optimizer.apply_gradients(zip(updates, tf_parameters))
    self.assertAllClose(tf_parameters[0].numpy(), parameters[0].numpy())
    self.assertAllClose(tf_parameters[1].numpy(), parameters[1].numpy())

  def testNoneUpdate(self, opt_class):
    parameters = [tf.Variable(1.), tf.Variable(2.)]
    updates = [None, tf.constant(3.)]
    optimizer = opt_class(learning_rate=0.001)
    optimizer.apply(updates, parameters)
    self.assertAllClose(1., parameters[0].numpy())

  def testVariableHyperParams(self, opt_class):
    parameters = [tf.Variable([1., 2.]), tf.Variable([3., 4.])]
    updates = [tf.constant([5., 5.]), tf.constant([3., 3.])]
    learning_rate = tf.Variable(0.001)
    optimizer = opt_class(learning_rate=learning_rate)
    optimizer.apply(updates, parameters)
    self.assertAllClose([[0.999, 1.999], [2.999, 3.999]],
                        [x.numpy() for x in parameters])
    learning_rate.assign(0.1)
    self.assertAlmostEqual(0.1, optimizer.learning_rate.numpy())
    optimizer.apply(updates, parameters)
    self.assertAllClose([[0.899, 1.899], [2.899, 3.899]],
                        [x.numpy() for x in parameters], rtol=1e-4)

  def testHyperParamDTypeConversion(self, opt_class):
    parameters = [tf.Variable([1., 2.]), tf.Variable([3., 4.])]
    updates = [tf.constant([5., 5.]), tf.constant([3., 3.])]
    dtype = tf.float32 if self.primary_device == "TPU" else tf.float64
    learning_rate = tf.Variable(0.001, dtype=dtype)
    beta1 = tf.Variable(0.9, dtype=dtype)
    beta2 = tf.Variable(0.999, dtype=dtype)
    epsilon = tf.Variable(1e-8, dtype=dtype)
    optimizer = opt_class(
        learning_rate=learning_rate, beta1=beta1, beta2=beta2, epsilon=epsilon)
    optimizer.apply(updates, parameters)
    self.assertAllClose([[0.999, 1.999], [2.999, 3.999]],
                        [x.numpy() for x in parameters], rtol=1e-4)

  def testDifferentLengthUpdatesParams(self, opt_class):
    parameters = [tf.Variable([1., 2.]), tf.Variable([3., 4.])]
    updates = [tf.constant([5., 5.])]
    optimizer = opt_class(learning_rate=0.001)
    with self.assertRaisesRegexp(
        ValueError, "`updates` and `parameters` must be the same length."):
      optimizer.apply(updates, parameters)

  def testEmptyParams(self, opt_class):
    optimizer = opt_class(learning_rate=0.001)
    with self.assertRaisesRegexp(ValueError, "`parameters` cannot be empty."):
      optimizer.apply([], [])

  def testAllUpdatesNone(self, opt_class):
    parameters = [tf.Variable(1.), tf.Variable(2.)]
    updates = [None, None]
    optimizer = opt_class(learning_rate=0.001)
    with self.assertRaisesRegexp(
        ValueError, "No updates provided for any parameter"):
      optimizer.apply(updates, parameters)

  def testInconsistentDTypes(self, opt_class):
    parameters = [tf.Variable([1., 2.], name="param0")]
    updates = [tf.constant([5, 5])]
    optimizer = opt_class(learning_rate=0.001)
    with self.assertRaisesRegexp(
        ValueError, "DType of .* is not equal to that of parameter .*param0.*"):
      optimizer.apply(updates, parameters)

  def testMomentVariablesColocatedWithOriginal(self, opt_class):
    optimizer = opt_class(learning_rate=0.001)
    with tf.device("CPU:0"):
      var = tf.Variable(1.0)
    optimizer.apply([tf.constant(0.1)], [var])
    self.assertEqual(optimizer.m[0].device, var.device)
    self.assertEqual(optimizer.v[0].device, var.device)

  def testUnsuppportedStrategyError(self, opt_class):
    strategy = tf.distribute.MirroredStrategy()
    with strategy.scope():
      var = tf.Variable(1.0)
      optimizer = opt_class(learning_rate=0.001)
    step = lambda: optimizer.apply([tf.constant(0.1)], [var])
    with self.assertRaisesRegexp(
        ValueError,
        "Sonnet optimizers are not compatible with `MirroredStrategy`"):
      strategy.experimental_run_v2(step)

if __name__ == "__main__":
  # tf.enable_v2_behavior()
  tf.test.main()
