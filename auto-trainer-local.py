import logging
import os

logging.basicConfig(level=logging.WARNING, format="%(asctime)s: %(levelname)s: %(name)s: %(message)s")
logging.getLogger("transitions").setLevel(logging.WARNING)
logging.getLogger("tools").setLevel(logging.WARNING)
logging.getLogger("autotrainer").setLevel(logging.WARNING)
logging.getLogger("inference_algorithms").setLevel(logging.WARNING)


def configure_telemetry(endpoint: str):
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")

    if endpoint is None:
        return

    from opentelemetry.sdk.resources import SERVICE_NAME, Resource

    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    from opentelemetry import metrics
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    resource = Resource(attributes={SERVICE_NAME: "auto-trainer"})

    trace_provider = TracerProvider(resource=resource)
    processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    trace_provider.add_span_processor(processor)
    trace.set_tracer_provider(trace_provider)

    reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"))
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)


if __name__ == '__main__':
    import sys
    import argparse
    import faulthandler
    from multiprocessing import set_start_method
    from tools.acquisition.run_acquisition import run_acquisition

    faulthandler.enable()

    set_start_method("spawn")

    parser = argparse.ArgumentParser()

    parser.add_argument("-c", "--configuration", help="configuration file", default=None, type=str)
    parser.add_argument("-t", "--telemetry", help="telemetry endpoint", default=None, type=str)
    parser.add_argument("-d", "--dev", help="enable development mode and options", action="store_true")
    parser.add_argument("-e", "--allow-can-emulation", help="include CAN emulation as a connection option",
                        default="", type=str)

    args = parser.parse_args()

    # strtobool compatibility is all over the place.
    allow_emulation = args.allow_can_emulation.lower() in ["true", "yes", "1"]

    if args.telemetry:
        configure_telemetry(args.telemetry)

    if run_acquisition(args.configuration, args.dev, allow_emulation):
        sys.exit(0)
    else:
        sys.exit(1)
