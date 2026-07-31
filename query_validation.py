from datetime import datetime, timedelta


MAX_PVS = 100
MAX_PV_LENGTH = 256
MAX_SAMPLES = 100_000
MAX_BINS = 10_000
MAX_QUERY_WINDOW = timedelta(days=31)


def validate_query_params(query_type, params):
    pvlist = params.get("pvlist", [])
    if len(pvlist) > MAX_PVS or any(len(pv) > MAX_PV_LENGTH for pv in pvlist):
        raise ValueError

    for field in ("channel", "pattern"):
        value = params.get(field, "")
        if len(value) > MAX_PV_LENGTH:
            raise ValueError

    if query_type == "mysampler" and params["num_samples"] > MAX_SAMPLES:
        raise ValueError
    if query_type == "mystats" and params["num_bins"] > MAX_BINS:
        raise ValueError

    time_fields = {
        "interval": ("begin", "end"),
        "mystats": ("start", "end"),
    }
    if query_type in time_fields:
        start_field, end_field = time_fields[query_type]
        start = datetime.fromisoformat(params[start_field])
        end = datetime.fromisoformat(params[end_field])
        if end - start > MAX_QUERY_WINDOW:
            raise ValueError
