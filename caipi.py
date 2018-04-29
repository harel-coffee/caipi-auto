#!/usr/bin/env python3

import numpy as np
from sklearn.utils import check_random_state
from sklearn.model_selection import StratifiedKFold, StratifiedShuffleSplit
from os.path import join

from caipi import *


PROBLEMS = {
    'toy-fst': lambda *args, **kwargs: \
            ToyProblem(*args, rule='fst', **kwargs),
    'toy-lst': lambda *args, **kwargs: \
            ToyProblem(*args, rule='lst', **kwargs),
    'colors-rule0': lambda *args, **kwargs: \
            ColorsProblem(*args, rule=0, **kwargs),
    'colors-rule1': lambda *args, **kwargs: \
            ColorsProblem(*args, rule=1, **kwargs),
    'sudoku': SudokuProblem,
    'newsgroups': lambda *args, **kwargs: \
            NewsgroupsProblem(*args,
                              classes=['sci.electronics', 'sci.med'],
                              **kwargs),
    'reviews': ReviewsProblem,
    'mnist': MNISTProblem,
    'fashion': FashionProblem,
}


LEARNERS = {
    'lr': lambda *args, **kwargs: \
            LinearLearner(*args, model='lr', **kwargs),
    'svm': lambda *args, **kwargs: \
            LinearLearner(*args, model='svm', **kwargs),
    'l1svm': lambda *args, **kwargs: \
            LinearLearner(*args, model='l1svm', **kwargs),
    'polysvm': lambda *args, **kwargs: \
            LinearLearner(*args, model='polysvm', **kwargs),
    'gp': GPLearner,
}


def _get_basename(args):
    basename = '__'.join([args.problem, args.learner, args.strategy])
    fields = [
        ('k', args.n_folds),
        ('n', args.n_examples),
        ('p', args.prop_known),
        ('P', args.prop_eval),
        ('T', args.max_iters),
        ('e', args.eval_iters),
        ('E', args.start_expl_at),
        ('F', args.n_features),
        ('S', args.n_samples),
        ('K', args.kernel_width),
        ('R', args.lime_repeats),
        ('s', args.seed),
    ]
    basename += '__' + '__'.join([name + '=' + str(value)
                                  for name, value in fields])
    return join('results', basename)


def _subsample(problem, examples, prop, rng=None):
    rng = check_random_state(rng)

    classes = sorted(set(problem.y))
    if 0 <= prop <= 1:
        n_sampled = int(round(len(examples) * prop))
        n_sampled_per_class = max(n_sampled // len(classes), 3)
    else:
        n_sampled_per_class = max(int(prop), 3)

    sample = []
    for y in classes:
        examples_y = np.array([i for i in examples if problem.y[i] == y])
        pi = rng.permutation(len(examples_y))
        sample.extend(examples_y[pi[:n_sampled_per_class]])

    return list(sample)


def eval_passive(problem, args, rng=None):
    """Useful for checking the based performance of the learner and whether
    the explanations are stable."""

    rng = check_random_state(rng)
    basename = _get_basename(args)

    folds = StratifiedShuffleSplit(n_splits=args.n_folds, random_state=0) \
                .split(problem.y, problem.y)
    train_examples, test_examples = list(folds)[0]
    eval_examples = _subsample(problem, test_examples,
                               args.prop_eval, rng=0)
    print('#train={} #test={} #eval={}'.format(
        len(train_examples), len(test_examples), len(eval_examples)))

    print('  #explainable in train', len(set(train_examples) & problem.explainable))
    print('  #explainable in eval', len(set(eval_examples) & problem.explainable))

    learner = LEARNERS[args.learner](problem, strategy=args.strategy, rng=0)
    #learner.select_model(problem.X[train_examples],
    #                     problem.y[train_examples])
    learner.fit(problem.X[train_examples],
                problem.y[train_examples])
    train_params = learner.get_params()

    print('Computing full-train performance...')
    perf = problem.eval(learner, train_examples,
                        test_examples, eval_examples,
                        t='train', basename=basename)
    print('perf on full training set =', perf)

    print('Checking LIME stability...')
    perf = problem.eval(learner, train_examples,
                        test_examples, eval_examples,
                        t='train2', basename=basename)
    print('perf on full training set =', perf)

    try:
        print('Computing expl-as-doc performance...')
        expl2doc = lambda expl: ' '.join([word for word, _ in expl])

        explanations_as_docs = [expl2doc(problem.explanations[i])
                                for i in train_examples]
        X_explanations = problem.vectorizer.transform(explanations_as_docs)
        #learner.select_model(X_explanations,
        #                     problem.y[train_examples])
        learner.fit(X_explanations,
                    problem.y[train_examples])
        perf = problem.eval(learner, train_examples,
                            test_examples, eval_examples,
                            t='train', basename=basename)
        print('perf on expl-as-doc set =', perf)
    except:
        pass

    print('Computing corrections for {} examples...'.format(len(train_examples)))
    X_test_tuples = {tuple(densify(problem.X[i]).ravel())
                     for i in test_examples}

    X_corr, y_corr = None, None
    expl_train_examples = set(train_examples) & problem.explainable
    for j, i in enumerate(expl_train_examples):
        print('  correcting {:3d} / {:3d}'.format(j + 1, len(expl_train_examples)))
        x = densify(problem.X[i])
        pred_y = learner.predict(x)[0]
        pred_expl = problem.explain(learner, train_examples, i, pred_y)
        X_corr, y_corr = problem.query_corrections(X_corr, y_corr, i, pred_y, pred_expl, X_test_tuples)

    if X_corr is None:
        print('no corrections were obtained')
        return
    print(X_corr.shape[0], 'corrections obtained')

    print('Computing corr performance...')
    corr_params = None
    if np.min(y_corr) != np.max(y_corr):
        #learner.select_model(X_corr, y_corr)
        learner.fit(X_corr, y_corr)
        corr_params = learner.get_params()
        perf = problem.eval(learner, train_examples,
                            test_examples, eval_examples,
                            t='corr', basename=basename)
    print('perf on corr only =', perf)

    print('Computing train+corr performance...')
    X_train_corr = vstack([problem.X[train_examples], X_corr])
    y_train_corr = hstack([problem.y[train_examples], y_corr])
    #learner.select_model(X_train_corr, y_train_corr)
    learner.fit(X_train_corr, y_train_corr)
    train_corr_params = learner.get_params()
    perf = problem.eval(learner, train_examples,
                        test_examples, eval_examples,
                        t='train+corr', basename=basename)
    print('perf on train+corr set =', perf)

    print('w_train        :\n', train_params)
    print('w_corr         :\n', corr_params)
    print('w_{train+corr} :\n', train_corr_params)

    dump(basename + '_passive_models.pickle', {
            'w_train': train_params,
            'w_corr': corr_params,
            'w_both': train_corr_params
        })


def caipi(problem,
          learner,
          train_examples,
          known_examples,
          test_examples,
          eval_examples,
          max_iters=100,
          start_expl_at=-1,
          eval_iters=10,
          basename=None,
          rng=None):
    rng = check_random_state(rng)

    print('CAIPI T={} #train={} #known={} #test={} #eval={}'.format(
          max_iters,
          len(train_examples), len(known_examples),
          len(test_examples), len(eval_examples)))
    print('  #explainable in train', len(set(train_examples) & problem.explainable))
    print('  #explainable in eval', len(set(eval_examples) & problem.explainable))

    X_test_tuples = {tuple(densify(problem.X[i]).ravel())
                     for i in test_examples}

    #learner.select_model(problem.X[train_examples],
    #                     problem.y[train_examples])
    #learner.fit(problem.X[train_examples],
    #            problem.y[train_examples])
    #perf = problem.eval(learner,
    #                    train_examples,
    #                    test_examples,
    #                    eval_examples,
    #                    t='train',
    #                    basename=basename)
    #params = np.round(learner.get_params(), decimals=1)
    #print('train model = {params}, perfs = {perf}'.format(**locals()))

    learner.select_model(problem.X[known_examples],
                         problem.y[known_examples])
    learner.fit(problem.X[known_examples],
                problem.y[known_examples])

    perfs, params = [], []
    X_corr, y_corr = None, None
    for t in range(max_iters):

        if len(known_examples) >= len(train_examples):
            break

        unknown_examples = set(train_examples) - set(known_examples)
        i = learner.select_query(problem, unknown_examples & problem.explainable)
        assert i in train_examples and i not in known_examples
        x = densify(problem.X[i])

        explain = 0 <= start_expl_at <= t

        pred_y = learner.predict(x)[0]
        pred_expl = problem.explain(learner, known_examples, i, pred_y) \
                    if explain else None

        true_y = problem.query_label(i)
        known_examples.append(i)

        if explain:
            X_corr, y_corr = \
                problem.query_corrections(X_corr, y_corr, i, pred_y, pred_expl,
                                          X_test_tuples)

        X_known = vstack([X_corr, problem.X[known_examples]])
        y_known = hstack([y_corr, problem.y[known_examples]])
        per_class = np.array([len(y_known[y_known == label])
                            for label in range(len(problem.class_names))]) \
                    / len(y_known)
        balance = np.max(per_class) / np.min(per_class)
        learner.fit(X_known, y_known)
        params.append(learner.get_params())

        do_eval = t % eval_iters == 0
        #print('evaluating on known...')
        #known_perf = problem.eval(learner,
        #                    known_examples,
        #                    known_examples,
        #                    known_examples if do_eval else None,
        #                    t=t, basename=basename)
        known_perf = None
        print('evaluating on test|eval...')
        perf = problem.eval(learner,
                            known_examples,
                            test_examples,
                            eval_examples if do_eval else None,
                            t=t, basename=basename)
        n_corrections = len(y_corr) if y_corr is not None else 0
        perf += (n_corrections,)
        perfs.append(perf)

        # print('selecting model...')
        #if t >=5 and t % 5 == 0:
        #    learner.select_model(vstack([X_corr, problem.X[known_examples]]),
        #                         hstack([y_corr, problem.y[known_examples]]))

        params_for_print = np.round(learner.get_params(), decimals=1)
        print('{t:3d} : model = {params_for_print},  perfs on known = {known_perf},  perfs on test = {perf},  balance = {balance}'.format(**locals()))

    return perfs, params


def eval_interactive(problem, args, rng=None):
    """The main evaluation loop."""

    rng = check_random_state(args.seed)
    basename = _get_basename(args)

    folds = StratifiedKFold(n_splits=args.n_folds, random_state=0) \
                .split(problem.y, problem.y)

    perfs, params = [], []
    for k, (train_examples, test_examples) in enumerate(folds):
        print()
        print(80 * '=')
        print('Running fold {}/{}'.format(k + 1, args.n_folds))
        print(80 * '=')

        train_examples = list(train_examples)
        known_examples = _subsample(problem, train_examples,
                                    args.prop_known, rng=0)
        test_examples = list(test_examples)
        eval_examples = _subsample(problem, test_examples,
                                   args.prop_eval, rng=0)

        learner = LEARNERS[args.learner](problem, strategy=args.strategy, rng=0)

        perf, param = caipi(problem,
                            learner,
                            train_examples,
                            known_examples,
                            test_examples,
                            eval_examples,
                            max_iters=args.max_iters,
                            start_expl_at=args.start_expl_at,
                            eval_iters=args.eval_iters,
                            basename=basename + '_fold={}'.format(k),
                            rng=rng)
        perfs.append(perf)
        params.append(param)

        dump(basename + '.pickle', {'args': args, 'perfs': perfs})
        dump(basename + '-params.pickle', params)


def main():
    import argparse

    fmt_class = argparse.ArgumentDefaultsHelpFormatter
    parser = argparse.ArgumentParser(formatter_class=fmt_class)
    parser.add_argument('problem', choices=sorted(PROBLEMS.keys()),
                        help='name of the problem')
    parser.add_argument('learner', choices=sorted(LEARNERS.keys()),
                        default='svm', help='Active learner to use')
    parser.add_argument('strategy', type=str, default='random',
                        help='Query selection strategy to use')
    parser.add_argument('-s', '--seed', type=int, default=0,
                        help='RNG seed')

    group = parser.add_argument_group('Evaluation')
    group.add_argument('-k', '--n-folds', type=int, default=10,
                       help='Number of cross-validation folds')
    group.add_argument('-n', '--n-examples', type=int, default=None,
                       help='Restrict dataset to this many examples')
    group.add_argument('-p', '--prop-known', type=float, default=0.1,
                       help='Proportion of initial labelled examples')
    group.add_argument('-P', '--prop-eval', type=float, default=0.1,
                       help='Proportion of the test set to evaluate the '
                            'explanations on')
    group.add_argument('-T', '--max-iters', type=int, default=100,
                       help='Maximum number of learning iterations')
    group.add_argument('-e', '--eval-iters', type=int, default=10,
                       help='Interval for evaluating performance on the '
                       'evaluation set')
    group.add_argument('--passive', action='store_true',
                       help='DEBUG: eval perfs using passive learning')

    group = parser.add_argument_group('Interaction')
    group.add_argument('-E', '--start-expl-at', type=int, default=-1,
                       help='Iteration at which corrections kick in')
    group.add_argument('-F', '--n-features', type=int, default=10,
                       help='Number of LIME features to present the user')
    group.add_argument('-S', '--n-samples', type=int, default=5000,
                       help='Size of the LIME sampled dataset')
    group.add_argument('-K', '--kernel-width', type=float, default=0.75,
                       help='LIME kernel width')
    group.add_argument('-R', '--lime-repeats', type=int, default=1,
                       help='Number of times to re-run LIME')
    args = parser.parse_args()

    np.seterr(all='raise')
    np.set_printoptions(precision=3, linewidth=80, threshold=np.nan)
    np.random.seed(args.seed)

    rng = np.random.RandomState(args.seed)

    print('Creating problem...')
    problem = PROBLEMS[args.problem](n_examples=args.n_examples,
                                     n_samples=args.n_samples,
                                     n_features=args.n_features,
                                     kernel_width=args.kernel_width,
                                     lime_repeats=args.lime_repeats,
                                     rng=rng)

    if args.passive:
        print('Evaluating passive learning...')
        eval_passive(problem, args, rng=rng)
    else:
        print('Evaluating interactive learning...')
        eval_interactive(problem, args, rng=rng)

if __name__ == '__main__':
    main()
