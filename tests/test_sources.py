import os
import unittest
from unittest.mock import patch

from amazon_scout.sources.base import PaidProviderBudget, SourceAvailability
from amazon_scout.sources.codex_web import CodexWebSource
from amazon_scout.sources.dataforseo import DataForSEOSource
from amazon_scout.sources.provenance import choose_preferred, source_priority
from amazon_scout.sources.rainforest import RainforestSource
from amazon_scout.sources.serpapi import SerpApiSource


class SourceTests(unittest.TestCase):
    def test_source_priority(self):
        self.assertGreater(source_priority("sp_api"), source_priority("codex_web"))
        self.assertGreater(source_priority("dataforseo", "amazon_search_volume"), source_priority("codex_web", "amazon_search_volume"))

    def test_paid_provider_disabled(self):
        with self.assertRaises(PermissionError): PaidProviderBudget().authorize()

    def test_paid_call_and_cost_limits(self):
        budget = PaidProviderBudget(True, 1, .10)
        budget.authorize(.05)
        with self.assertRaises(PermissionError): budget.authorize(.01)
        with self.assertRaises(PermissionError): PaidProviderBudget(True, 2, .01).authorize(.02)

    def test_source_fallback_statuses(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(SerpApiSource().status().availability, SourceAvailability.NOT_CONFIGURED)
            self.assertEqual(RainforestSource().status().availability, SourceAvailability.NOT_CONFIGURED)
            self.assertEqual(DataForSEOSource().status().availability, SourceAvailability.NOT_CONFIGURED)
            self.assertEqual(CodexWebSource().status().availability, SourceAvailability.READY)

    def test_dataforseo_uae_is_fail_closed(self):
        with patch.dict(os.environ, {"DATAFORSEO_LOGIN":"x", "DATAFORSEO_PASSWORD":"y"}, clear=True):
            self.assertEqual(DataForSEOSource().status().availability, SourceAvailability.UNSUPPORTED_FOR_UAE)
            with self.assertRaises(RuntimeError): DataForSEOSource().amazon_labs_request()
