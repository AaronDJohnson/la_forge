try:
    from uncertainties import ufloat
    from uncertainties.umath import exp, log10
except:
    msg = 'The uncertainties package is required to use'
    msg += ' some of the thermodynamic integration functions.\n'
    msg += 'Please install uncertainties to use these functions.'

try:
    from emcee.autocorr import integrated_time
except:
    msg = 'The emcee package is required to use'
    msg += ' some of the thermodynamic integration functions.\n'
    msg += 'Please install emcee to use these functions.'

from scipy.interpolate import interp1d
import numpy as np
import matplotlib.pyplot as plt

rng = np.random.default_rng()  # instatiate the RNG

__all__ = []

# Generic functions for all BF calculations:

def bootstrap(core, param, num_reals=2000, num_samples=1000):
    """
    Bootstrap samples (with replacement) a 1d array of nearly independent samples,
    giving a representative subsample for each realization. By taking a mean and
    standard deviation of the resulting subsamples, we can get an uncertainty
    estimate.

    Note on number of samples: The number of samples is set at 1000,
    but in general we should plot the histograms and make sure that they
    look like histograms and not random points.

    Input:
        core (*Core): Any core object
        param (str): parameter to bootstrap sample
        num_reals (int) [2000]: number of realizations
        num_samples (int) [1000]: number of samples to use
    Output:
        
    """
    tau = int(integrated_time(core.get_param(param)))
    array = core.get_param(param, thin_by=tau)
    new_array = rng.choice(array, (num_samples, num_reals))
    return new_array

# Thermodynamic integration

def make_betalike(slices_core):
    """
    For use with thermodynamic integration (and BayesWave code).
    Save a file that gives temperatures as column headers with their
    beta * lnlikelihoods in the columns. (beta = 1 / T)

    Note that using Core(chaindir, pt_chains=True, usecols=[-3])
    will save time and memory on your computer.

    Input:
        slices_core (SlicesCore): SlicesCore with pt_chains=True
    Output:
        temps (list): temperatures used for the corresponding column
        betalike (ndarray): beta * lnlike
    """
    # find shortest chain:
    chain_lengths = []
    temps = slices_core.params
    for ii in range(len(temps)):
        chain_lengths.append(len(slices_core.get_param(temps[ii])))
    num_temps = len(chain_lengths)
    min_length = min(chain_lengths)
    betalike = np.zeros((min_length, num_temps))
    for ii in range(len(temps)):
        hot_chain = slices_core.get_param(temps[ii])
        betalike[:, ii] = hot_chain[len(hot_chain) - min_length:]

    return np.array(temps), betalike

def core_to_txt(slices_core, outfile):
    """
    Output a file to be used with BayesWave thermodynamic integration code
    (by Neil Cornish and Tyson Littenberg):
    https://github.com/tlittenberg/thermodynamic_integration

    Input:
        slices_core (SlicesCore): SlicesCore with pt_chains=True
        outfile (str): filepath to save output
    """
    temps, betalike = make_betalike(slices_core)
    temps_str = []
    for ii in range(len(temps)):
        temps_str.append(str(temps[ii]))
    with open(outfile, 'w') as f:
        f.write(' '.join(temps_str))
        f.write('\n')
        np.savetxt(f, betalike)

def ti_bootstrap(betalike, num_chains, num_reals=2000):
    """
    Standard bootstrap with replacement

    Inputs:
        betalike (array): beta * loglikelihoods from find_means
        num_chains (int): number of thermodynamic chains
        num_reals (int): number of realizations to bootstrap
    """
    rng = np.random.default_rng()
    new_means = np.zeros((num_reals, num_chains))
    for ii in range(num_chains):
        tau = int(integrated_time(betalike[:, ii]))
        trimmed_like = betalike[::tau, ii]
        num_samples = int(0.1 * len(trimmed_like))
        new_means[:, ii] = np.mean(rng.choice(betalike[:, ii], (num_reals, num_samples)), axis=1)
    new_means = np.flip(new_means)  # we inverted inv_temps, so this should be too!
    return new_means

def ti_log_evidence(slices_core, verbose=True, iterations=2000,
                    remove_hot=False, plot=False):
    """
    Compute ln(evidence) of chains of several different temperatures.

    Input:
        core (Core): Core containing pt_chains
        verbose (bool) [True]: get more info
        iterations (int) [2000]: number of iterations to use to get error estimate
        remove_hot (bool) [False]: if a hot chain exists (T=1e80), remove it

    Return:
        ln_Z (float): natural logarithm of the evidence
        total_unc (float): uncertainty in the natural logarithm of the evidence
    """
    temps, betalike = make_betalike(slices_core)
    inv_temps = 1 / temps[::-1]
    num_chains = len(inv_temps)
    new_means = ti_bootstrap(betalike, num_chains=num_chains, num_reals=iterations)

    if plot:
        plt.figure(figsize=(12, 5))
        for ii in range(iterations):
            plt.loglog(inv_temps, new_means[ii, :])
        plt.xlim([1e-10, 1])
        plt.show()
        plt.clf()

    ln_Z_arr = np.zeros(iterations)

    x = np.log10(inv_temps)  # interpolate on a log(inv_temp) scale
    x_new = np.linspace(x[0], x[-1], num=10000)  # new interpolated points
    for ii in range(iterations):
        y = new_means[ii, :]
        y_spl = interp1d(x, y)
        if plot:
            plt.plot(x_new, y_spl(x_new))
            plt.plot(x, y, 'o')
        ln_Z = np.trapz(y_spl(x_new), 10**(x_new))
        ln_Z_arr[ii] = ln_Z

    ln_Z = np.mean(ln_Z_arr)
    total_unc = np.std(ln_Z_arr)

    if verbose:
        print()
        print('model:')
        print('ln(evidence) =', ln_Z)
        print('error in ln_Z =', total_unc)
        print()
    return ln_Z, total_unc

# generic function to propagate uncertainties:

def log10_bf(log_ev1, log_ev2, scale='log10'):
    """
    Compute log10(Bayes factor) comparing (model 2 / model 1)
    Input:
        log_ev1 (tuple): log10 evidence from model 1
        log_ev2 (tuple): log10 evidence from model 2
        scale (str): [log10] pick values to return from (log10, log, 1)

    Return:
        log10_bf (tuple): log10 Bayes factor
    """
    log_evidence1 = ufloat(log_ev1)
    log_evidence2 = ufloat(log_ev2)
    log_bf = log_evidence2 - log_evidence1
    bf = exp(log_bf)
    log10_bf = log10(bf)
    if scale == 'log':
        return log_bf.n, log_bf.s
    elif scale == '1':
        return bf.n, bf.s
    elif scale == 'log10':
        return log10_bf.n, log10_bf.s

# HyperModel BF calculation with bootstrap:

def odds_ratio_bootstrap(hmcore, num_reals=2000, domains=([-0.5, 0.5], [0.5, 1.5])):
    """
    Standard bootstrap with replacement for product space odds ratios

    Inputs:
        hmcore (HyperModelCore): HyperModelCore object
        num_reals (int): number of realizations to bootstrap
        domains (tuple): tuple of model domains on the nmodel param
                         default: ([-0.5, 0.5], [0.5, 1.5])
                         modify this to e.g. ([0.5, 1.5], [-0.5, 0.5]) to
                             compute the BF the other way around
    Outputs:
        mean(ors) (float): average of the odds ratios given by bootstrap
        std(ors) (float): std of the odds ratios given by bootstrap
    """
    nmodel = hmcore.get_param('nmodel')
    rng = np.random.default_rng()
    bfs = np.zeros((num_reals))
    tau = int(integrated_time(nmodel))
    thinned_nmodel = nmodel[::tau]
    num_samples = int(0.1 * len(thinned_nmodel))
    new_nmodels = rng.choice(nmodel, (num_reals, num_samples))
    ors = np.zeros(new_nmodels.shape[0])
    for ii in range(num_reals):
        ors[ii] = (len(np.where((new_nmodels[ii, :] > domains[0][0]) & (new_nmodels[ii, :] <= domains[0][1]))[0]) /
                   len(np.where((new_nmodels[ii, :] > domains[1][0]) & (new_nmodels[ii, :] <= domains[1][1]))[0]))
    return np.mean(ors), np.std(ors)

