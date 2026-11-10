import math


def sample_actual_duration(planned, rng, sigma=0.25):
    """Overrun model: lognormal around the planned duration.

    The mu shift keeps the average actual duration equal to the planned one,
    so some surgeries run long and some short. Never shorter than 1 minute.
    """
    mu = math.log(planned) - sigma ** 2 / 2
    return max(1, round(rng.lognormvariate(mu, sigma)))