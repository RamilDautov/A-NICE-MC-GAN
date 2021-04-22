import time

import numpy as np
import tensorflow as tf
from a_nice_mc.utils.evaluation import acceptance_rate, effective_sample_size, gelman_rubin_diagnostic
from a_nice_mc.utils.hmc import metropolis_hastings_accept
from a_nice_mc.utils.logger import create_logger

logger = create_logger(__name__)


class NormalMonteCarloSampler(object):
    """
    TensorFlow implementation for MCMC where the proposal is a random normal distribution.
    Used for evaluating the `mean` and `std` of a particular energy model.
    """
    def __init__(self, energy_fn, prior, std=1.0,
                 inter_op_parallelism_threads=1, intra_op_parallelism_threads=1):
        self.energy_fn = energy_fn
        self.prior = prior
        self.z = self.energy_fn.z

        def fn(z, x):
            z_ = z + tf.random_normal(tf.shape(self.z), 0.0, std)
            accept = metropolis_hastings_accept(
                energy_prev=energy_fn(z),
                energy_next=energy_fn(z_)
            )
            return tf.where(accept, z_, z)

        self.steps = tf.placeholder(tf.int32, [])
        elems = tf.zeros([self.steps])
        self.z_ = tf.scan(
            fn, elems, self.z, back_prop=False
        )

        self.sess = tf.Session(
            config=tf.ConfigProto(
                inter_op_parallelism_threads=inter_op_parallelism_threads,
                intra_op_parallelism_threads=intra_op_parallelism_threads
            )
        )
        self.sess.run(tf.global_variables_initializer())

    def sample(self, steps, batch_size):
        start = time.time()
        z = self.sess.run(self.z_, feed_dict={self.steps: steps, self.z: self.prior(batch_size)})
        end = time.time()
        logger.info('batches [%d] steps [%d] time [%5.4f] steps/s [%5.4f]' %
                    (batch_size, steps, end - start, steps * batch_size / (end - start)))
        z = np.transpose(z, [1, 0, 2])
        return z


def obtain_statistics(sampler, steps, burn_in, batch_size):
    z = sampler.sample(steps + burn_in, batch_size)
    z_ = z[:, burn_in:]
    z_ = sampler.energy_fn.statistics(z_)

    z = np.reshape(z, [-1, z.shape[-1]])
    z = sampler.energy_fn.statistics(z)

    m = np.mean(z, axis=0, dtype=np.float64)
    s = np.std(z, axis=0, dtype=np.float64)
    logger.info('{}: \n mean {} \n std {} \n acceptance rate: {}'.format(
        sampler.energy_fn.name,
        m,
        s,
        acceptance_rate(z)
    ))

    energy_fn = sampler.energy_fn
    effective_sample_size(
        z_,
        energy_fn.mean(),
        energy_fn.std() * energy_fn.std(),
        logger
    )

    gelman_rubin_diagnostic(
        z_, logger, energy_fn.mean()
    )
