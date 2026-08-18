from datetime import datetime

from jlab_archiver_client import (
    Channel,
    ChannelQuery,
    Interval,
    IntervalQuery,
    MySampler,
    MySamplerQuery,
    MyStats,
    MyStatsQuery,
    Point,
    PointQuery,
)
from jlab_archiver_client.config import config as archiver_config

from config import MYA_DEPLOYMENT, MYQUERY_PROTOCOL, MYQUERY_SERVER


archiver_config.set(
    myquery_server=MYQUERY_SERVER,
    protocol=MYQUERY_PROTOCOL,
)


VALID_QUERY_TYPES = {"mysampler", "interval", "mystats", "point", "channel"}


def run_mya_query(query_type, query_params):
    dispatch = {
        "mysampler": run_mysampler,
        "interval": run_interval,
        "mystats": run_mystats,
        "point": run_point,
        "channel": run_channel,
    }
    query_function = dispatch.get(query_type)
    if query_function is None:
        raise ValueError(f"Unknown MYA query type: {query_type}")
    return query_function(**query_params)


def run_mysampler(start: datetime, interval: int, num_samples: int, pvlist: list[str]):
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    query = MySamplerQuery(
        start=start,
        interval=interval,
        num_samples=num_samples,
        pvlist=pvlist,
        deployment=MYA_DEPLOYMENT,
    )
    sampler = MySampler(query)
    sampler.run()

    if sampler.data is None or sampler.data.empty:
        raise RuntimeError(f"MySampler returned no data for PVs: {pvlist}")
    return sampler.data


def run_interval(
    begin,
    end,
    prior_point=True,
    pvlist=None,
    channel=None,
):
    begin = datetime.fromisoformat(begin) if isinstance(begin, str) else begin
    end = datetime.fromisoformat(end) if isinstance(end, str) else end
    if pvlist:
        query = IntervalQuery(
            pvlist=pvlist,
            begin=begin,
            end=end,
            prior_point=prior_point,
            deployment=MYA_DEPLOYMENT,
        )
        data = Interval.run_parallel(query)
    elif channel:
        query = IntervalQuery(
            channel=channel,
            begin=begin,
            end=end,
            prior_point=prior_point,
            deployment=MYA_DEPLOYMENT,
        )
        interval_query = Interval(query)
        interval_query.run()
        data = interval_query.data
    else:
        raise ValueError("Interval query requires pvlist or channel.")

    if data is None or (hasattr(data, "empty") and data.empty):
        raise RuntimeError("Interval query returned no data.")
    return data


def run_mystats(start, end, num_bins, pvlist):
    start = datetime.fromisoformat(start) if isinstance(start, str) else start
    end = datetime.fromisoformat(end) if isinstance(end, str) else end
    query = MyStatsQuery(
        start=start,
        end=end,
        num_bins=num_bins,
        pvlist=pvlist,
        deployment=MYA_DEPLOYMENT,
    )
    stats = MyStats(query)
    stats.run()
    if stats.data is None or stats.data.empty:
        raise RuntimeError(f"MyStats returned no data for PVs: {pvlist}")
    return stats.data


def run_point(channel, time):
    time = datetime.fromisoformat(time) if isinstance(time, str) else time
    query = PointQuery(channel=channel, time=time, deployment=MYA_DEPLOYMENT)
    point = Point(query)
    point.run()
    if point.data is None:
        raise RuntimeError(f"Point query returned no data for channel: {channel}")
    return point.data


def run_channel(pattern):
    query = ChannelQuery(pattern=pattern, deployment=MYA_DEPLOYMENT)
    channel = Channel(query)
    channel.run()
    return channel.data if channel.data is not None else []
