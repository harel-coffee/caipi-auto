import numpy as np
from sklearn.utils import check_random_state
from textwrap import dedent

from .utils import TextMod


def mojito(problem, learner, explainer, train_examples, known_examples,
           max_iters=100, start_explaining_at=20, improve_explanations=True,
           rng=None):
    """An implementation of the Mojito algorithm.

    Parameters
    ----------
    problem : mojito.Problem
        The problem.
    learner : mojito.ActiveLearner
        The learner.
    explainer : mojito.Explainer
        The explainer.
    train_examples : list of int
        Indices of the training examples
    known_examples : list of int
        Indices of the examples whose label is known.
    max_iters : int, defaults to 100
        Maximum number of iterations.
    start_explaining_at : int, default to 20
        Iteration at which the explanation mechanic kicks in.
    improve_explanations : bool, defaults to True
        Whether to obtain feedback on the explanations.
    rng : numpy.RandomState, defaults to None
        The RNG.
    """
    rng = check_random_state(rng)

    train_examples = list(train_examples)
    known_examples = list(known_examples)
    test_examples = list(set(problem.examples) - set(train_examples))

    # Fit a model on the complete training set
    learner.fit(problem.X[train_examples], problem.Y[train_examples])
    full_perfs = problem.evaluate(learner,
                                  problem.X[test_examples],
                                  problem.Y[test_examples])

    # Fit an initial model on the known examples
    learner.fit(problem.X[known_examples], problem.Y[known_examples])
    trace = [problem.evaluate(learner,
                              problem.X[test_examples],
                              problem.Y[test_examples])]

    perfs = trace[-1]
    print(dedent('''\
            T={} #train={} #known={} #test={}
            full set perfs = {}
            starting perfs = {}
        ''').format(max_iters, len(train_examples), len(known_examples),
                    len(test_examples), full_perfs, perfs))

    explain = False
    for t in range(max_iters):
        if len(known_examples) == len(train_examples):
            break
        if 0 <= start_explaining_at <= t:
            explain = True

        # Select a query from the unknown examples
        i = learner.select_query(problem.X, problem.Y,
                                 set(train_examples) - set(known_examples))
        assert i in train_examples and i not in known_examples

        # Compute a prediction and an explanation
        x = problem.X[i]
        y = learner.predict(x.reshape(1, -1))

        x_explainable = problem.X_explainable[i]
        g, discrepancy = (None, -1) if not explain else \
            explainer.explain(problem, learner, x_explainable)

        # Ask the user
        y_bar = problem.improve(i, y)
        g_bar, discrepancy_bar = (None, -1) if not improve_explanations else \
            problem.improve_explanation(explainer, x_explainable, g)

        # Update the model
        # TODO learn from the improved explanation
        known_examples.append(i)
        learner.fit(problem.X[known_examples],
                    problem.Y[known_examples])

        # Record the model performance
        perfs = problem.evaluate(learner,
                                 problem.X[test_examples],
                                 problem.Y[test_examples])
        print('{t:3d} : example {i}, label {y} -> {y_bar}, perfs {perfs}'
                  .format(**locals()))
        if g is not None:
            print('model explanation (discrepancy {discrepancy}) =\n {g}'
                     .format(**locals()))
        if g_bar is not None:
            print('oracle explanation (discrepancy {discrepancy_bar}) =\n {g_bar}'
                     .format(**locals()))
            quit()

        trace.append(np.array(perfs))
    else:
        print('all examples processed in {} iterations'.format(t))

    return np.array(trace)
