#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Tests for utils module."""

import os

import pandas as pd
from nose.tools import assert_equal, assert_true

from sosia.utils import FIELDS_JOURNALS_LIST


def test_create_fields_journals_list():
    try:
        os.remove(FIELDS_JOURNALS_LIST)
    except FileNotFoundError:
        pass
    sosia.create_fields_journals_list()
    df = pd.read_csv(FIELDS_JOURNALS_LIST)
    assert_true(isinstance(df, pd.DataFrame))
    assert_equal(list(df.columns), ['asjc', 'source_id'])
    assert_true(df.shape[0] > 197920)
