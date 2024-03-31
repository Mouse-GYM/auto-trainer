from multiprocessing import Process


class DeviceProcess(Process):
    def __init__(self):
        super().__init__()

    def run(self):
        while True:
            pass
