# Imports


# Handles the runtime of the bot session
class BotLegs():
    def __init__(self, mods=[], DEBUG=False) -> None:
        self._update = 'update'
        self._DEBUG = DEBUG
        self._mods = mods


    # Run update on each bot module
    def update(self):
        for m in self._mods:
            if hasattr(m, self._update) and callable(getattr(m, self._update)):
                m.update()