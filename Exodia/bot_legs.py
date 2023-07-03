# Imports
import time

# Handles the runtime of the bot session
class BotLegs():
    def __init__(self, mods=[], DEBUG=False) -> None:
        # Name for the update function that should appear in the other classes
        self._update = 'update'
        self._DEBUG = DEBUG
        self._mods = mods
        self.flag = False

        # Time period for updates, each game tick is 0.6 seconds but it probably isnt practical 
        # to try to sync the bot with the game w/o some sort of reading of the game client info
        self._t = 1.0

        # Max amount of time I want the bot to be running
        self._max = 60


    # Run update on each bot object
    def update(self):
        # Updates in each object in order
        for m in self._mods:
            if hasattr(m, self._update) and callable(getattr(m, self._update)):
                try: 
                    m.update()
                except:
                    print('Something went wrong!')
                    self.flag = True
                    break


    # Updates the bot every _t seconds
    def bot_loop(self):
        self.update()
        end = 0
        last_time = time.time()
        # Something else needs to stop this
        while(not self.flag):
            curr_time = time.time()
            # If we have passed the time period, we need to update each object legs is watching
            if (time.time() - last_time) > self._t:
                self.update()
                last_time = curr_time
            end += time.time() - last_time
            if end > self._max:
                self.flag = True
            
