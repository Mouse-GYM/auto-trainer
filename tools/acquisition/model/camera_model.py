class CameraModel:
    def __init__(self, name: str = "Random Image", url: str = "random://anything"):
        self._name = name
        self._url = url

    def __repr__(self):
        return f"({self._name}: {self._url})"

    @property
    def name(self):
        return self._name

    @property
    def url(self):
        return self._url
