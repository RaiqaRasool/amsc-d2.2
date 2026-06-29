from datetime import datetime

from jlab_archiver_client import MySampler, MySamplerQuery


def run_mysampler(start: datetime, interval: int, num_samples: int, pvlist: list[str]):
    query = MySamplerQuery(
        start=start,
        interval=interval,
        num_samples=num_samples,
        pvlist=pvlist,
    )
    sampler = MySampler(query)
    sampler.run()

    if sampler.data is None or sampler.data.empty:
        raise RuntimeError(f"MySampler returned no data for PVs: {pvlist}")
    return sampler.data
