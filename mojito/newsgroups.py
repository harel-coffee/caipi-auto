import numpy as np
import nltk
from os.path import join
from lime.lime_text import LimeTextExplainer
from sklearn.datasets import fetch_20newsgroups
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.metrics import precision_recall_fscore_support as prfs

from .problems import Problem
from .utils import TextMod, load, dump


class NewsgroupsProblem(Problem):
    """Document classification.

    Partially ripped from https://marcotcr.github.io/lime
    """
    def __init__(self, labels=None, rng=None):

        path = join('cache', '20newsgroups.pickle')
        try:
            print('loading 20newsgroups...')
            dataset, self.processed_data = load(path)
        except:
            print('failed, preprocessing 20newsgroups...')
            # NOTE let's keep the quotes, they are pretty informative --
            # although maybe they leak test data in the training set?
            dataset = fetch_20newsgroups(subset='all',
                                         remove=('headers', 'footers'),
                                         random_state=rng)
            self.processed_data = self.preprocess(dataset.data)

            print('caching preprocessed dataset...')
            dump(path, (dataset, self.processed_data))

        # TODO distinguish between learner's and explainer's features
        vectorizer = TfidfVectorizer(lowercase=False)
        self.vectorizer = vectorizer.fit(self.processed_data)

        self.X = vectorizer.transform(self.processed_data)
        self.Y = dataset.target
        self.examples = list(range(len(dataset.target)))
        self.data = dataset.data
        self.labels = labels or dataset.target_names

    @staticmethod
    def preprocess(data):
        """Reduces documents to lists of adjectives, nouns, and verbs."""

        VALID_TAGS = set([
            'FW',   # Foreign word
            'JJ',   # Adjective
            'JJR',  # Adjective, comparative
            'JJS',  # Adjective, superlative
            'NN',   # Noun, singular or mass
            'NNS',  # Noun, plural
            'NNP',  # Proper noun, singular
            'NNPS', # Proper noun, plural
            'UH',   # Interjection
            'VB',   # Verb, base form
            'VBD',  # Verb, past tense
            'VBG',  # Verb, gerund or present participle
            'VBN',  # Verb, past participle
            'VBP',  # Verb, non-3rd person singular present
            'VBZ',  # Verb, 3rd person singular present
        ])

        processed_data = []
        for i, text in enumerate(data):
            print('preprocessing document {} of {}'.format(i, len(data)))
            processed_text = ' '.join(token for token, tag
                                      in nltk.pos_tag(nltk.word_tokenize(text))
                                      if tag in VALID_TAGS)
            processed_data.append(processed_text)
        return processed_data

    def explain(self, learner, train_examples, example, num_samples=5000):
        # TODO pass num_samples in
        explainer = LimeTextExplainer(class_names=self.labels, verbose=True)
        local_model = Ridge(alpha=1, fit_intercept=True)
        pipeline = make_pipeline(self.vectorizer, learner.model_)
        explanation = explainer.explain_instance(self.processed_data[example],
                                                 pipeline.predict_proba,
                                                 model_regressor=local_model,
                                                 num_features=10)
        # TODO extract datapoints, coefficients, intercept, discrepancy
        return explanation, -1

    def improve(self, example, y):
        return self.Y[example]

    @staticmethod
    def highlight_words(text, explanation):
        import re

        for word, coeff in explanation.as_list():
            colored_word = TextMod.UNDERLINE + TextMod.BOLD + \
                           (TextMod.RED if coeff < 0 else TextMod.GREEN) + \
                           word + TextMod.END
            matches = list(re.compile(r'\b' + word + r'\b').finditer(text))
            matches.reverse()
            for match in matches:
                start = match.start()
                text = text[:start] + colored_word + text[start+len(word):]
        return text

    def improve_explanation(self, example, y, explanation):
        class_color = TextMod.BOLD + TextMod.GREEN if y else TextMod.RED
        class_name = class_color + self.labels[y] + TextMod.END

        print('The model thinks that this document:')
        print('=' * 80 + '\n')
        print(self.highlight_words(self.data[example], explanation))
        print('\n' + '=' * 80)
        print('is {}, because of these words:'.format(class_name))
        for word, coeff in explanation.as_list():
            color = TextMod.RED if coeff < 0 else TextMod.GREEN
            coeff = TextMod.BOLD + color + '{:+3.1f}'.format(coeff) + TextMod.END
            word = TextMod.BOLD + word + TextMod.END
            print('  {:16s} : {}'.format(word, coeff))

        # TODO acquire improved explanation

        return explanation, -1

    def evaluate(self, learner, examples):
        return prfs(self.Y[examples],
                    learner.predict(self.X[examples]),
                    average='weighted')[:3]