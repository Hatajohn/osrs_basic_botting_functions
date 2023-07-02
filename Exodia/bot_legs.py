# Imports


# Handles the runtime of the bot session
class BotLegs():
    def __init__(self, mods=[], DEBUG=False) -> None:
        # Name for the update function that should appear in the other classes
        self._update = 'update'
        self._DEBUG = DEBUG
        self._mods = mods

        # Time period for updates, each game tick is 0.6 seconds but it probably isnt practical 
        # to try to sync the bot with the game w/o some sort of reading of the game client info
        self._t = 0.6


    # Run update on each bot object
    def update(self):
        # Updates in each object in order
        for m in self._mods:
            if hasattr(m, self._update) and callable(getattr(m, self._update)):
                m.update()