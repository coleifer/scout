#!/bin/bash
SCOUT_SETTINGS=test_fts4.cfg python tests.py
SCOUT_SETTINGS=test_fts4_no_c.cfg python tests.py
SCOUT_SETTINGS=test_fts5.cfg python tests.py
