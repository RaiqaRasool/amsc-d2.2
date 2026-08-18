import sys
import types
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch


class FakeArchiverConfig:
    protocol = "http"
    myquery_server = "epicsweb.jlab.org"

    def set(self, **values):
        for name, value in values.items():
            setattr(self, name, value)


fake_client = types.ModuleType("jlab_archiver_client")
for class_name in (
    "Channel",
    "ChannelQuery",
    "Interval",
    "IntervalQuery",
    "MySampler",
    "MySamplerQuery",
    "MyStats",
    "MyStatsQuery",
    "Point",
    "PointQuery",
):
    setattr(fake_client, class_name, type(class_name, (), {}))

fake_client_config = types.ModuleType("jlab_archiver_client.config")
fake_client_config.config = FakeArchiverConfig()
fake_dotenv = types.ModuleType("dotenv")
fake_dotenv.load_dotenv = lambda: None
sys.modules["jlab_archiver_client"] = fake_client
sys.modules["jlab_archiver_client.config"] = fake_client_config
sys.modules.setdefault("dotenv", fake_dotenv)

import mya_query


class FakeData:
    empty = False


class MyaQueryConfigTests(unittest.TestCase):
    def test_archiver_endpoint_uses_application_config(self):
        self.assertEqual(mya_query.MYQUERY_PROTOCOL, mya_query.archiver_config.protocol)
        self.assertEqual(mya_query.MYQUERY_SERVER, mya_query.archiver_config.myquery_server)

    @patch("mya_query.MySampler")
    @patch("mya_query.MySamplerQuery")
    def test_mysampler_uses_application_deployment(self, query_class, sampler_class):
        sampler_class.return_value.data = FakeData()

        mya_query.run_mysampler(datetime(2026, 1, 1), 1000, 1, ["pv"])

        query_class.assert_called_once_with(
            start=datetime(2026, 1, 1),
            interval=1000,
            num_samples=1,
            pvlist=["pv"],
            deployment=mya_query.MYA_DEPLOYMENT,
        )

    @patch("mya_query.Interval")
    @patch("mya_query.IntervalQuery")
    def test_interval_uses_application_deployment(self, query_class, interval_class):
        interval_class.return_value.data = FakeData()

        mya_query.run_interval("2026-01-01", "2026-01-02", channel="pv")

        query_class.assert_called_once_with(
            channel="pv",
            begin=datetime(2026, 1, 1),
            end=datetime(2026, 1, 2),
            prior_point=True,
            deployment=mya_query.MYA_DEPLOYMENT,
        )

    @patch("mya_query.MyStats")
    @patch("mya_query.MyStatsQuery")
    def test_mystats_uses_application_deployment(self, query_class, stats_class):
        stats_class.return_value.data = FakeData()

        mya_query.run_mystats("2026-01-01", "2026-01-02", 1, ["pv"])

        self.assertEqual(
            mya_query.MYA_DEPLOYMENT,
            query_class.call_args.kwargs["deployment"],
        )

    @patch("mya_query.Point")
    @patch("mya_query.PointQuery")
    def test_point_uses_application_deployment(self, query_class, point_class):
        point_class.return_value.data = MagicMock()

        mya_query.run_point("pv", "2026-01-01")

        self.assertEqual(
            mya_query.MYA_DEPLOYMENT,
            query_class.call_args.kwargs["deployment"],
        )

    @patch("mya_query.Channel")
    @patch("mya_query.ChannelQuery")
    def test_channel_uses_application_deployment(self, query_class, channel_class):
        channel_class.return_value.data = []

        mya_query.run_channel("pv%")

        query_class.assert_called_once_with(
            pattern="pv%",
            deployment=mya_query.MYA_DEPLOYMENT,
        )


if __name__ == "__main__":
    unittest.main()
