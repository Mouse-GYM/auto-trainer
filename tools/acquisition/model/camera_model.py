class CameraModel:
    def __init__(self, name: str = "Random Image", url: str = "random://anything"):
        self._name = name
        self._url = url

    @property
    def name(self):
        return self._name

    @property
    def url(self):
        return self._url
