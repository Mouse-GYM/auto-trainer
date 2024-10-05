from autotrainer.core import ObservableObject


class MockPelletDelivery(ObservableObject):
    def __init__(self):
        super().__init__(event_names=("ack_received",))

    def send_ack(self):
        self.ack_received("ACK")

    def load_pellet(self):
        pass

    def send_pellet(self):
        pass

    def release_pellet(self):
        pass
