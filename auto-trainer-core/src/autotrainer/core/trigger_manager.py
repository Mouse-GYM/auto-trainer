CAPTURE_TRIGGER_ID = "CaptureTrigger"

_ALL_TRIGGERS = ""


class TriggerManager:
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = TriggerManager("InstanceTriggerManager")

        return cls._instance

    def __init__(self, key=""):
        if key != "InstanceTriggerManager":
            raise Exception("Use TriggerManager.instance()")

        self._triggers_by_id = dict()

        self._triggers_by_id[_ALL_TRIGGERS] = list()

    def register(self, sink, trigger_id: str = _ALL_TRIGGERS):
        funcs = self._triggers_by_id.get(trigger_id)

        if funcs is None:
            funcs = list()
            self._triggers_by_id[trigger_id] = funcs

        funcs.append(sink)

    def unregister(self, sink, trigger_id: str = _ALL_TRIGGERS):
        funcs = self._triggers_by_id.get(trigger_id)

        if funcs is None:
            return

        try:
            funcs.remove(sink)
        except ValueError:
            pass

    def trigger(self, sender: object, trigger_id: str, context: object = None):
        funcs = self._triggers_by_id.get(_ALL_TRIGGERS)

        for f in funcs:
            f(sender, trigger_id, context)

        funcs = self._triggers_by_id.get(trigger_id)

        if funcs is None:
            return

        for f in funcs:
            f(sender, trigger_id, context)
