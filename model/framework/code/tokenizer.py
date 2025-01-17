__all__ = ['SPE_Tokenizer', 'encode', 'isolate_glossary']

# Cell

import sys
import os
import inspect
import codecs
import io
import argparse
import re
import warnings
import random
sys.path.append('..')
from pretokenizer import *
from learner import *


class SPE_Tokenizer(object):
    """
    Tokenize SMILES based on the learned SPE tokens.

    codes: output file of `learn_SPE()`

    merges: number of learned SPE tokens you want to use. `-1` means using all of them. `1000` means use the most frequent 1000.

    exclusive_tokens: argument that passes to  `atomwise_tokenizer()`

    glossaries: argument that passes to `isolate_glossary()`

    dropout: See [BPE-Dropout: Simple and Effective Subword Regularization](https://arxiv.org/abs/1910.13267).
    If `dropout` is set to 0, the segmentation is equivalent to the standard BPE; if `dropout` is set to 1, the segmentation splits words into distinct characters.
    """

    def __init__(self, codes, merges=-1, glossaries=None, exclusive_tokens=None):

        codes.seek(0)
        offset=1

        self.bpe_codes = [tuple(item.strip('\r\n ').split(' ')) for (n, item) in enumerate(codes) if (n < merges or merges == -1)]

        for i, item in enumerate(self.bpe_codes):
            if len(item) != 2:
                sys.stderr.write('Error: invalid line {0} in BPE codes file: {1}\n'.format(i+offset, ' '.join(item)))
                sys.stderr.write('The line should exist of exactly two subword units, separated by whitespace\n')
                sys.exit(1)

        # some hacking to deal with duplicates (only consider first instance)
        self.bpe_codes = dict([(code,i) for (i,code) in reversed(list(enumerate(self.bpe_codes)))])

        self.bpe_codes_reverse = dict([(pair[0] + pair[1], pair) for pair,i in self.bpe_codes.items()])

        self.glossaries = glossaries if glossaries else []

        self.glossaries_regex = re.compile('^({})$'.format('|'.join(glossaries))) if glossaries else None

        self.exclusive_tokens = exclusive_tokens
        self.cache = {}

    def tokenize(self, smi, dropout=0):
        segments = [out for segment in self._isolate_glossaries(smi)
                    for out in encode(segment,
                                      self.bpe_codes,
                                      self.bpe_codes_reverse,
                                      self.cache,
                                      self.exclusive_tokens,
                                      self.glossaries_regex,
                                      dropout)]
        return ' '.join(segments)


    def _isolate_glossaries(self, word):
        word_segments = [word]
        for gloss in self.glossaries:
            word_segments = [out_segments for segment in word_segments
                                 for out_segments in isolate_glossary(segment, gloss)]
        return word_segments


def encode(orig, bpe_codes, bpe_codes_reverse, cache,
           exclusive_tokens=None, glossaries_regex=None, dropout=0):
    """Encode word based on list of SPE merge operations, which are applied consecutively.
    """

    if not dropout and orig in cache:
        return cache[orig]

    if glossaries_regex and glossaries_regex.match(orig):
        cache[orig] = (orig,)
        return (orig,)

    if len(orig) == 1:
        return orig

    word = atomwise_tokenizer(orig, exclusive_tokens=exclusive_tokens)

    while len(word) > 1:

        # get list of symbol pairs; optionally apply dropout
        pairs = [(bpe_codes[pair],i,pair) for (i,pair) in enumerate(zip(word, word[1:])) if (not dropout or random.random() > dropout) and pair in bpe_codes]

        if not pairs:
            break

        #get first merge operation in list of BPE codes
        bigram = min(pairs)[2]

        # find start position of all pairs that we want to merge
        positions = [i for (rank,i,pair) in pairs if pair == bigram]

        i = 0
        new_word = []
        bigram = ''.join(bigram)
        for j in positions:
            # merges are invalid if they start before current position. This can happen if there are overlapping pairs: (x x x -> xx x)
            if j < i:
                continue
            new_word.extend(word[i:j]) # all symbols before merged pair
            new_word.append(bigram) # merged pair
            i = j+2 # continue after merged pair
        new_word.extend(word[i:]) # add all symbols until end of word
        word = new_word

    word = tuple(word)

    cache[orig] = word
    return word

def isolate_glossary(word, glossary):
    """
    Isolate a glossary present inside a word.

    Returns a list of subwords. In which all 'glossary' glossaries are isolated.

    For example, if 'USA' is the glossary and '1934USABUSA' the word, the return value is:
        ['1934', 'USA', 'B', 'USA']
    """
    # regex equivalent of (if word == glossary or glossary not in word)
    if re.match('^'+glossary+'$', word) or not re.search(glossary, word):
        return [word]
    else:
        segments = re.split(r'({})'.format(glossary), word)
        segments, ending = segments[:-1], segments[-1]
        segments = list(filter(None, segments)) # Remove empty strings in regex group.
        return segments + [ending.strip('\r\n ')] if ending != '' else segments