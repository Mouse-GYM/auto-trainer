import multiprocessing


def get_mp_ctx():
    return multiprocessing.get_context("spawn")
